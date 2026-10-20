import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import phenix_apps

_DUMMY_APP = """\
from phenix_apps.apps import AppBase
from phenix_apps.common.logger import logger


class DummyApp(AppBase):
    def pre_start(self):
        logger.info("dummy pre-start ran")


DummyApp.main("dummy")
"""


def _run_dummy_app(tmp_path: Path, args: list[str], env: dict[str, str]):
    """Run a minimal AppBase app in a fresh interpreter, as phenix runs apps."""

    script = tmp_path / "dummy_app.py"
    script.write_text(_DUMMY_APP)

    experiment = {
        "spec": {
            "experimentName": "dummy",
            "baseDir": str(tmp_path / "exp"),
            "scenario": {"apps": [{"name": "dummy"}]},
        }
    }

    package_root = str(Path(phenix_apps.__file__).resolve().parents[1])
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("PHENIX_")}
    run_env["PYTHONPATH"] = os.pathsep.join(
        p for p in (package_root, os.environ.get("PYTHONPATH")) if p
    )
    run_env["PHENIX_LOG_LEVEL"] = "INFO"
    run_env.update(env)

    res = subprocess.run(
        [sys.executable, str(script), "pre-start", *args],
        input=json.dumps(experiment),
        capture_output=True,
        text=True,
        env=run_env,
        check=False,
    )

    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == experiment

    return [line for line in res.stderr.splitlines() if line.strip()]


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--dry-run"], {"PHENIX_LOG_FILE": "stderr"}),
        ([], {"PHENIX_LOG_FILE": "stderr", "PHENIX_DRYRUN": "true"}),
    ],
    ids=["dry-run-flag", "phenix-dryrun-env"],
)
def test_dry_run_logs_json_when_phenix_reads_stderr(tmp_path, args, env):
    lines = _run_dummy_app(tmp_path, args, env)

    assert lines
    entries = [json.loads(line) for line in lines]
    assert all(entry["level"] and isinstance(entry["msg"], str) for entry in entries)
    assert "dummy pre-start ran" in [entry["msg"] for entry in entries]


@pytest.mark.parametrize("log_file", ["", "app.log"])
def test_local_dry_run_logs_human_readable_lines(tmp_path, log_file):
    env = {"PHENIX_LOG_FILE": str(tmp_path / log_file) if log_file else ""}

    lines = _run_dummy_app(tmp_path, ["--dry-run"], env)

    # loguru colors console lines when it detects CI (GITHUB_ACTIONS=true).
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines]
    line = next(line for line in plain if "dummy pre-start ran" in line)
    assert "| INFO" in line
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)
    assert not (tmp_path / "app.log").exists()
