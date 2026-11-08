from unittest import mock

import pytest
from box import Box

from phenix_apps.apps.scorch.cc import cc
from phenix_apps.apps.scorch.cc.cc import CC, _one_line


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("whoami", "whoami"),
        ("rm -f /tmp/a\nrm -f /tmp/b\n", "rm -f /tmp/a\\nrm -f /tmp/b\\n"),
        ("dir C:\\temp\r\n", "dir C:\\temp\\r\\n"),
        (42, "42"),
    ],
)
def test_one_line_escapes_line_breaks(text, want):
    assert _one_line(text) == want


def test_stage_exec_logs_the_command_on_one_line(monkeypatch):
    component = object.__new__(CC)
    component.metadata = Box(
        {"start": [{"type": "exec", "args": "rm -f /tmp/a\nrm -f /tmp/b\n"}]}
    )
    component.mm = mock.Mock()
    component.extract_node_names = mock.Mock(return_value=[])
    info = mock.Mock()
    monkeypatch.setattr(cc.logger, "info", info)

    component.start()

    component.mm.cc_exec_once.assert_called_once_with("rm -f /tmp/a\nrm -f /tmp/b\n")
    info.assert_called_once_with(
        "command 'rm -f /tmp/a\\nrm -f /tmp/b\\n' executed with filter 'None' using cc"
    )


def _cc(metadata: dict) -> CC:
    component = object.__new__(CC)
    component.metadata = Box(metadata)
    component.mm = mock.Mock()
    component.extract_node_names = mock.Mock(return_value=["vm1"])  # type: ignore[method-assign]
    component.extract_node_os_type = mock.Mock(return_value="linux")  # type: ignore[method-assign]
    return component


def test_stage_exec_clears_the_filter_it_sets():
    component = _cc(
        {"start": [{"type": "exec", "filter": "hostname=h1", "args": "true"}]}
    )

    component.start()

    assert component.mm.method_calls == [
        mock.call.cc_filter("hostname=h1"),
        mock.call.cc_exec_once("true"),
        mock.call.clear_cc_filter(),
    ]


@pytest.mark.parametrize(
    ("step", "method"), [("exec", "cc_exec_once"), ("background", "cc_background_once")]
)
def test_vm_steps_clear_the_filter_even_when_queuing_fails(monkeypatch, step, method):
    component = _cc(
        {"vms": [{"hostname": "vm1", "start": [{"type": step, "args": "x"}]}]}
    )
    monkeypatch.setattr(CC, "_CC__send_cmd_as_file", lambda *_: "bash /tmp/x.sh")
    monkeypatch.setattr(
        cc.utils,
        "mm_cc_filter_vm",
        lambda mm, vm: mm.cc_filter(f"uuid=of-{vm}"),
    )
    getattr(component.mm, method).side_effect = RuntimeError("minimega refused")

    with pytest.raises(RuntimeError, match="refused"):
        component.start()

    assert component.mm.method_calls == [
        mock.call.cc_filter("uuid=of-vm1"),
        getattr(mock.call, method)("bash /tmp/x.sh"),
        mock.call.clear_cc_filter(),
    ]
