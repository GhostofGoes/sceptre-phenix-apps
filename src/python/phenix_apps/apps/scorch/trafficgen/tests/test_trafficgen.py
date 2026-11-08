from unittest import mock

import pytest
from box import Box

from phenix_apps.apps.scorch.trafficgen import trafficgen
from phenix_apps.apps.scorch.trafficgen.trafficgen import TrafficGen

SCRIPTS = {
    "trafficServer": "/x/traffic-server.py",
    "backgroundGen": "/x/background-gen.py",
    "malwareGen": "/x/malware-gen.py",
}


@pytest.fixture
def start(monkeypatch):
    """start(target) runs trafficgen's start for one target and returns its
    minimega calls."""

    monkeypatch.setattr(trafficgen.time, "sleep", lambda s: None)

    def run(target: dict) -> list:
        comp = TrafficGen.__new__(TrafficGen)
        comp.name = "tg"
        comp.metadata = Box({"scripts": SCRIPTS, "targets": [target]})
        comp.mm_init = mock.Mock()  # type: ignore[method-assign]
        comp.extract_node_ip = mock.Mock(return_value="10.0.0.1")  # type: ignore[method-assign]
        comp.start()
        return comp.mm_init.return_value.method_calls

    return run


def test_the_malware_generator_gets_its_own_settings(start):
    calls = start(
        {
            "hostname": "g1",
            "duration": 10,
            "backgroundClient": {"hostname": "g2", "rate": 20, "probability": 0.5},
            "malwareClient": {"hostname": "g3", "rate": 10, "probability": 0.75},
        }
    )

    assert calls[-3:] == [
        mock.call.cc_filter("name=g3"),
        mock.call.cc_background(
            "python3 /malware-gen.py --ip 10.0.0.1 --rate 10 --duration 10 "
            "--probability 0.75"
        ),
        mock.call.clear_cc_filter(),
    ]


def test_a_malware_generator_without_a_background_one(start):
    calls = start({"hostname": "g1", "malwareClient": {"hostname": "g3"}})

    assert calls[-2] == mock.call.cc_background(
        "python3 /malware-gen.py --ip 10.0.0.1 --rate 20 --duration 5 "
        "--probability 1.25"
    )
