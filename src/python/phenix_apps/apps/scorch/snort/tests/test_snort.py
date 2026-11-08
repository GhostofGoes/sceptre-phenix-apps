from unittest.mock import MagicMock

import pytest
from box import Box
from pydantic import ValidationError

from phenix_apps.apps.scorch.snort.snort import Snort


def component(mocker, iface="eth1", running=True, link_ok=True) -> Snort:
    sn = Snort.__new__(Snort)
    sn.name = "snort"
    sn.metadata = Box({"hostname": "ids", "sniffInterface": iface, "startupWait": 0})
    sn.mm = mm = MagicMock()
    mocker.patch.object(sn, "mm_init", return_value=mm)

    def run(vm, cmd, **_):
        if cmd.startswith("ip link show") and not link_ok:
            raise RuntimeError(
                f"failed to run '{cmd}'\nstderr: Device \"{iface}\" does not exist."
            )
        return {
            "stdout": "ERROR: cannot parse snort.conf\n"
            if cmd.startswith("cat")
            else ""
        }

    mocker.patch.object(sn, "run_and_check_command", side_effect=run)
    mocker.patch.object(sn, "check_process_running", return_value=running)
    return sn


def test_start_runs_snort_with_stderr_captured(mocker):
    sn = component(mocker)
    sn.start()

    (cmd,), _ = sn.mm.cc_background.call_args
    assert cmd == (
        "bash -c 'snort -i eth1 -c /etc/snort/snort.conf 2> /var/log/snort/snort.err'"
    )
    sn.check_process_running.assert_called_once_with("ids", "snort")


def test_start_fails_on_missing_interface(mocker):
    sn = component(mocker, link_ok=False)

    with pytest.raises(RuntimeError, match="sniffInterface eth1 not found on ids"):
        sn.start()

    sn.mm.cc_background.assert_not_called()


def test_start_fails_with_stderr_when_snort_dies(mocker):
    sn = component(mocker, running=False)

    with pytest.raises(RuntimeError, match=r"cannot parse snort\.conf"):
        sn.start()


@pytest.mark.parametrize("iface", ["any'; reboot; '", "eth0 eth1", ""])
def test_start_rejects_unsafe_interface(mocker, iface):
    sn = component(mocker, iface=iface)

    with pytest.raises(ValidationError):
        sn.start()

    sn.mm.cc_background.assert_not_called()


def test_start_clears_the_filter_it_sets(mocker):
    sn = component(mocker)
    sn.start()

    calls = [c[0] for c in sn.mm.method_calls]
    assert calls[0] == "cc_filter"
    assert calls[-1] == "clear_cc_filter"
    assert calls.count("cc_filter") == calls.count("clear_cc_filter") == 1


def stopping(mocker, listing: str, exitcode: int = 0) -> Snort:
    sn = Snort.__new__(Snort)
    sn.name = "snort"
    sn.metadata = Box({"hostname": "ids", "waitDuration": 0})
    sn.mm = mm = MagicMock()
    mocker.patch.object(sn, "mm_init", return_value=mm)
    sn.base_dir = mocker.MagicMock()
    mocker.patch(
        "phenix_apps.apps.scorch.snort.snort.utils.mm_exec_wait",
        return_value={"exitcode": exitcode, "stdout": "", "stderr": ""},
    )
    mocker.patch.object(
        sn, "run_and_check_command", return_value={"stdout": listing, "exitcode": 0}
    )
    return sn


def test_stop_waits_for_snort_then_copies_every_packet_log(mocker):
    sn = stopping(mocker, "alert\nsnort.log.1700000002\nsnort.log.1700000001\n")
    recv = mocker.patch("phenix_apps.apps.scorch.snort.snort.utils.mm_recv")

    sn.stop()

    assert sn.mm.method_calls[:3] == [
        mocker.call.cc_filter("name=ids"),
        mocker.call.cc_exec("pkill -INT snort"),
        mocker.call.clear_cc_filter(),
    ]
    assert [c.args[2] for c in recv.call_args_list] == [
        "/var/log/snort/alert",
        "/var/log/snort/snort.log.1700000001",
        "/var/log/snort/snort.log.1700000002",
        "/var/log/snort/snort.stats",
    ]


def test_stop_fails_without_a_packet_log(mocker):
    sn = stopping(mocker, "alert\nsnort.err\n")
    mocker.patch("phenix_apps.apps.scorch.snort.snort.utils.mm_recv")

    with pytest.raises(RuntimeError, match=r"needs 'output log_tcpdump: snort\.log'"):
        sn.stop()
