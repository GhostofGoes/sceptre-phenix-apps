"""Capture settings the mm component hands minimega."""

import os

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.mm.mm import MM

SETTINGS = ("capture_pcap_filter", "capture_pcap_snaplen")


@pytest.fixture
def mm(mocker):
    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    return fake


def _calls(mm):
    """Capture settings and capture starts, in order."""
    keep = (*SETTINGS, "capture_pcap_bridge", "capture_pcap_vm")
    return [(c[0], c.args[0]) for c in mm.mock_calls if c[0] in keep]


def _run_start(component_args, metadata):
    component_args(
        scorch_experiment(
            [{"name": "mm", "type": "mm", "metadata": metadata}], [{"start": ["mm"]}]
        ),
        "start",
        "mm",
    )
    MM()


def test_bridge_capture_quotes_a_multi_word_filter(component_args, mm):
    capture = {"bridge": "phenix", "filter": "tcp port 80", "snaplen": 200}
    _run_start(
        component_args, {"start": [{"type": "start_capture", "capture": capture}]}
    )

    assert _calls(mm) == [
        ("capture_pcap_filter", "'tcp port 80'"),
        ("capture_pcap_snaplen", 200),
        ("capture_pcap_bridge", "phenix"),
        ("capture_pcap_filter", "' '"),
        ("capture_pcap_snaplen", 0),
    ]


def test_a_filter_minimega_cannot_relay_starts_no_capture(component_args, mm):
    """A non-breaking space in a quoted filter makes minimega exit."""
    capture = {"bridge": "phenix", "filter": "tcp\u00a0port 80"}

    with pytest.raises(RuntimeError, match="capture filter holds"):
        _run_start(
            component_args, {"start": [{"type": "start_capture", "capture": capture}]}
        )

    assert "'tcp\u00a0port 80'" not in [c[1] for c in _calls(mm)]
    mm.capture_pcap_bridge.assert_not_called()


def test_vm_capture_without_settings_clears_leftovers(component_args, mm):
    """minimega keeps the namespace filter and snaplen for every new capture."""
    _run_start(
        component_args,
        {
            "vms": [
                {
                    "hostname": "vm-1",
                    "start": [{"type": "start_capture", "capture": {"interface": 0}}],
                }
            ]
        },
    )

    assert _calls(mm) == [
        ("capture_pcap_filter", "' '"),
        ("capture_pcap_snaplen", 0),
        ("capture_pcap_vm", "vm-1"),
        ("capture_pcap_filter", "' '"),
        ("capture_pcap_snaplen", 0),
    ]


def test_stop_converts_a_capture_name_without_a_shell(
    component_args, mm, mocker, fake_tshark
):
    """Capture file names come from scenario metadata and must not reach a shell."""
    mocker.patch("phenix_apps.apps.scorch.mm.mm.time.sleep")
    mm.file_status.return_value = []

    files = component_args(
        scorch_experiment(
            [
                {
                    "name": "mm",
                    "type": "mm",
                    "metadata": {
                        "vms": [
                            {
                                "hostname": "vm-1",
                                "stop": [
                                    {
                                        "type": "stop_capture",
                                        "capture": {"convert": True},
                                    }
                                ],
                            }
                        ]
                    },
                }
            ],
            [{"stop": ["mm"]}],
        ),
        "stop",
        "mm",
    )
    base_dir = files / "scorch/run-0/mm/loop-0-count-0"
    base_dir.mkdir(parents=True)
    name = "a'$(touch${IFS}PWNED)'.pcap"
    (base_dir / name).write_bytes(b"")

    MM()

    assert not (fake_tshark / "PWNED").exists()
    assert (base_dir / f"{name}.jsonl").read_text().splitlines() == [
        "-r",
        str(base_dir / name),
        "-T",
        "ek",
    ]


@pytest.mark.parametrize("target", ["bridge", "vm"])
def test_a_rejected_snaplen_still_clears_the_filter(component_args, mm, target):
    """minimega rejects a negative snaplen after the filter is already set."""

    def snaplen(size):
        if size < 0:
            raise RuntimeError("strconv.ParseUint: invalid syntax")

    mm.capture_pcap_snaplen.side_effect = snaplen
    capture = {"filter": "tcp port 80", "snaplen": -1}
    if target == "bridge":
        metadata = {
            "start": [
                {"type": "start_capture", "capture": {"bridge": "phenix", **capture}}
            ]
        }
    else:
        metadata = {
            "vms": [
                {
                    "hostname": "vm-1",
                    "start": [
                        {
                            "type": "start_capture",
                            "capture": {"interface": 0, **capture},
                        }
                    ],
                }
            ]
        }

    with pytest.raises(RuntimeError, match="ParseUint"):
        _run_start(component_args, metadata)

    assert _calls(mm) == [
        ("capture_pcap_filter", "'tcp port 80'"),
        ("capture_pcap_snaplen", -1),
        ("capture_pcap_filter", "' '"),
        ("capture_pcap_snaplen", 0),
    ]


@pytest.mark.parametrize(
    ("capture", "interface"),
    [(None, None), ({"convert": False}, None), ({"interface": 1}, 1)],
    ids=["no-capture", "no-interface", "interface"],
)
def test_vm_stop_capture_stops_only_the_named_interface(
    component_args, mm, capture, interface
):
    """Without an interface minimega stops every capture on the VM."""
    stop = {"type": "stop_capture"}
    if capture is not None:
        stop["capture"] = capture
    component_args(
        scorch_experiment(
            [
                {
                    "name": "mm",
                    "type": "mm",
                    "metadata": {"vms": [{"hostname": "vm-1", "stop": [stop]}]},
                }
            ],
            [{"stop": ["mm"]}],
        ),
        "stop",
        "mm",
    )

    MM()

    mm.capture_pcap_delete_vm.assert_called_once_with("vm-1", interface)


def _stop_two_vms(component_args, mocker, convert=True):
    """Run a stop stage whose two VMs each stop their capture; return the run
    directory, with a capture file per VM already in it."""
    mocker.patch("phenix_apps.apps.scorch.mm.mm.time.sleep")
    stop = [{"type": "stop_capture", "capture": {"interface": 0, "convert": convert}}]
    files = component_args(
        scorch_experiment(
            [
                {
                    "name": "mm",
                    "type": "mm",
                    "metadata": {
                        "vms": [
                            {"hostname": "vm-1", "stop": stop},
                            {"hostname": "vm-2", "stop": stop},
                        ]
                    },
                }
            ],
            [{"stop": ["mm"]}],
        ),
        "stop",
        "mm",
    )
    base_dir = files / "scorch/run-0/mm/loop-0-count-0"
    base_dir.mkdir(parents=True)
    for vm in ("vm-1", "vm-2", "vm-3"):
        (base_dir / f"{vm}.pcap").write_bytes(b"")
    return base_dir


def _tshark(tmp_path, monkeypatch, script):
    bin_dir = tmp_path / "tshark-bin"
    bin_dir.mkdir()
    tshark = bin_dir / "tshark"
    tshark.write_text(f"#!/bin/sh\n{script}\n")
    tshark.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


def test_stop_converts_no_capture_minimega_still_writes(
    component_args, mm, mocker, fake_tshark
):
    """vm-3's capture, which the stage does not stop, is still growing."""
    mm.file_status.return_value = []
    base_dir = _stop_two_vms(component_args, mocker)
    mm.capture.return_value = [
        {"Header": ["bridge", "type", "path"], "Tabular": []},
        {
            "Header": ["bridge", "type", "path"],
            "Tabular": [["phenix", "pcap", f"{base_dir}/vm-3.pcap"]],
        },
    ]

    MM()

    assert [c.args[0] for c in mm.capture_pcap_delete_vm.call_args_list] == [
        "vm-1",
        "vm-2",
    ]
    assert sorted(p.name for p in base_dir.glob("*.jsonl")) == [
        "vm-1.pcap.jsonl",
        "vm-2.pcap.jsonl",
    ]


def test_stop_converts_a_capture_again_once_it_grew(
    component_args, mm, mocker, fake_tshark
):
    """A .jsonl older than its capture was converted while it still grew."""
    mm.file_status.return_value = []
    base_dir = _stop_two_vms(component_args, mocker)
    stale = base_dir / "vm-1.pcap.jsonl"
    stale.write_text("partial\n")
    os.utime(stale, (1, 1))
    fresh = base_dir / "vm-2.pcap.jsonl"
    fresh.write_text("done\n")

    MM()

    assert stale.read_text().splitlines()[0] == "-r"
    assert fresh.read_text() == "done\n"


def test_a_failed_conversion_fails_the_stage_after_every_stop(
    component_args, mm, mocker, tmp_path, monkeypatch
):
    mm.file_status.return_value = []
    base_dir = _stop_two_vms(component_args, mocker)
    _tshark(tmp_path, monkeypatch, "echo partial; exit 2")

    with pytest.raises(RuntimeError, match=r"tshark exited 2 converting vm-1\.pcap"):
        MM()

    assert mm.capture_pcap_delete_vm.call_count == 2
    assert list(base_dir.glob("*.jsonl")) == []


def test_a_missing_tshark_fails_the_stage_after_every_stop(
    component_args, mm, mocker, tmp_path, monkeypatch
):
    mm.file_status.return_value = []
    base_dir = _stop_two_vms(component_args, mocker)
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))

    with pytest.raises(RuntimeError) as err:
        MM()

    for vm in ("vm-1", "vm-2", "vm-3"):
        assert f"cannot convert {vm}.pcap to JSON: " in str(err.value)

    assert mm.capture_pcap_delete_vm.call_count == 2
    assert list(base_dir.glob("*.jsonl")) == []


def test_a_failed_filter_reset_still_resets_the_snaplen(component_args, mm):
    """A dropped minimega socket fails the filter reset too."""

    def capture_filter(arg):
        if arg == "' '":
            raise RuntimeError("socket closed")

    mm.capture_pcap_filter.side_effect = capture_filter
    mm.capture_pcap_bridge.side_effect = RuntimeError("no such bridge")
    capture = {"bridge": "phenix", "snaplen": 96, "filter": "udp"}

    with pytest.raises(RuntimeError, match="no such bridge"):
        _run_start(
            component_args, {"start": [{"type": "start_capture", "capture": capture}]}
        )

    assert [c.args[0] for c in mm.capture_pcap_snaplen.call_args_list] == [96, 0]
