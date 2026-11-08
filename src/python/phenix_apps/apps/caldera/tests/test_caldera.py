"""Caldera server nodes added in configure, and their pre-start injects."""

import io
import json
from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.caldera.app import Caldera
from phenix_apps.common import settings


@pytest.fixture
def caldera(monkeypatch, tmp_path):
    """Return a function that configures server mallory and returns the app."""
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
        return app

    return run


@pytest.fixture
def configure(caldera):
    def run(interfaces):
        return caldera(interfaces).extract_node("mallory").network.interfaces

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


def test_firefox_policies_skip_terms_of_use(caldera):
    app = caldera([{"address": "10.20.0.50/24", "vlan": "EXP"}])
    app.pre_start()

    injects = {i.dst: i.src for i in app.extract_node("mallory").injections}
    policies = json.loads(
        Path(injects["/etc/firefox/policies/policies.json"]).read_text()
    )

    # The file replaces the image's own policies.json, so it must keep Firefox's
    # Terms of Use dialog from covering Caldera too.
    assert policies == {
        "policies": {
            "SkipTermsOfUse": True,
            "Bookmarks": [
                {
                    "Title": "Caldera",
                    "URL": "http://10.20.0.50:8888",
                    "Placement": "toolbar",
                }
            ],
        }
    }
