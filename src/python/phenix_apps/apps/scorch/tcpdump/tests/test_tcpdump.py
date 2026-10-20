"""tcpdump leaves no cc filter in the namespace."""

import re
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.tcpdump.tcpdump import TCPDump
from phenix_apps.common import settings, utils

MODULE = "phenix_apps.apps.scorch.tcpdump.tcpdump"
VMS = [{"hostname": "vm-1", "iface": "eth0"}, {"hostname": "vm-2", "iface": "eth1"}]


@pytest.fixture
def mm(mocker):
    """The namespace's minimega, with mm_exec_wait aiming its filter as it does."""
    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)

    def exec_wait(mm, vm, cmd, **_kwargs):
        mm.cc_filter(f"uuid={vm}-uuid")
        return {"exitcode": 0, "stdout": "/usr/bin/tcpdump", "stderr": ""}

    mocker.patch(f"{MODULE}.utils.mm_exec_wait", side_effect=exec_wait)
    mocker.patch(f"{MODULE}.utils.mm_recv")
    return fake


def _run(component_args, stage, vms=VMS):
    component_args(
        scorch_experiment(
            [{"name": "tcp", "type": "tcpdump", "metadata": {"vms": vms}}],
            [{"start": ["tcp"], "stop": ["tcp"]}],
        ),
        stage,
        "tcp",
    )
    TCPDump()


@pytest.mark.parametrize("stage", ["start", "stop"])
def test_stage_clears_the_cc_filters_it_sets(component_args, mm, mocker, stage):
    _run(component_args, stage)

    assert mm.cc_filter.call_count >= len(VMS)
    assert mm.method_calls[-1] == mocker.call.clear_cc_filter()


def test_stop_removes_each_capture_under_its_vm_filter(component_args, mm, mocker):
    _run(component_args, "stop")

    filter_or_rm = [
        c
        for c in mm.method_calls
        if c[0] in ("cc_filter", "cc_exec_once", "clear_cc_filter")
    ]
    assert filter_or_rm == [
        mocker.call.cc_filter("uuid=vm-1-uuid"),
        mocker.call.cc_exec_once("rm /dump-eth0.pcap"),
        mocker.call.cc_filter("uuid=vm-2-uuid"),
        mocker.call.cc_exec_once("rm /dump-eth1.pcap"),
        mocker.call.clear_cc_filter(),
    ]


def test_failed_start_still_clears_the_cc_filter(component_args, mm, mocker):
    mocker.patch(
        f"{MODULE}.utils.mm_exec_wait",
        return_value={"exitcode": 1, "stdout": "", "stderr": ""},
    )

    with pytest.raises(RuntimeError, match="tcpdump is not installed in VM vm-1"):
        _run(component_args, "start")

    assert mm.method_calls[-1] == mocker.call.clear_cc_filter()


def test_stop_converts_without_a_shell(component_args, mm, fake_tshark):
    """The interface name comes from scenario metadata and must not reach a shell."""
    iface = "e'$(touch${IFS}PWNED)'"
    files = component_args(
        scorch_experiment(
            [
                {
                    "name": "tcp",
                    "type": "tcpdump",
                    "metadata": {
                        "convertToJSON": True,
                        "vms": [{"hostname": "vm-1", "iface": iface}],
                    },
                }
            ],
            [{"stop": ["tcp"]}],
        ),
        "stop",
        "tcp",
    )

    TCPDump()

    pcap = files / f"scorch/run-0/tcp/loop-0-count-0/vm-1-{iface}.pcap"
    assert not (fake_tshark / "PWNED").exists()
    assert Path(f"{pcap}.jsonl").read_text().splitlines() == [
        "-r",
        str(pcap),
        "-T",
        "ek",
    ]


def _stop_converting(component_args):
    files = component_args(
        scorch_experiment(
            [
                {
                    "name": "tcp",
                    "type": "tcpdump",
                    "metadata": {"convertToJSON": True, "vms": VMS},
                }
            ],
            [{"stop": ["tcp"]}],
        ),
        "stop",
        "tcp",
    )
    return files / "scorch/run-0/tcp/loop-0-count-0"


@pytest.mark.parametrize(
    ("tshark", "error"),
    [("echo partial; exit 2", "tshark exited 2 converting"), (None, "cannot convert")],
    ids=["tshark-fails", "no-tshark"],
)
def test_a_failed_conversion_fails_the_stage_after_every_stop(
    component_args, mm, tmp_path, monkeypatch, tshark, error
):
    bin_dir = tmp_path / "tshark-bin"
    bin_dir.mkdir()
    if tshark:
        (bin_dir / "tshark").write_text(f"#!/bin/sh\n{tshark}\n")
        (bin_dir / "tshark").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    base_dir = _stop_converting(component_args)

    with pytest.raises(RuntimeError) as err:
        TCPDump()

    for capture in ("vm-1-eth0.pcap", "vm-2-eth1.pcap"):
        assert re.search(f"{error} [^;]*{re.escape(capture)}", str(err.value))

    assert [c.args[0] for c in mm.cc_exec_once.call_args_list] == [
        "rm /dump-eth0.pcap",
        "rm /dump-eth1.pcap",
    ]
    assert list(base_dir.glob("*.jsonl")) == []


def test_stop_reaches_every_vm_when_one_has_no_client(component_args, mm, mocker):
    def exec_wait(mm, vm, cmd, **_kwargs):
        if vm == "vm-1":
            raise RuntimeError("no cc client for vm-1")
        mm.cc_filter(f"uuid={vm}-uuid")
        return {"exitcode": 0, "stdout": "", "stderr": ""}

    mocker.patch(f"{MODULE}.utils.mm_exec_wait", side_effect=exec_wait)

    with pytest.raises(RuntimeError, match="tcpdump stop failed: vm-1: no cc client"):
        _run(component_args, "stop")

    assert [c.args[0] for c in mm.cc_exec_once.call_args_list] == ["rm /dump-eth1.pcap"]
    assert mm.method_calls[-1] == mocker.call.clear_cc_filter()


def test_stop_waits_only_the_teardown_grace_for_each_client(component_args, mm):
    """phenix gives a canceled run's stop and cleanup stages 4 minutes in all,
    less than the client grace a start waits."""
    _run(component_args, "stop")

    graces = [c.kwargs.get("client_grace") for c in utils.mm_exec_wait.call_args_list]
    graces += [c.kwargs.get("grace") for c in utils.mm_recv.call_args_list]
    assert graces == [settings.CC_TEARDOWN_GRACE] * 4
