"""The cc component leaves no cc filter in the namespace."""

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.cc.cc import CC
from phenix_apps.apps.scorch.conftest import scorch_experiment

MODULE = "phenix_apps.apps.scorch.cc.cc"
NODES = [
    {
        "type": "VirtualMachine",
        "general": {"hostname": "vm-1"},
        "hardware": {"os_type": "linux"},
        "network": {"interfaces": []},
    }
]


@pytest.fixture
def mm(mocker, monkeypatch, tmp_path):
    """The namespace's minimega, with the cc helpers aiming its filter as they do."""
    monkeypatch.setattr("phenix_apps.apps.scorch.app.PHENIX_DIR", str(tmp_path))
    (tmp_path / "images" / "exp").mkdir(parents=True)

    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)

    def filter_vm(mm, vm, **_):
        mm.cc_filter(f"uuid={vm}-uuid")
        return f"{vm}-uuid", "host"

    def exec_wait(mm, vm, cmd, **_):
        filter_vm(mm, vm)
        mm.cc_exec_once(cmd)
        return {"exitcode": 0, "stdout": "vm-1", "stderr": ""}

    mocker.patch(f"{MODULE}.utils.mm_cc_filter_vm", side_effect=filter_vm)
    mocker.patch(f"{MODULE}.utils.mm_exec_wait", side_effect=exec_wait)
    mocker.patch(
        f"{MODULE}.utils.mm_cc_send_wait",
        side_effect=lambda mm, vm, *_: filter_vm(mm, vm),
    )
    return fake


def _start(component_args, metadata):
    component_args(
        scorch_experiment(
            [{"name": "cc", "type": "cc", "metadata": metadata}],
            [{"start": ["cc"]}],
            NODES,
        ),
        "start",
        "cc",
    )
    CC()


def test_top_level_exec_clears_its_filter(component_args, mm, mocker):
    _start(
        component_args,
        {"start": [{"type": "exec", "filter": "hostname=vm-1", "args": "true"}]},
    )

    assert mm.method_calls == [
        mocker.call.cc_filter("hostname=vm-1"),
        mocker.call.cc_exec_once("true"),
        mocker.call.clear_cc_filter(),
    ]


def test_failed_top_level_exec_still_clears_its_filter(component_args, mm, mocker):
    mm.cc_exec.side_effect = RuntimeError("minimega refused")

    with pytest.raises(RuntimeError, match="minimega refused"):
        _start(
            component_args,
            {
                "start": [
                    {
                        "type": "exec",
                        "filter": "hostname=vm-1",
                        "once": False,
                        "args": "true",
                    }
                ]
            },
        )

    assert mm.method_calls[-1] == mocker.call.clear_cc_filter()


@pytest.mark.parametrize(
    "step",
    [
        {"type": "exec", "args": "hostname"},
        {"type": "exec", "args": "hostname", "wait": True},
        {"type": "background", "args": "sleep 600"},
    ],
    ids=["exec", "exec-wait", "background"],
)
def test_vm_steps_clear_the_filters_they_set(component_args, mm, mocker, step):
    _start(component_args, {"vms": [{"hostname": "vm-1", "start": [step]}]})

    calls = [c[0] for c in mm.method_calls]
    assert calls.count("cc_filter") == 2  # the script's send, then the step
    assert calls.count("clear_cc_filter") == 2
    assert mm.method_calls[-1] == mocker.call.clear_cc_filter()
