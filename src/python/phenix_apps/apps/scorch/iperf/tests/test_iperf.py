"""The iperf component collects the files its iperf3 processes write, and leaves
no cc filter in the namespace."""

import json
import re
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.iperf.iperf import Iperf

MODULE = "phenix_apps.apps.scorch.iperf.iperf"


def _node(hostname, address):
    return {
        "type": "VirtualMachine",
        "general": {"hostname": hostname},
        "hardware": {"os_type": "linux"},
        "network": {"interfaces": [{"name": "eth0", "address": address}]},
    }


NODES = [_node("srv", "10.0.0.1"), _node("c1", "10.0.0.2"), _node("c2", "10.0.0.3")]
METADATA = {
    "run_duration": 10,
    "iperf_paths": {"linux": "/usr/bin/iperf3", "windows": "C:/iperf3/iperf3.exe"},
    "servers": [
        {
            "hostname": "srv",
            "port_range_start": 5201,
            "clients": [{"hostname": "c1"}, {"hostname": "c2"}],
        }
    ],
}
CLIENT_RESULT = {"intervals": [{"streams": [{"rtt": 1500}]}], "end": {}}


@pytest.fixture
def mm(mocker):
    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    mocker.patch(f"{MODULE}.sleep")
    mocker.patch(
        "phenix_apps.common.utils.mm_exec_wait",
        return_value={"exitcode": 0, "stdout": "", "stderr": ""},
    )
    mocker.patch(
        "phenix_apps.common.utils.mm_cc_client_locate",
        side_effect=lambda _mm, vm, **_: (vm, "host"),
    )
    return fake


def _run(component_args, stage, metadata=METADATA):
    component_args(
        scorch_experiment(
            [{"name": "ip", "type": "iperf", "metadata": metadata}],
            [{"configure": ["ip"], "start": ["ip"], "stop": ["ip"]}],
            NODES,
        ),
        stage,
        "ip",
    )
    Iperf()


def _started(mm):
    """The commands start backgrounded on each VM, by the cc filter they ran under."""
    commands = {}
    vm = None

    for name, args, _ in mm.method_calls:
        if name == "cc_filter":
            vm = args[0].removeprefix("name=")
        elif name == "cc_background_once":
            commands.setdefault(vm, []).append(args[0])

    return commands


def _written(commands):
    """The files each VM's commands write, by --logfile or redirection."""
    return {
        vm: {
            path
            for cmd in cmds
            for path in re.findall(r"(?:--logfile |>)(/[^\s']+)", cmd)
        }
        for vm, cmds in commands.items()
    }


def test_stop_collects_only_files_the_started_processes_write(
    component_args, mm, mocker
):
    _run(component_args, "start")
    written = _written(_started(mm))

    def recv(mm, vm, src, dst):
        assert src in written.get(vm, set()), f"nothing started on {vm} writes {src}"
        text = json.dumps(CLIENT_RESULT if "client-data" in src else {})
        Path(dst).write_text(text)

    collected = mocker.patch(f"{MODULE}.utils.mm_recv", side_effect=recv)

    _run(component_args, "stop")

    sources = {(c.kwargs["vm"], c.kwargs["src"]) for c in collected.call_args_list}
    for client in ("c1", "c2"):
        assert ("srv", f"/iperf_server-data_client-{client}_server-srv.json") in sources
        assert (
            client,
            f"/iperf_client-data_client-{client}_server-srv.json",
        ) in sources


def test_started_processes_send_stderr_to_their_log(component_args, mm):
    _run(component_args, "start")
    commands = [cmd for cmds in _started(mm).values() for cmd in cmds]

    # Two servers on srv, a client on each of c1 and c2.
    assert len(commands) == 4
    for cmd in commands:
        # Not 2>1, which writes stderr to a file named 1 in miniccc's directory.
        assert re.fullmatch(r"bash -c '.* >/iperf_\S+\.log 2>&1'", cmd), cmd


def test_start_runs_each_process_on_its_vm_then_clears_the_cc_filter(
    component_args, cc_namespace, mocker
):
    mocker.patch(f"{MODULE}.sleep")

    _run(component_args, "start")

    # Two servers on srv, then a client on each of c1 and c2, each started
    # once, so that a VM whose miniccc reconnects does not start it again.
    assert [(m, f) for m, _, f in cc_namespace.queued] == [
        ("cc_background_once", "name=srv"),
        ("cc_background_once", "name=srv"),
        ("cc_background_once", "name=c1"),
        ("cc_background_once", "name=c2"),
    ]
    assert cc_namespace.filter is None


def test_failed_start_still_clears_the_cc_filter(component_args, cc_namespace, mocker):
    mocker.patch(f"{MODULE}.sleep")
    cc_namespace.mm.cc_background_once.side_effect = RuntimeError("no client")

    with pytest.raises(RuntimeError, match="no client"):
        _run(component_args, "start")

    assert cc_namespace.filter is None


def test_configure_clears_the_cc_filter_of_its_cleanup(
    component_args, cc_namespace, mocker
):
    mocker.patch(f"{MODULE}.sleep")

    _run(component_args, "configure", {**METADATA, "verify_execution": False})

    assert [(c.split()[0], f) for _, c, f in cc_namespace.queued] == [
        ("pkill", "iperf=1 os=linux"),
        ("bash", "iperf=1 os=linux"),
    ]
    assert cc_namespace.filter is None


@pytest.mark.parametrize(
    ("fails", "error"), [("queue", "no client"), ("wait", "timed out")]
)
def test_run_multi_clears_the_cc_prefix_once_its_command_is_queued(
    mocker, fails, error
):
    """minimega tags every later cc command in the namespace with a prefix left set."""
    iperf = Iperf.__new__(Iperf)
    iperf.mm = mocker.MagicMock(name="mm")
    if fails == "queue":
        iperf.mm.cc_exec_once.side_effect = RuntimeError(error)

    def wait(*_args, **_kwargs):
        iperf.mm.waited()
        raise RuntimeError(error)

    mocker.patch(f"{MODULE}.utils.mm_wait_for_prefix", side_effect=wait)

    with pytest.raises(RuntimeError, match=error):
        iperf._run_multi("ss -tulp4", "iperf=1 os=linux", "ss_linux", 2)

    calls = [c[0] for c in iperf.mm.method_calls]
    assert calls[:2] == ["clear_cc_prefix", "cc_prefix"]
    assert calls[2:] == (
        ["cc_filter", "cc_exec_once", "clear_cc_filter", "clear_cc_prefix"]
        + ([] if fails == "queue" else ["waited"])
    )
