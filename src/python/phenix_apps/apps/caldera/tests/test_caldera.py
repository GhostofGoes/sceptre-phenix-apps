"""Caldera server nodes added in configure."""

import io

import pytest
from box import Box

from phenix_apps.apps.caldera.app import Caldera
from phenix_apps.common import settings


@pytest.fixture
def configure(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PHENIX_DIR", str(tmp_path / "phenix"))

    def run(interfaces):
        exp = Box(
            {
                "spec": {
                    "experimentName": "test",
                    "baseDir": str(tmp_path / "exp"),
                    "topology": {"nodes": []},
                    "scenario": {
                        "apps": [
                            {
                                "name": "caldera",
                                "metadata": {
                                    "servers": [
                                        {
                                            "hostname": "mallory",
                                            "interfaces": interfaces,
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            }
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(exp.to_json()))
        app = Caldera("caldera", "configure")
        app.configure()
        return app.extract_node("mallory").network.interfaces

    return run


def test_interface_with_gateway(configure):
    ifaces = configure(
        [{"address": "10.20.0.50/24", "gateway": "10.20.0.254", "vlan": "EXP"}]
    )

    assert ifaces.to_list() == [
        {
            "name": "IF0",
            "type": "ethernet",
            "proto": "static",
            "address": "10.20.0.50",
            "mask": 24,
            "gateway": "10.20.0.254",
            "vlan": "EXP",
        }
    ]


def test_interfaces_without_gateway(configure):
    ifaces = configure(
        [
            {"address": "10.20.0.50/24", "gateway": "10.20.0.254", "vlan": "EXP"},
            {"address": "172.16.0.50/16", "vlan": "MGMT"},
        ]
    )

    assert ifaces[0].gateway == "10.20.0.254"
    assert ifaces[1].to_dict() == {
        "name": "IF1",
        "type": "ethernet",
        "proto": "static",
        "address": "172.16.0.50",
        "mask": 16,
        "vlan": "MGMT",
    }
