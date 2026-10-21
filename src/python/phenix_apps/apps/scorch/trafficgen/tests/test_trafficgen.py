"""Client commands the trafficgen component starts, and the cc filter it leaves."""

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.trafficgen.trafficgen import TrafficGen
from phenix_apps.common import settings, utils

SCRIPTS = {
    "trafficServer": "/scripts/traffic-server.py",
    "backgroundGen": "/scripts/background-gen.py",
    "malwareGen": "/scripts/malware-gen.py",
}

NODES = [
    {
        "type": "VirtualMachine",
        "general": {"hostname": "traffic-server"},
        "hardware": {"os_type": "linux"},
        "network": {"interfaces": [{"name": "IF0", "address": "10.0.0.10"}]},
    }
]

BACKGROUND = {"hostname": "background-gen", "rate": 10000, "probability": 0.01}
MALWARE = {"hostname": "malware-gen", "rate": 7, "probability": 0.5}


@pytest.fixture
def mm(mocker):
    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    mocker.patch("phenix_apps.apps.scorch.trafficgen.trafficgen.time.sleep")
    mocker.patch.object(
        utils, "mm_cc_client_locate", side_effect=lambda _mm, vm, **_: (vm, "host")
    )
    return fake


def _start(component_args, target, stage="start"):
    target = {"hostname": "traffic-server", "duration": 3, **target}
    metadata = {"scripts": SCRIPTS, "targets": [target]}
    component_args(
        scorch_experiment(
            [{"name": "tg", "type": "trafficgen", "metadata": metadata}],
            [{"start": ["tg"], "stop": ["tg"], "cleanup": ["tg"]}],
            NODES,
        ),
        stage,
        "tg",
    )
    TrafficGen()


def _malware_command(mm):
    (cmd,) = [
        c.args[0]
        for c in mm.cc_background_once.call_args_list
        if "malware-gen" in c.args[0]
    ]
    return cmd


@pytest.mark.parametrize(
    "target",
    [
        {"malwareClient": MALWARE},
        {"backgroundClient": BACKGROUND, "malwareClient": MALWARE},
    ],
    ids=["malware-only", "both"],
)
def test_malware_client_uses_its_own_settings(component_args, mm, target):
    _start(component_args, target)

    assert _malware_command(mm) == (
        "python3 /malware-gen.py --ip 10.0.0.10 --rate 7 --duration 3 --probability 0.5"
    )


def test_malware_client_defaults(component_args, mm):
    _start(component_args, {"malwareClient": {"hostname": "malware-gen"}})

    assert "--rate 20 " in _malware_command(mm)
    assert _malware_command(mm).endswith("--probability 1.25")


BOTH = {"backgroundClient": BACKGROUND, "malwareClient": MALWARE}


@pytest.mark.parametrize(
    ("stage", "commands"),
    [
        (
            "start",
            [
                ("cc_background_once", "python3 /traffic-server.py", "traffic-server"),
                (
                    "cc_background_once",
                    "python3 /background-gen.py --ip 10.0.0.10 --rate 10000 "
                    "--duration 3 --probability 0.01",
                    "background-gen",
                ),
                (
                    "cc_background_once",
                    "python3 /malware-gen.py --ip 10.0.0.10 --rate 7 --duration 3 "
                    "--probability 0.5",
                    "malware-gen",
                ),
            ],
        ),
        (
            "stop",
            [
                ("cc_exec_once", "pkill -f traffic-server.py", "traffic-server"),
                ("cc_exec_once", "pkill -f background-gen.py", "background-gen"),
                ("cc_exec_once", "pkill -f malware-gen.py", "malware-gen"),
            ],
        ),
        (
            "cleanup",
            [
                ("cc_exec_once", "rm /traffic-server.py", "traffic-server"),
                ("cc_exec_once", "rm /background-gen.py", "background-gen"),
                ("cc_exec_once", "rm /malware-gen.py", "malware-gen"),
            ],
        ),
    ],
)
def test_stage_runs_each_command_on_its_vm_then_clears_the_cc_filter(
    component_args, cc_namespace, mocker, stage, commands
):
    mocker.patch("phenix_apps.apps.scorch.trafficgen.trafficgen.time.sleep")

    _start(component_args, BOTH, stage)

    assert cc_namespace.queued == [(m, c, f"name={vm}") for m, c, vm in commands]
    assert cc_namespace.filter is None


def test_failed_start_still_clears_the_cc_filter(component_args, cc_namespace, mocker):
    mocker.patch("phenix_apps.apps.scorch.trafficgen.trafficgen.time.sleep")
    cc_namespace.mm.cc_background_once.side_effect = RuntimeError("no client")

    with pytest.raises(RuntimeError, match="no client"):
        _start(component_args, BOTH)

    assert cc_namespace.filter is None


@pytest.mark.parametrize(
    ("stage", "error"),
    [
        ("stop", "could not stop traffic"),
        ("cleanup", "could not delete traffic scripts"),
    ],
)
def test_teardown_reaches_every_vm_when_one_has_no_client(
    component_args, cc_namespace, mocker, stage, error
):
    """mm_cc_once raises for a VM whose miniccc client never registers."""

    def locate(_mm, vm, **_):
        if vm == "traffic-server":
            raise RuntimeError("no cc client for traffic-server")
        return vm, "host"

    mocker.patch.object(utils, "mm_cc_client_locate", side_effect=locate)

    with pytest.raises(RuntimeError, match=f"{error} in traffic-server: no cc"):
        _start(component_args, BOTH, stage)

    assert [vm for _, _, vm in cc_namespace.queued] == [
        "name=background-gen",
        "name=malware-gen",
    ]
    assert cc_namespace.filter is None


@pytest.mark.parametrize(
    ("stage", "error"),
    [
        ("stop", "could not stop traffic"),
        ("cleanup", "could not delete traffic scripts"),
    ],
)
def test_teardown_waits_only_the_teardown_grace_for_a_vm_without_a_client(
    component_args, cc_namespace, unregistered, stage, error
):
    """phenix gives a canceled run's stop and cleanup stages 4 minutes in all,
    less than the client grace a start waits."""
    unregistered.vms.add("traffic-server")

    with pytest.raises(
        RuntimeError,
        match=f"{error} in traffic-server: timed out after "
        f"{settings.CC_TEARDOWN_GRACE}s",
    ):
        _start(component_args, BOTH, stage)

    assert unregistered.now <= settings.CC_TEARDOWN_GRACE + settings.CC_POLL_RATE
    assert [vm for _, _, vm in cc_namespace.queued] == [
        "name=background-gen",
        "name=malware-gen",
    ]
