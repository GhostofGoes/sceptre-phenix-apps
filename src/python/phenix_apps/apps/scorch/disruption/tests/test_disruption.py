"""When the disruption starts, how long the dos disruption waits for its script,
and the cc filter it leaves."""

from datetime import UTC, datetime

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.disruption.disruption import Disruption


def _node(hostname, address):
    return {
        "type": "VirtualMachine",
        "general": {"hostname": hostname},
        "hardware": {"os_type": "linux"},
        "network": {"interfaces": [{"name": "eth0", "address": address}]},
    }


NODES = [_node("attacker", "10.0.0.66"), _node("load5", "10.0.0.5")]


@pytest.mark.parametrize(
    ("run_duration", "start_delay", "attack_duration", "run_for"),
    [
        (300.0, 10.0, 20.0, 20.0),
        (300.0, 0.0, 20.0, 20.0),
        # Clamped so the attack and its wrap-up fit in run_duration.
        (100.0, 10.0, 60.0, 29.0),
        # Fits within a second of run_duration, so it is not lengthened.
        (120.0, 5.0, 51.0, 51.0),
        (120.0, 5.0, 54.0, 54.0),
    ],
)
def test_dos_waits_for_the_delay_and_the_attack(
    component_args, mocker, run_duration, start_delay, attack_duration, run_for
):
    run = _run_timed_dos(
        component_args, mocker, run_duration, start_delay, attack_duration
    )

    host, cmd = run.call_args.args
    assert host == "attacker"
    assert f"--wait-for {start_delay} --run-for {run_for} " in cmd
    assert "--target-ips 10.0.0.5 " in cmd
    # The script sleeps --wait-for, attacks for --run-for, then writes results.
    timeout = run.call_args.kwargs["timeout"]
    assert timeout == start_delay + run_for + 60.0
    assert timeout <= run_duration


@pytest.mark.parametrize(
    ("run_duration", "start_delay"), [(30.0, 5.0), (60.0, 5.0), (66.0, 5.0)]
)
def test_dos_without_time_for_an_attack_fails(
    component_args, mocker, run_duration, start_delay
):
    with pytest.raises(RuntimeError, match="leaves no time for a dos attack"):
        _run_timed_dos(component_args, mocker, run_duration, start_delay, 10.0)


def test_cyber_physical_shortens_its_dos_attack_the_same_way(component_args, mocker):
    mm = mocker.MagicMock()
    mocker.patch(
        "phenix_apps.apps.scorch.disruption.disruption.utils.mm_cc_client_locate",
        return_value=("attacker-uuid", "host"),
    )
    mocker.patch.object(Disruption, "_run_physical_disruption", return_value=0.0)
    mocker.patch.object(Disruption, "_kill_phys_process")
    mocker.patch(
        "phenix_apps.apps.scorch.disruption.disruption.utils.read_json",
        return_value={"scenario_duration": 2.0, "stages": {}},
    )

    _run_timed_dos(
        component_args,
        mocker,
        120.0,
        5.0,
        51.0,
        disruption="cyber_physical",
        physical={
            "start_delay": 1.0,
            "opc_hostname": "opc",
            "script_path": "/opc/physical.py",
            "results_path": "/opc/results.json",
            "scenario_path": "/opc/scenario.json",
            "log_path": "/opc/physical.log",
        },
        mm=mm,
    )

    # Once: minimega resends any other command to a client that reconnects.
    mm.cc_background.assert_not_called()
    assert "--wait-for 5.0 --run-for 51.0 " in mm.cc_background_once.call_args.args[0]


def _run_timed_dos(
    component_args,
    mocker,
    run_duration,
    start_delay,
    attack_duration,
    disruption="dos",
    mm=None,
    **extra,
):
    """Run the dos start stage and return its mocked run_and_check_command."""
    metadata = {
        "current_disruption": disruption,
        "run_duration": run_duration,
        **extra,
        "dos": {
            "start_delay": start_delay,
            "attack_duration": attack_duration,
            "attacker": {
                "hostname": "attacker",
                "script_path": "/root/dos.py",
                "results_path": "/root/results.json",
            },
            "targets": [{"hostname": "load5"}],
        },
    }
    component_args(
        scorch_experiment(
            [{"name": "disruption", "type": "disruption", "metadata": metadata}],
            [{"start": ["disruption"]}],
            NODES,
        ),
        "start",
        "disruption",
    )
    mocker.patch("phenix_apps.apps.scorch.disruption.disruption.sleep")
    mocker.patch.object(ComponentBase, "mm_init", return_value=mm or mocker.MagicMock())
    mocker.patch.object(Disruption, "_kill_dos_processes")
    recv = mocker.patch.object(Disruption, "recv_file")
    run = mocker.patch.object(
        Disruption,
        "run_and_check_command",
        return_value={"exitcode": 0, "stdout": "done", "stderr": ""},
    )

    Disruption()

    assert recv.call_args_list[0].kwargs["src"] == [
        "/root/results.json",
        "/root/dos.py",
    ]
    return run


@pytest.mark.parametrize(
    ("now", "start"),
    [
        (datetime(2026, 10, 19, 12, 30, 15, 250000, UTC), "2026-10-19T12:30:16+00:00"),
        # The last second of an hour, a day and a year carry into the next.
        (datetime(2026, 10, 19, 13, 59, 59, 500000, UTC), "2026-10-19T14:00:00+00:00"),
        (datetime(2026, 10, 19, 23, 59, 59, 750000, UTC), "2026-10-20T00:00:00+00:00"),
        (datetime(2026, 12, 31, 23, 59, 59, 0, UTC), "2027-01-01T00:00:00+00:00"),
    ],
)
def test_start_time_rounds_up_to_the_next_second(component_args, mocker, now, start):
    metadata = {"current_disruption": "baseline", "run_duration": 30}
    files_dir = component_args(
        scorch_experiment(
            [{"name": "disruption", "type": "disruption", "metadata": metadata}],
            [{"start": ["disruption"]}],
            NODES,
        ),
        "start",
        "disruption",
    )
    mocker.patch(
        "phenix_apps.apps.scorch.disruption.disruption.utils.utc_now",
        return_value=now,
    )
    sleep = mocker.patch("phenix_apps.apps.scorch.disruption.disruption.sleep")
    mocker.patch.object(ComponentBase, "mm_init", return_value=mocker.MagicMock())

    Disruption()

    out = files_dir / "scorch/run-0/disruption/loop-0-count-0"
    assert (out / "disruption_start_time.txt").read_text() == start
    assert sleep.call_args_list[0].args == (1 - now.microsecond / 1e6,)
    assert sleep.call_args_list[1].args == (30.0,)


ATTACKER = {
    "type": "VirtualMachine",
    "general": {"hostname": "attacker"},
    "hardware": {"os_type": "linux"},
    "network": {
        "interfaces": [
            {"name": "eth0", "address": "10.0.0.66"},
            {"name": "eth1", "address": "10.1.0.66"},
        ]
    },
}
DOS = {
    "current_disruption": "dos",
    "run_duration": 300.0,
    "dos": {
        "start_delay": 0.0,
        "attack_duration": 20.0,
        "attacker": {
            "hostname": "attacker",
            "script_path": "/root/dos.py",
            "results_path": "/root/results.json",
        },
        "targets": [{"hostname": "load5"}],
    },
}


def _run_dos(component_args, mocker, stage):
    component_args(
        scorch_experiment(
            [{"name": "disruption", "type": "disruption", "metadata": DOS}],
            [
                {
                    "configure": ["disruption"],
                    "start": ["disruption"],
                    "cleanup": ["disruption"],
                }
            ],
            [ATTACKER, NODES[1]],
        ),
        stage,
        "disruption",
    )
    mocker.patch("phenix_apps.apps.scorch.disruption.disruption.sleep")
    mocker.patch.object(Disruption, "ensure_vm_running")

    Disruption()


@pytest.mark.parametrize(
    ("stage", "commands"),
    [
        (
            "configure",
            [
                ("pkill dos.py", "name=attacker"),
                ("pkill hping3", "name=attacker"),
                ("hping3 --version", "uuid=attacker-uuid"),
                ("/root/dos.py --help", "uuid=attacker-uuid"),
                ("ip link set eth1 down", "uuid=attacker-uuid"),
            ],
        ),
        (
            "cleanup",
            [
                ("pkill dos.py", "name=attacker"),
                ("pkill hping3", "name=attacker"),
                ("rm -f /root/results.json", "name=attacker"),
                ("ip link set eth1 up", "name=attacker"),
            ],
        ),
    ],
)
def test_dos_stage_clears_the_cc_filters_it_sets(
    component_args, cc_namespace, mocker, stage, commands
):
    _run_dos(component_args, mocker, stage)

    assert [(c, f) for _, c, f in cc_namespace.queued] == commands
    assert cc_namespace.filter is None


def test_failed_dos_start_still_clears_the_cc_filter(
    component_args, cc_namespace, mocker
):
    cc_namespace.result = {"exitcode": 1, "stdout": "", "stderr": "no hping3"}

    with pytest.raises(RuntimeError, match="no hping3"):
        _run_dos(component_args, mocker, "start")

    assert cc_namespace.filter is None
