from pathlib import Path
from unittest import mock

import pytest
from box import Box
from pydantic import ValidationError

from phenix_apps.apps.scorch.art import art
from phenix_apps.apps.scorch.art.art import AtomicRedTeam


@pytest.fixture
def make(tmp_path, monkeypatch):
    """make(metadata, exits) returns an art component and the commands it runs
    in the VM; a command exits with the code of the first prefix in `exits` it
    starts with, 0 otherwise."""

    commands: list[str] = []
    monkeypatch.setattr(art.time, "sleep", lambda s: None)

    def recv(mm, vm, src, dst):
        Path(dst).write_text('{"Executor": {"ExecutedCommand": {"results": "Linux"}}}')

    monkeypatch.setattr(art.utils, "mm_recv", recv)

    def run(metadata: dict, exits: dict[str, int] | None = None):
        def exec_wait(mm, vm, cmd):
            commands.append(cmd)
            code = next((c for p, c in (exits or {}).items() if cmd.startswith(p)), 0)
            return {"exitcode": code, "stdout": "", "stderr": "unknown technique"}

        monkeypatch.setattr(art.utils, "mm_exec_wait", exec_wait)

        comp = AtomicRedTeam.__new__(AtomicRedTeam)
        comp.name = "art"
        comp.base_dir = tmp_path
        comp.metadata = Box(
            {
                "technique": "T1082",
                "testIndex": 0,
                "vms": [{"hostname": "g1"}],
                **metadata,
            }
        )
        comp.mm_init = mock.Mock()  # type: ignore[method-assign]
        comp.extract_node_os_type = mock.Mock(return_value="linux")  # type: ignore[method-assign]
        return comp, commands

    return run


def test_missing_goart_fails_the_start(make):
    comp, commands = make({}, exits={"test -x": 1})

    with pytest.raises(
        RuntimeError,
        match="goart not found or not executable at /phenix/art/goart on g1",
    ):
        comp.start()

    assert commands == ["test -x /phenix/art/goart"]


def test_goart_path_output_path_and_exec_wait_are_honored(make, monkeypatch):
    slept = []
    comp, commands = make(
        {
            "goartPath": "/opt/e2e-art/goart",
            "outputPath": "/var/tmp/e2e-art/",
            "execWaitSeconds": 1,
            "env": {"E2E_ENV": "night"},
        }
    )
    monkeypatch.setattr(art.time, "sleep", slept.append)

    comp.start()

    check, run = commands
    assert check == "test -x /opt/e2e-art/goart"
    argv = run.split()
    out = argv[argv.index("-o") + 1]
    assert argv[0] == "/opt/e2e-art/goart"
    assert out.startswith("/var/tmp/e2e-art/")
    assert out.endswith(".json")
    assert argv[argv.index("-o") + 2 :] == ["-i", "0", "--env", "E2E_ENV=night"]
    assert slept == [1.0]


def test_a_failing_goart_fails_with_abort_on_error(make):
    comp, _ = make({"abortOnError": True}, exits={"/phenix/art/goart -q": 2})

    with pytest.raises(RuntimeError, match="goart exited 2 on g1: unknown"):
        comp.start()


def test_a_failing_goart_is_only_logged_without_abort_on_error(make):
    comp, commands = make({}, exits={"/phenix/art/goart -q": 2})

    comp.start()

    assert len(commands) == 2


@pytest.mark.parametrize("option", ["goartPath", "outputPath"])
def test_paths_with_shell_characters_are_refused(make, option):
    comp, _ = make({option: "/tmp/x; reboot"})

    with pytest.raises(ValidationError):
        comp.start()
