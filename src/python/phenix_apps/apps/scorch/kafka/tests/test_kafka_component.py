import sys
from pathlib import Path
from unittest import mock

import pytest
from box import Box

from phenix_apps.apps.scorch.kafka import kafka_component
from phenix_apps.apps.scorch.kafka.kafka_component import LISTENER, Kafka


@pytest.fixture
def kafka(tmp_path, monkeypatch):
    monkeypatch.setattr(kafka_component.time, "sleep", lambda s: None)
    comp = Kafka.__new__(Kafka)
    comp.name = "k"
    comp.exp_name = "exp"
    comp.component_id = "abc"
    comp.base_dir = tmp_path / "out"
    comp.pid_file = tmp_path / "k.pid"
    comp.metadata = Box({"topics": [{"name": "t"}]})
    return comp


def test_listener_runs_under_this_interpreter(kafka, monkeypatch, tmp_path):
    popen = mock.Mock(return_value=mock.Mock(pid=42, poll=mock.Mock(return_value=None)))
    monkeypatch.setattr(kafka_component.subprocess, "Popen", popen)

    kafka.configure()

    (command,), kwargs = popen.call_args
    assert command[:2] == [sys.executable, str(LISTENER)]
    assert command[3] == str(tmp_path / "out" / "k_output.csv")
    assert command[5] == '[{"name": "t"}]'
    assert Path(kwargs["stdout"].name) == tmp_path / "out" / "kafka_listener.log"
    assert kafka.pid_file.read_text() == "42"


def test_a_listener_that_dies_at_once_fails_configure(kafka, monkeypatch):
    popen = mock.Mock(return_value=mock.Mock(pid=42, poll=mock.Mock(return_value=1)))
    monkeypatch.setattr(kafka_component.subprocess, "Popen", popen)

    with pytest.raises(RuntimeError, match="exited with status 1 right after"):
        kafka.configure()

    assert not kafka.pid_file.exists()
