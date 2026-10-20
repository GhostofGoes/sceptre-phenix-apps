"""How the kafka component launches its listener process."""

import sys
from pathlib import Path

import pytest

from phenix_apps.apps.scorch.app import StageCanceled
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.kafka import kafka_component
from phenix_apps.apps.scorch.kafka.kafka_component import Kafka

METADATA = {
    "kafka_endpoints": [{"ip": "10.0.0.7", "port": "9092"}],
    "topics": [{"name": "exp.foo*"}],
    "wait_duration_seconds": 30,
}


@pytest.fixture
def popen(mocker):
    """subprocess.Popen, returning a listener that is still running."""
    mocker.patch("time.sleep")
    proc = mocker.MagicMock(pid=4242)
    proc.poll.return_value = None
    return mocker.patch.object(kafka_component.subprocess, "Popen", return_value=proc)


@pytest.fixture
def configure(component_args, tmp_path):
    """Run configure under an experiment name unique to the test."""
    started = []

    def run():
        exp = scorch_experiment(
            [{"name": "kafka", "type": "kafka", "metadata": METADATA}],
            [{"configure": ["kafka"], "cleanup": ["kafka"]}],
            name=f"kafka-test-{tmp_path.name}",
        )
        files_dir = component_args(exp, "configure", "kafka")
        try:
            started.append(Kafka())
        finally:
            for pid_file in Path("/tmp").glob(
                f"phenix-scorch-kafka-{exp['spec']['experimentName']}-*.pid"
            ):
                pid_file.unlink()
        return files_dir / "scorch/run-0/kafka/loop-0-count-0"

    return run


def test_listener_runs_under_the_components_interpreter(configure, popen):
    base = configure()

    argv = popen.call_args.args[0]
    assert argv[0] == sys.executable
    assert argv[1].endswith("phenix_apps/apps/scorch/kafka/kafka_listener.py")
    assert argv[2:] == [
        "True",
        str(base / "kafka_output.csv"),
        "10.0.0.7:9092",
        '[{"name": "exp.foo*"}]',
        argv[6],
        "30",
    ]
    assert argv[6].startswith("kafka-test-")

    # The listener outlives the component, so its output goes to a file.
    stderr = popen.call_args.kwargs["stderr"]
    assert stderr is not kafka_component.subprocess.DEVNULL
    assert Path(stderr.name) == base / "kafka_listener.log"


def test_listener_that_exits_at_once_fails_configure(configure, popen):
    popen.return_value.poll.return_value = 1

    with pytest.raises(
        RuntimeError, match=r"listener exited with status 1.*kafka_listener\.log"
    ):
        configure()


def test_a_cancel_during_the_startup_grace_kills_the_listener(configure, popen, mocker):
    """The listener runs in its own session, so nothing else would stop it."""
    mocker.patch.object(
        kafka_component.time, "sleep", side_effect=StageCanceled("signal 15")
    )

    with pytest.raises(RuntimeError, match="signal 15"):
        configure()

    popen.return_value.kill.assert_called_once_with()
