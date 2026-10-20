"""vmstats removes the vmstat tag it puts on the VMs."""

import os
import signal
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.vmstats.vmstats import VMStats

MODULE = "phenix_apps.apps.scorch.vmstats.vmstats"
VMSTAT_OUT = """\
procs -----memory---- -----timestamp-----
 r  b   free  us sy id                 UTC
 1  0 123456   1  1 98 2026-10-19 12:00:00
"""
NODES = [
    {
        "type": "VirtualMachine",
        "general": {"hostname": vm},
        "hardware": {"os_type": "linux"},
        "network": {"interfaces": []},
    }
    for vm in ("vm-1", "vm-2")
]


@pytest.fixture
def mm(mocker):
    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    mocker.patch(f"{MODULE}.time.sleep")
    mocker.patch(
        f"{MODULE}.utils.mm_cc_client_locate",
        side_effect=lambda _mm, vm, **_: (f"{vm}-uuid", "host"),
    )
    mocker.patch(
        f"{MODULE}.utils.mm_recv",
        side_effect=lambda mm, vm, src, dst: Path(dst).write_text(VMSTAT_OUT),
    )
    return fake


def _run(component_args, stage):
    files_dir = component_args(
        scorch_experiment(
            [{"name": "vm", "type": "vmstats", "metadata": {"pollPeriod": 1}}],
            [{"start": ["vm"], "stop": ["vm"]}],
            NODES,
        ),
        stage,
        "vm",
    )
    VMStats()
    return files_dir / "scorch/run-0/vm/loop-0-count-0"


def test_start_tags_the_vms(component_args, mm, mocker):
    _run(component_args, "start")

    assert mm.vm_tag.call_args_list == [
        mocker.call("vm-1", "vmstat", "1"),
        mocker.call("vm-2", "vmstat", "1"),
    ]


def test_start_queues_vmstat_once_in_each_vm(component_args, mm, mocker):
    """minimega resends a command that is not once to a client that reconnects,
    which would append a second vmstat stream to /vmstat.out."""
    _run(component_args, "start")

    vmstat = "bash -c 'vmstat -n -t 1 >> /vmstat.out'"
    mm.cc_background.assert_not_called()
    assert [c for c in mm.method_calls if "filter" in c[0] or "background" in c[0]] == [
        mocker.call.cc_filter("name=vm-1 os=linux"),
        mocker.call.cc_background_once(vmstat),
        mocker.call.clear_cc_filter(),
        mocker.call.cc_filter("name=vm-2 os=linux"),
        mocker.call.cc_background_once(vmstat),
        mocker.call.clear_cc_filter(),
    ]


def test_stop_deletes_by_name_then_removes_the_tag(component_args, mm, mocker):
    """minimega matches a filter when it routes a queued command, so a command
    aimed at the tag could miss VMs whose tag is already gone."""
    out = _run(component_args, "stop")

    queued = []
    filter_ = None
    for name, args, _ in mm.method_calls:
        if name == "cc_filter":
            filter_ = args[0]
        elif name == "clear_cc_filter":
            filter_ = None
        elif name == "cc_exec_once":
            queued.append((args[0], filter_))
    assert queued == [
        ("pkill vmstat", "vmstat=1 os=linux"),
        ("rm -f /vmstat.out", "name=vm-1"),
        ("rm -f /vmstat.out", "name=vm-2"),
    ]

    assert mm.clear_vm_tag.call_args_list == [
        mocker.call("vm-1", "vmstat"),
        mocker.call("vm-2", "vmstat"),
    ]
    calls = [c[0] for c in mm.method_calls]
    assert calls.index("clear_vm_tag") > max(
        i for i, c in enumerate(calls) if c == "cc_exec_once"
    )
    assert len((out / "vm_stats.jsonl").read_text().splitlines()) == 2


def test_a_failed_copy_still_removes_the_tag(component_args, mm, mocker):
    mocker.patch(f"{MODULE}.utils.mm_recv", side_effect=ValueError("no mount"))

    with pytest.raises(RuntimeError, match=r"Failed to get vmstat\.out from vm-1"):
        _run(component_args, "stop")

    assert mm.clear_vm_tag.call_args_list == [
        mocker.call("vm-1", "vmstat"),
        mocker.call("vm-2", "vmstat"),
    ]


def test_a_failed_tag_removal_removes_the_other_tags(component_args, mm, mocker):
    """minimega fails clear vm tag for a VM it no longer knows."""
    mm.clear_vm_tag.side_effect = [RuntimeError("vm not found: vm-1"), None]

    with pytest.raises(RuntimeError, match="vm not found: vm-1"):
        _run(component_args, "stop")

    assert mm.clear_vm_tag.call_args_list == [
        mocker.call("vm-1", "vmstat"),
        mocker.call("vm-2", "vmstat"),
    ]


@pytest.mark.parametrize("failure", ["sigterm", "minimega error"])
def test_a_failed_pkill_clears_the_cc_filter(
    component_args, cc_namespace, mocker, failure
):
    """A filter left set aims every later cc command in the namespace at the
    tag, which no VM has once stop removes it."""
    mocker.patch(f"{MODULE}.time.sleep")

    def pkill(cmd):
        cc_namespace.queued.append(("cc_exec_once", cmd, cc_namespace.filter))
        if failure == "sigterm":
            # phenix cancels the stage while minimega queues the command.
            os.kill(os.getpid(), signal.SIGTERM)
        raise RuntimeError("minimega: cc exec failed")

    cc_namespace.mm.cc_exec_once.side_effect = pkill

    with pytest.raises(RuntimeError, match="Error occurred during stage execution"):
        _run(component_args, "stop")

    assert cc_namespace.queued == [
        ("cc_exec_once", "pkill vmstat", "vmstat=1 os=linux")
    ]
    assert cc_namespace.filter is None
    assert cc_namespace.mm.clear_vm_tag.call_args_list == [
        mocker.call("vm-1", "vmstat"),
        mocker.call("vm-2", "vmstat"),
    ]
