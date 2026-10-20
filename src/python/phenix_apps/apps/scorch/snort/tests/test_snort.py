"""snort collects the packet logs snort names snort.log.<time>, and leaves no cc
filter in the namespace."""

import json
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.snort.snort import Snort
from phenix_apps.common import utils

MODULE = "phenix_apps.apps.scorch.snort.snort"
STATS = """\
# Snort perfmonitor statistics
#time,pkt_drop_percent,wire_mbits_per_sec.realtime
1760000005,0.000,0.012
1760000010,0.000,0.020
"""


@pytest.fixture
def mm(mocker):
    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    mocker.patch(f"{MODULE}.time.sleep")
    mocker.patch.object(
        utils, "mm_cc_client_locate", side_effect=lambda _mm, vm, **_: (vm, "host")
    )
    return fake


@pytest.fixture
def ls(mocker, mm):
    """The result of the `ls` of /var/log/snort, run as mm_exec_wait runs it."""
    result = {"exitcode": 0, "stdout": "", "stderr": ""}

    def exec_wait(mm, vm, cmd):
        mm.cc_filter(f"uuid={vm}-uuid")
        return dict(result)

    mocker.patch(f"{MODULE}.utils.mm_exec_wait", side_effect=exec_wait)
    return result


@pytest.fixture
def recv(mocker):
    def write(mm, vm, src, dst):
        Path(dst).write_text(STATS if src.endswith("snort.stats") else "x")

    return mocker.patch(f"{MODULE}.utils.mm_recv", side_effect=write)


def _run(component_args, stage, metadata=None):
    metadata = metadata or {"hostname": "ids"}
    files_dir = component_args(
        scorch_experiment(
            [{"name": "sn", "type": "snort", "metadata": metadata}],
            [{"start": ["sn"], "stop": ["sn"], "cleanup": ["sn"]}],
        ),
        stage,
        "sn",
    )
    Snort()
    return files_dir / "scorch/run-0/sn/loop-0-count-0"


def test_stop_collects_every_timestamped_packet_log(
    component_args, mm, ls, recv, mocker
):
    ls["stdout"] = "alert\nsnort.log.1760000000\nsnort.log.1760000100\nsnort.stats"

    out = _run(component_args, "stop")

    assert [c.args[1:3] for c in recv.call_args_list] == [
        ("ids", "/var/log/snort/alert"),
        ("ids", "/var/log/snort/snort.log.1760000000"),
        ("ids", "/var/log/snort/snort.log.1760000100"),
        ("ids", "/var/log/snort/snort.stats"),
    ]
    assert (out / "snort.log.1760000100").is_file()
    rows = [json.loads(line) for line in (out / "snort-stats.jsonl").open()]
    assert [r["time"] for r in rows] == ["1760000005", "1760000010"]
    assert mm.method_calls[-1] == mocker.call.clear_cc_filter()


def test_stop_without_a_packet_log_names_the_vm(component_args, mm, ls, recv):
    ls["stdout"] = "alert\nsnort.stats"

    with pytest.raises(RuntimeError, match=r"no snort\.log\.<time> .* in VM ids"):
        _run(component_args, "stop")

    recv.assert_not_called()


def test_cleanup_deletes_the_timestamped_packet_logs(component_args, mm):
    _run(component_args, "cleanup")

    assert mm.cc_exec_once.call_args_list[0].args == (
        "bash -c 'rm -f /var/log/snort/snort.log.*'",
    )


CONFIGURED = {
    "hostname": "ids",
    "sniffInterface": "eth1",
    "scripts": {
        "configSnort": {"script": "/scripts/configure-snort.sh", "executor": "bash"}
    },
    "configs": [{"src": "/configs/snort.conf", "dst": "/etc/snort/snort.conf"}],
}


@pytest.mark.parametrize(
    ("stage", "commands"),
    [
        (
            "configure",
            [
                ("cc_exec_once", "bash /configure-snort.sh"),
                ("cc_exec_once", "ip link set eth1 up"),
            ],
        ),
        (
            "start",
            [
                ("cc_exec_once", "rm -rf /var/log/snort"),
                ("cc_exec_once", "mkdir -p /var/log/snort"),
                ("cc_background_once", "snort -i eth1 -c /etc/snort/snort.conf"),
            ],
        ),
        (
            "cleanup",
            [
                ("cc_exec_once", f"bash -c 'rm -f /var/log/snort/{log}'")
                for log in ("snort.log.*", "snort.err", "snort.stats")
            ],
        ),
    ],
)
def test_stage_runs_on_its_host_then_clears_the_cc_filter(
    component_args, cc_namespace, stage, commands
):
    _run(component_args, stage, CONFIGURED)

    assert cc_namespace.queued == [(m, c, "name=ids") for m, c in commands]
    assert cc_namespace.filter is None


def test_failed_start_still_clears_the_cc_filter(component_args, cc_namespace):
    cc_namespace.mm.cc_background_once.side_effect = RuntimeError("no client")

    with pytest.raises(RuntimeError, match="no client"):
        _run(component_args, "start", CONFIGURED)

    assert cc_namespace.filter is None


def test_stop_copies_the_logs_once_snort_has_exited(component_args, mm, recv, mocker):
    """pkill returns once the signal is sent, before Snort flushes its logs."""
    events = []

    def exec_wait(mm, vm, cmd):
        events.append(cmd.split()[0])
        stdout = (
            "alert\nsnort.log.1760000000\nsnort.stats" if cmd.startswith("ls") else ""
        )
        return {"exitcode": 0, "stdout": stdout, "stderr": ""}

    mocker.patch(f"{MODULE}.utils.mm_exec_wait", side_effect=exec_wait)
    mm.cc_exec_once.side_effect = lambda cmd: events.append(cmd)
    recv.side_effect = lambda mm, vm, src, dst: (
        events.append("recv"),
        Path(dst).write_text(STATS if src.endswith("snort.stats") else "x"),
    )

    _run(component_args, "stop")

    assert events[:4] == ["pkill -INT snort", "timeout", "ls", "recv"]
