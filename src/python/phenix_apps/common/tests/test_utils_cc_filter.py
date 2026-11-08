import pytest

from phenix_apps.common import utils


class _RecordingMM:
    """Records cc_filter, cc_exec_once, cc_send and clear_cc_filter calls in order."""

    def __init__(self):
        self.calls = []

    def cc_filter(self, value):
        self.calls.append(("filter", value))

    def cc_exec_once(self, cmd):
        self.calls.append(("exec", cmd))

    def clear_cc_filter(self):
        self.calls.append(("clear",))

    def cc_send(self, src):
        self.calls.append(("send", src))
        return [{"Host": "h", "Data": 7}]

    def cc_responses(self, _cmd_id):
        return []


def test_mm_cc_filter_clears_the_filter_on_exit_and_on_error():
    mm = _RecordingMM()
    with utils.mm_cc_filter(mm, "uuid=abc"):
        mm.cc_exec_once("true")
    with pytest.raises(RuntimeError), utils.mm_cc_filter(mm, "uuid=def"):
        raise RuntimeError("boom")

    assert mm.calls == [
        ("filter", "uuid=abc"),
        ("exec", "true"),
        ("clear",),
        ("filter", "uuid=def"),
        ("clear",),
    ]


def test_kill_and_delete_helpers_leave_no_filter_behind():
    mm = _RecordingMM()
    utils.mm_kill_process(mm, "uuid=abc", "iperf3")
    utils.mm_delete_file(mm, "uuid=abc", "/tmp/out.json")
    with pytest.raises(ValueError, match="unknown os_type"):
        utils.mm_kill_process(mm, "uuid=abc", "iperf3", os_type="beos")

    assert mm.calls == [
        ("filter", "uuid=abc"),
        ("exec", "pkill iperf3"),
        ("clear",),
        ("filter", "uuid=abc"),
        ("exec", "rm -f /tmp/out.json"),
        ("clear",),
        ("filter", "uuid=abc"),
        ("clear",),
    ]


@pytest.fixture
def located(monkeypatch):
    """The VM's client is registered, and its commands finish at once."""
    monkeypatch.setattr(
        utils, "mm_cc_client_locate", lambda mm, vm, **_: (f"uuid-{vm}", "h")
    )
    monkeypatch.setattr(utils, "mm_wait_for_cmd", lambda *_, **__: None)
    monkeypatch.setattr(
        utils, "mm_cc_exitcode_wait", lambda *_, **__: {"Response": "0"}
    )
    monkeypatch.setattr(utils, "mm_cc_all_hosts", lambda *_, **__: [])


def test_mm_exec_wait_clears_the_filter_it_sets(located):
    mm = _RecordingMM()
    mm.cc_exec_once = lambda cmd: (
        mm.calls.append(("exec", cmd)) or [{"Host": "h", "Data": 3}]
    )

    assert utils.mm_exec_wait(mm, "vm1", "true")["exitcode"] == 0
    assert mm.calls == [("filter", "uuid=uuid-vm1"), ("exec", "true"), ("clear",)]


def test_mm_exec_wait_clears_the_filter_when_queuing_fails(located):
    mm = _RecordingMM()

    def refuse(cmd):
        raise RuntimeError("minimega refused")

    mm.cc_exec_once = refuse

    with pytest.raises(RuntimeError, match="refused"):
        utils.mm_exec_wait(mm, "vm1", "true")

    assert mm.calls == [("filter", "uuid=uuid-vm1"), ("clear",)]


def test_mm_cc_send_wait_clears_the_filter_it_sets(located):
    mm = _RecordingMM()

    utils.mm_cc_send_wait(mm, "vm1", "/phenix/exp/run.sh", "exp")

    assert mm.calls == [
        ("filter", "uuid=uuid-vm1"),
        ("send", "/phenix/exp/run.sh"),
        ("clear",),
    ]
