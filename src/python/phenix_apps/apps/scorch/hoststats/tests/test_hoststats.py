"""hoststats runs in the background until phenix's SIGTERM, then flushes."""

import json
import os
import signal
import threading
import time
from types import SimpleNamespace

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.hoststats import hoststats
from phenix_apps.apps.scorch.hoststats.hoststats import HostStats


@pytest.fixture
def mm(mocker):
    """minimega with one host and no VMs."""
    fake = mocker.MagicMock(name="mm")
    fake.vm_info.return_value = []
    # __get_resdata pops fields from the row, so each poll gets a fresh one.
    fake.host.side_effect = lambda: [
        {"Host": "h1", "Data": {"Name": "h1", "Load": "0.10 0.20 0.30"}}
    ]
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    return fake


def _start(component_args, component, metadata=None):
    spec = {"name": "hs", "type": "hoststats", "metadata": metadata or {}}
    spec.update(component)
    files_dir = component_args(
        scorch_experiment([spec], [{"start": ["hs"]}]), "start", "hs"
    )
    HostStats()
    return files_dir / "scorch/run-0/hs/loop-0-count-0"


@pytest.fixture
def sigterm_after(mocker):
    """Send SIGTERM ``seconds`` after hoststats installs its SIGTERM handler.

    A timer armed earlier could fire before then: before ComponentBase installs
    its handler, SIGTERM kills pytest, and after that, ComponentBase ignores it
    and start polls on.
    """
    timers = []

    def arm(seconds):
        def install(signum, handler):
            previous = signal.signal(signum, handler)
            timer = threading.Timer(seconds, os.kill, (os.getpid(), signal.SIGTERM))
            timers.append(timer)
            timer.start()
            return previous

        # Only hoststats' own reference to the signal module.
        mocker.patch.object(
            hoststats, "signal", SimpleNamespace(SIGTERM=signal.SIGTERM, signal=install)
        )

    yield arm

    for timer in timers:
        timer.cancel()


@pytest.mark.parametrize("component", [{}, {"background": False}], ids=str)
def test_foreground_start_fails_instead_of_blocking(component_args, mm, component):
    with pytest.raises(RuntimeError, match="background: true"):
        _start(component_args, component)

    mm.host.assert_not_called()


def test_sigterm_ends_start_without_waiting_out_the_poll_period(
    component_args, mm, sigterm_after
):
    # phenix kills a background component 10 s after its SIGTERM.
    sigterm_after(0.5)
    began = time.monotonic()

    out = _start(component_args, {"background": True}, {"pollPeriod": 30})

    assert time.monotonic() - began < 5
    rows = [json.loads(line) for line in (out / "host_stats.jsonl").open()]
    assert [(r["compute_name"], r["Load_15"]) for r in rows] == [("h1", 0.3)]
    (status,) = out.glob("start-*.json")
    assert "Stopped user component: hs" in status.read_text()


def test_sigterm_flushes_what_the_flush_period_held_back(
    component_args, mm, sigterm_after
):
    sigterm_after(0.5)

    out = _start(
        component_args,
        {"background": True},
        {"pollPeriod": 0.05, "flushPeriod": 60},
    )

    # The first poll flushes at once; every later one only at SIGTERM.
    assert len((out / "host_stats.jsonl").read_text().splitlines()) > 1


def test_a_failed_poll_fails_start(component_args, mm):
    mm.vm_info.side_effect = RuntimeError("minimega is gone")

    with pytest.raises(RuntimeError, match="stopped polling minimega"):
        _start(component_args, {"background": True}, {"pollPeriod": 30})


def test_a_sigterm_before_start_runs_still_stops_it(component_args, mm, mocker):
    """ComponentBase ignores SIGTERM in a background start until the component
    installs its own handler."""
    run_stage = HostStats.execute_stage

    def sigterm_first(self):
        os.kill(os.getpid(), signal.SIGTERM)
        # Ends start if the first SIGTERM was lost.
        backup = threading.Timer(3, os.kill, (os.getpid(), signal.SIGTERM))
        backup.start()
        try:
            run_stage(self)
        finally:
            backup.cancel()

    mocker.patch.object(HostStats, "execute_stage", sigterm_first)
    began = time.monotonic()

    _start(component_args, {"background": True}, {"pollPeriod": 30})

    assert time.monotonic() - began < 2
