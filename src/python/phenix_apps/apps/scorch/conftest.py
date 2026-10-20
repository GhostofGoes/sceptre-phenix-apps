"""Fixtures for constructing SCORCH components the way phenix runs them.

phenix calls `phenix-scorch-component-<type> <stage> <name> <run> <loop> <count>`
with the experiment JSON on stdin; `ComponentBase.__init__` reads all of it, so
these fixtures set argv, stdin and the files directory before construction.
"""

import contextlib
import functools
import io
import json
import os
import signal
import sys
from unittest import mock

import pytest
from loguru import logger

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.common import utils

# The cc calls that queue a command, which takes the namespace's cc filter.
CC_COMMANDS = (
    "cc_exec",
    "cc_exec_once",
    "cc_background",
    "cc_background_once",
    "cc_send",
)


def scorch_experiment(components, runs, nodes=(), name="exp"):
    """An experiment whose scorch app has these components and runs.

    `runs` take the shape phenix stores: every stage key present, null when
    unused, `loop` null without a nested loop, and `count` 0 when unset.
    """
    full_runs = []
    for run in runs:
        full_runs.append(
            {
                "configure": None,
                "start": None,
                "stop": None,
                "cleanup": None,
                "loop": None,
                "count": 0,
                "filebeat": None,
                "replace": None,
                **run,
            }
        )

    return {
        "metadata": {"annotations": {"topology": "topo", "scenario": "scn"}},
        "spec": {
            "experimentName": name,
            "baseDir": f"/phenix/experiments/{name}",
            "topology": {"nodes": list(nodes)},
            "scenario": {
                "apps": [
                    {
                        "name": "scorch",
                        "metadata": {"components": components, "runs": full_runs},
                    }
                ]
            },
        },
    }


@pytest.fixture
def component_args(monkeypatch, tmp_path):
    """Return a callable that prepares argv, stdin and PHENIX_FILES_DIR.

    Returns the files directory the component will write below.
    """

    files_dir = tmp_path / "files"
    monkeypatch.setenv("PHENIX_FILES_DIR", str(files_dir))
    sigterm = signal.getsignal(signal.SIGTERM)

    def prepare(experiment, stage, name, run=0, loop=0, count=0):
        monkeypatch.setattr(
            sys,
            "argv",
            ["phenix-scorch-component", stage, name, str(run), str(loop), str(count)],
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(experiment)))
        return files_dir

    yield prepare

    # ComponentBase replaces the SIGTERM handler, and execute_stage replaces
    # every loguru handler; restore a plain stderr handler for later tests.
    signal.signal(signal.SIGTERM, sigterm)
    logger.remove()
    logger.add(lambda msg: sys.stderr.write(msg))


@pytest.fixture
def fake_tshark(monkeypatch, tmp_path):
    """Put a ``tshark`` on PATH that prints its arguments, one per line.

    Runs in ``tmp_path``, so a test can check that no shell expanded anything.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tshark = bin_dir / "tshark"
    tshark.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    tshark.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def log_messages():
    """Messages logged through loguru until a component's execute_stage runs.

    execute_stage removes every loguru handler, this one included.
    """
    messages = []
    handler = logger.add(lambda msg: messages.append(msg.record["message"]))
    yield messages
    with contextlib.suppress(ValueError):
        logger.remove(handler)


class CCNamespace:
    """A fake minimega namespace's cc filter, behind the `mm` it belongs to.

    minimega keeps the cc filter as namespace state and copies it into each cc
    command as it queues it. `filter` is the filter set now, and `queued` holds
    a `(method, command, filter)` row for each command queued. The cc helpers
    that run a command in one VM aim the filter at its UUID, as the real ones
    do, and return `result`.
    """

    def __init__(self, mm):
        self.mm = mm
        self.filter = None
        self.queued = []
        self.result = {"exitcode": 0, "stdout": "ok", "stderr": ""}

        mm.cc_filter.side_effect = self._set_filter
        mm.clear_cc_filter.side_effect = self._clear_filter
        for name in CC_COMMANDS:
            getattr(mm, name).side_effect = functools.partial(self._queue, name)

    def _set_filter(self, *args, **kwargs):
        self.filter = kwargs.get("filter", args[0] if args else None)
        return mock.DEFAULT

    def _clear_filter(self):
        self.filter = None
        return mock.DEFAULT

    def _queue(self, method, command, *_args, **_kwargs):
        self.queued.append((method, command, self.filter))
        return mock.DEFAULT

    def exec_wait(self, mm, vm, cmd, once=True, **_kwargs):
        mm.cc_filter(f"uuid={vm}-uuid")
        (mm.cc_exec_once if once else mm.cc_exec)(cmd)
        return {"id": "1", "cmd": cmd, **self.result}

    def cc_send_wait(self, mm, vm, src, _exp_name, **_kwargs):
        mm.cc_filter(f"uuid={vm}-uuid")
        mm.cc_send(src)


@pytest.fixture
def cc_namespace(mocker):
    """The `CCNamespace` of the minimega every component's `mm_init` returns.

    The cc helpers that wait for a VM run against it, every client is
    registered, and file transfers, which mount the VM's files and need no
    filter, do nothing.
    """
    ns = CCNamespace(mocker.MagicMock(name="mm"))
    mocker.patch.object(ComponentBase, "mm_init", return_value=ns.mm)
    mocker.patch.object(utils, "mm_exec_wait", side_effect=ns.exec_wait)
    mocker.patch.object(
        utils, "mm_cc_client_locate", side_effect=lambda _mm, vm, **_: (vm, "host")
    )
    mocker.patch.object(utils, "mm_cc_send_wait", side_effect=ns.cc_send_wait)
    mocker.patch.object(utils, "mm_send")
    mocker.patch.object(utils, "mm_recv")
    return ns
