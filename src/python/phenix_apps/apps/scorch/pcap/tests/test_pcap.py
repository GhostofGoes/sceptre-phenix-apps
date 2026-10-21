"""The pcap component starts and stops only its own minimega captures."""

import json
import os

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.pcap.pcap import PCAP

NODES = [
    {
        "type": "VirtualMachine",
        "general": {"hostname": "vm-1"},
        "hardware": {"os_type": "linux"},
        "network": {
            "interfaces": [
                {"name": "eth0", "address": "10.0.0.1"},
                {"name": "eth1", "address": "10.0.1.1"},
            ]
        },
    }
]

TWO_INTERFACES = [
    {"hostname": "vm-1", "interface": 0},
    {"hostname": "vm-1", "interface": "eth1"},
]


class FakeCaptures:
    """Tracks VM captures the way minimega's StopVM does."""

    def __init__(self):
        self.active = set()

    def start(self, vm, iface, _path):
        self.active.add((vm, int(iface)))

    def delete(self, vm, interface=None):
        stopped = {
            c
            for c in self.active
            if c[0] == vm and (interface is None or c[1] == int(interface))
        }
        if not stopped:
            raise RuntimeError(f"vm not found: {vm}")
        self.active -= stopped


@pytest.fixture
def mm(mocker):
    mocker.patch("phenix_apps.apps.scorch.pcap.pcap.shutil.which", return_value="/x")
    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    return fake


def test_start_leaves_other_captures_alone(component_args, mm):
    component_args(
        scorch_experiment(
            [{"name": "pcap", "type": "pcap", "metadata": {"vms": TWO_INTERFACES}}],
            [{"start": ["pcap"]}],
            NODES,
        ),
        "start",
        "pcap",
    )

    PCAP()

    mm.clear_capture.assert_not_called()
    assert [c.args[:2] for c in mm.capture_pcap_vm.call_args_list] == [
        ("vm-1", 0),
        ("vm-1", 1),
    ]


def test_stop_two_interfaces_of_one_vm(component_args, mm, mocker):
    files_dir = component_args(
        scorch_experiment(
            [{"name": "pcap", "type": "pcap", "metadata": {"vms": TWO_INTERFACES}}],
            [{"stop": ["pcap"]}],
            NODES,
        ),
        "stop",
        "pcap",
    )
    captures = FakeCaptures()
    captures.start("vm-1", 0, None)
    captures.start("vm-1", 1, None)
    mm.capture_pcap_delete_vm.side_effect = captures.delete

    base = files_dir / "scorch/run-0/pcap/loop-0-count-0"
    base.mkdir(parents=True)
    for name in ("vm-1-0.pcap", "vm-1-1.pcap"):
        (base / name).write_bytes(b"")
    mocker.patch(
        "phenix_apps.apps.scorch.pcap.pcap.utils.pcap_capinfos",
        return_value={"File type": "Wireshark/tcpdump/... - pcap"},
    )

    PCAP()

    assert captures.active == set()
    mm.clear_capture.assert_not_called()


def _filter_calls(mm):
    """capture_pcap_filter and capture_pcap_vm calls, in order."""
    return [
        (c[0], c.args[0])
        for c in mm.mock_calls
        if c[0] in ("capture_pcap_filter", "capture_pcap_vm")
    ]


@pytest.mark.parametrize(
    ("configured", "applied"),
    [(None, "' '"), ("tcp port 80", "'tcp port 80'")],
    ids=["no-filter", "filter"],
)
def test_filter_is_set_for_its_captures_then_cleared(
    component_args, mm, configured, applied
):
    """minimega keeps the namespace filter for every later capture."""
    metadata = {"vms": [{"hostname": "vm-1"}]}
    if configured:
        metadata["filter"] = configured
    component_args(
        scorch_experiment(
            [{"name": "pcap", "type": "pcap", "metadata": metadata}],
            [{"start": ["pcap"]}],
            NODES,
        ),
        "start",
        "pcap",
    )

    PCAP()

    assert _filter_calls(mm) == [
        ("capture_pcap_filter", applied),
        ("capture_pcap_vm", "vm-1"),
        ("capture_pcap_filter", "' '"),
    ]


def test_a_filter_minimega_cannot_relay_is_refused_first(component_args, mm):
    """A non-breaking space in a quoted filter makes minimega exit."""
    metadata = {"vms": [{"hostname": "vm-1"}], "filter": "tcp\u00a0port 80"}
    component_args(
        scorch_experiment(
            [{"name": "pcap", "type": "pcap", "metadata": metadata}],
            [{"start": ["pcap"]}],
            NODES,
        ),
        "start",
        "pcap",
    )

    with pytest.raises(RuntimeError, match="pcap component 'pcap': filter holds"):
        PCAP()

    assert mm.mock_calls == []


def test_stop_stops_every_capture_before_reporting_a_failure(
    component_args, mm, mocker
):
    vms = [{"hostname": "vm-1", "interface": 0}, {"hostname": "vm-2", "interface": 0}]
    nodes = [NODES[0], {**NODES[0], "general": {"hostname": "vm-2"}}]
    component_args(
        scorch_experiment(
            [{"name": "pcap", "type": "pcap", "metadata": {"vms": vms}}],
            [{"stop": ["pcap"]}],
            nodes,
        ),
        "stop",
        "pcap",
    )
    captures = FakeCaptures()
    captures.start("vm-2", 0, None)
    mm.capture_pcap_delete_vm.side_effect = captures.delete
    capinfos = mocker.patch("phenix_apps.apps.scorch.pcap.pcap.utils.pcap_capinfos")

    with pytest.raises(RuntimeError, match="vm-1 interface 0: vm not found: vm-1"):
        PCAP()

    assert captures.active == set()
    capinfos.assert_not_called()


@pytest.mark.parametrize(
    ("configured", "applied"), [(None, 0), (96, 96)], ids=["no-snaplen", "snaplen"]
)
def test_snaplen_is_set_for_its_captures_then_reset(
    component_args, mm, configured, applied
):
    """minimega keeps the namespace snaplen for every later capture."""
    metadata = {"vms": [{"hostname": "vm-1"}]}
    if configured is not None:
        metadata["snaplen"] = configured
    component_args(
        scorch_experiment(
            [{"name": "pcap", "type": "pcap", "metadata": metadata}],
            [{"start": ["pcap"]}],
            NODES,
        ),
        "start",
        "pcap",
    )
    mm.capture_pcap_vm.side_effect = RuntimeError("vm not running")

    with pytest.raises(RuntimeError, match="vm not running"):
        PCAP()

    assert [
        (c[0], c.args[0])
        for c in mm.mock_calls
        if c[0] in ("capture_pcap_snaplen", "capture_pcap_vm")
    ] == [
        ("capture_pcap_snaplen", applied),
        ("capture_pcap_vm", "vm-1"),
        ("capture_pcap_snaplen", 0),
    ]


def test_a_failed_reset_neither_masks_the_error_nor_skips_the_other(component_args, mm):
    """A dropped minimega socket fails the filter reset too."""
    metadata = {"vms": [{"hostname": "vm-1"}], "snaplen": 96, "filter": "udp"}
    component_args(
        scorch_experiment(
            [{"name": "pcap", "type": "pcap", "metadata": metadata}],
            [{"start": ["pcap"]}],
            NODES,
        ),
        "start",
        "pcap",
    )
    mm.capture_pcap_vm.side_effect = RuntimeError("vm not running: vm-1")

    def capture_filter(arg):
        if arg == "' '":
            raise RuntimeError("socket closed")

    mm.capture_pcap_filter.side_effect = capture_filter

    with pytest.raises(RuntimeError, match="vm not running: vm-1"):
        PCAP()

    assert [c.args[0] for c in mm.capture_pcap_snaplen.call_args_list] == [96, 0]


# Stand-ins for the Wireshark tools stop runs: each writes the file its -w or
# last argument names, and capinfos reports a pcap.
FAKE_TOOLS = {
    "capinfos": 'printf "File name\\tFile type\\n%s\\tpcap\\n" "$3"\n',
    "mergecap": ': > "$2"\n',
    "editcap": 'for a; do out=$a; done; : > "$out"\n',
    "tshark": (
        'out=; prev=; for a; do [ "$prev" = -w ] && out=$a; prev=$a; done\n'
        'if [ -n "$out" ]; then : > "$out"; else echo "{}"; fi\n'
    ),
}


@pytest.fixture
def fake_tools(monkeypatch, tmp_path):
    """Put the Wireshark tools stop runs on PATH, and run in ``tmp_path``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in FAKE_TOOLS.items():
        tool = bin_dir / name
        tool.write_text(f"#!/bin/sh\n{body}")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_stop_runs_its_tools_without_a_shell(component_args, mm, fake_tools):
    """The capture paths hold the component's name, which the scenario sets."""
    name = "p$(touch${IFS}PWNED)"
    vms = [{"hostname": "vm-1"}, {"hostname": "vm-2"}]
    nodes = [NODES[0], {**NODES[0], "general": {"hostname": "vm-2"}}]
    metadata = {"vms": vms, "create_merged_pcap": True, "convertToJSON": True}
    # A dos target makes stop split its capture with tshark too.
    dos = {
        "name": "dis",
        "type": "disruption",
        "metadata": {
            "current_disruption": "dos",
            "dos": {"targets": [{"hostname": "vm-2"}]},
        },
    }
    files_dir = component_args(
        scorch_experiment(
            [{"name": name, "type": "pcap", "metadata": metadata}, dos],
            [{"stop": [name]}],
            nodes,
        ),
        "stop",
        name,
    )
    base = files_dir / f"scorch/run-0/{name}/loop-0-count-0"
    base.mkdir(parents=True)
    for vm in ("vm-1", "vm-2"):
        (base / f"{vm}-0.pcap").write_bytes(b"")

    PCAP()

    assert not (fake_tools / "PWNED").exists()
    assert (base / "merged.pcap").is_file()
    assert (base / "merged.jsonl").read_text() == "{}\n"
    assert json.loads((base / "pcap_metadata.json").read_text())["merged.pcap"] == {
        "File name": str(base / "merged.pcap"),
        "File type": "pcap",
    }


def test_a_disruption_component_without_a_type_counts_as_its_name(
    component_args, mm, fake_tools
):
    """phenix core defaults an omitted or empty type to the name."""
    vms = [{"hostname": "vm-1"}, {"hostname": "vm-2"}]
    nodes = [NODES[0], {**NODES[0], "general": {"hostname": "vm-2"}}]
    metadata = {"vms": vms, "create_merged_pcap": True}
    disruption = {
        "name": "disruption",
        "metadata": {
            "current_disruption": "dos",
            "dos": {"targets": [{"hostname": "vm-2"}]},
        },
    }
    files_dir = component_args(
        scorch_experiment(
            [{"name": "pcap", "type": "pcap", "metadata": metadata}, disruption],
            [{"stop": ["pcap"]}],
            nodes,
        ),
        "stop",
        "pcap",
    )
    base = files_dir / "scorch/run-0/pcap/loop-0-count-0"
    base.mkdir(parents=True)
    for vm in ("vm-1", "vm-2"):
        (base / f"{vm}-0.pcap").write_bytes(b"")

    PCAP()

    # Only a dos target's capture is split into its fragments and the rest.
    assert sorted(p.name for p in (base / "raw").glob("*_no_dos_fragments.pcap")) == [
        "vm-2-0_no_dos_fragments.pcap"
    ]
