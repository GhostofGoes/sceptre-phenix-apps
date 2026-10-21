"""Root and sub-broker scripts the helics app writes from federate annotations."""

import io

import pytest
from box import Box

from phenix_apps.apps.helics.app import Helics


def _node(hostname, address, annotations=None):
    return {
        "general": {"hostname": hostname},
        "hardware": {"os_type": "linux"},
        "network": {"interfaces": [{"name": "eth0", "address": address, "mask": 24}]},
        "annotations": annotations or {},
    }


@pytest.fixture
def run_helics(monkeypatch, tmp_path):
    def run(federates):
        nodes = [_node("power", "10.20.0.5"), _node("sub", "10.20.0.12")]
        for idx, configs in enumerate(federates, start=1):
            nodes.append(
                _node(f"fed-{idx}", f"10.20.0.{20 + idx}", {"helics/federate": configs})
            )

        exp = Box(
            {
                "spec": {
                    "experimentName": "test",
                    "baseDir": str(tmp_path / "exp"),
                    "topology": {"nodes": nodes},
                    "scenario": {
                        "apps": [
                            {
                                "name": "helics",
                                "metadata": {"broker": {"root": "power|eth0"}},
                            }
                        ]
                    },
                }
            }
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(exp.to_json()))
        app = Helics("helics", "pre-start")
        app.pre_start()
        return app

    return run


def _script(app, hostname):
    return (app.helics_dir / f"{hostname}-broker.sh").read_text()


@pytest.mark.parametrize(
    "broker", ["10.20.0.12", "10.20.0.12:24000", "sub|eth0"], ids=str
)
def test_sub_broker_address_forms(run_helics, broker):
    app = run_helics([[{"broker": broker, "fed-count": 2}]])

    sub = _script(app, "sub")
    assert "--broker 10.20.0.5 --local_interface 10.20.0.12:24000" in sub
    assert "-f2" in sub
    assert app.extract_node("sub").labels.to_dict() == {
        "group": "helics",
        "helics": "broker",
    }

    root = _script(app, "power")
    assert "--subbrokers 1" in root
    assert "-f2" in root


def test_federates_sharing_a_sub_broker_add_up(run_helics):
    app = run_helics(
        [
            [{"broker": "10.20.0.12", "fed-count": 2, "log-level": "debug"}],
            [{"broker": "sub|eth0", "fed-count": 1, "log-level": "trace"}],
        ]
    )

    sub = _script(app, "sub")
    assert sub.count("helics_broker") == 1
    assert "-f3" in sub
    assert "--loglevel debug" in sub
    assert "--subbrokers 1" in _script(app, "power")


def test_two_sub_brokers_on_one_host(run_helics):
    app = run_helics(
        [
            [{"broker": "10.20.0.12:24000", "fed-count": 1}],
            [{"broker": "10.20.0.12:24001", "fed-count": 2}],
        ]
    )

    sub = _script(app, "sub")
    assert sub.count("helics_broker") == 2
    assert "--local_interface 10.20.0.12:24000" in sub
    assert "--local_interface 10.20.0.12:24001" in sub

    root = _script(app, "power")
    assert "--subbrokers 2" in root
    assert "-f3" in root
