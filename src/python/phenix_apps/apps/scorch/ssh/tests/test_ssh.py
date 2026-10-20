"""The ssh component fails when its remote work fails."""

import json

import pytest

from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.ssh.ssh import SSH


@pytest.fixture
def client(mocker):
    """A paramiko SSHClient whose command exits with `client.exit_status`."""
    fake = mocker.MagicMock(name="SSHClient")
    mocker.patch(
        "phenix_apps.apps.scorch.ssh.ssh.paramiko.SSHClient", return_value=fake
    )

    def exec_command(command):
        stdout = mocker.MagicMock()
        stdout.read.return_value = b"out\n"
        stdout.channel.recv_exit_status.return_value = fake.exit_status
        stderr = mocker.MagicMock()
        stderr.read.return_value = b"boom\n" if fake.exit_status else b""
        return mocker.MagicMock(), stdout, stderr

    fake.exit_status = 0
    fake.exec_command.side_effect = exec_command
    return fake


def _run(component_args, metadata):
    md = {"ip": "10.0.0.9", "user": "root", "cmds": ["true", "false"], **metadata}
    files_dir = component_args(
        scorch_experiment(
            [{"name": "ssh", "type": "ssh", "metadata": md}], [{"start": ["ssh"]}]
        ),
        "start",
        "ssh",
    )
    base = files_dir / "scorch/run-0/ssh/loop-0-count-0"
    try:
        SSH()
    finally:
        record = base / "ssh_metadata_start.json"
        metadata_log = json.loads(record.read_text()) if record.exists() else None
    return metadata_log


def test_success(component_args, client):
    log = _run(component_args, {})

    client.exec_command.assert_called_once_with("true && false")
    (result,) = [e["data"] for e in log if "exit_status" in e["data"]]
    assert result == {
        "host": "10.0.0.9",
        "cmd": "true && false",
        "stdout": "out",
        "stderr": "",
        "exit_status": 0,
    }


def test_failing_remote_command_fails_the_stage(component_args, client):
    client.exit_status = 1

    with pytest.raises(RuntimeError, match=r"10\.0\.0\.9.*exit status 1.*boom"):
        _run(component_args, {})


def test_failed_file_fetch_fails_the_stage(component_args, client):
    client.open_sftp.return_value.stat.side_effect = FileNotFoundError("no such file")

    with pytest.raises(RuntimeError, match=r"/var/log/collect\.log.*no such file"):
        _run(component_args, {"files": ["/var/log/collect.log"]})


def test_command_that_cannot_run_fails_the_stage(component_args, client):
    client.exec_command.side_effect = OSError("channel closed")

    with pytest.raises(
        RuntimeError, match=r"true && false.*10\.0\.0\.9.*channel closed"
    ):
        _run(component_args, {"files": ["/var/log/collect.log"]})

    client.open_sftp.assert_not_called()
