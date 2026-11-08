"""Builders for running the real ot-sim app against a small experiment."""

import io

import lxml.etree as ET
import pytest
from box import Box

from phenix_apps.apps.otsim.app import OTSim


def topo_node(hostname, address, iface="eth0", vlan="OT"):
    """A topology node with one addressed interface."""
    return {
        "general": {"hostname": hostname},
        "hardware": {"os_type": "linux"},
        "network": {
            "interfaces": [
                {"name": iface, "address": address, "mask": 24, "vlan": vlan}
            ]
        },
    }


@pytest.fixture
def run_otsim(monkeypatch, tmp_path):
    """Run ot-sim pre-start and return the app.

    `nodes` are topology nodes, `hosts` the ot-sim app hosts, `metadata` the
    ot-sim app metadata, and `extra_apps` any other scenario apps.
    """

    def run(nodes, hosts, metadata=None, extra_apps=()):
        exp = Box(
            {
                "spec": {
                    "experimentName": "test",
                    "baseDir": str(tmp_path / "exp"),
                    "topology": {"nodes": nodes},
                    "scenario": {
                        "apps": [
                            {
                                "name": "ot-sim",
                                "metadata": metadata or {},
                                "hosts": hosts,
                            },
                            *extra_apps,
                        ]
                    },
                }
            }
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(exp.to_json()))
        app = OTSim("ot-sim", "pre-start")
        app.pre_start()
        return app

    return run


def config_xml(app, hostname):
    """Parse the config.xml ot-sim rendered for a host."""
    return ET.parse(str(app.otsim_dir / f"{hostname}.xml")).getroot()


def injections(app, hostname):
    """The injections the app added to a topology node, as (src, dst) pairs."""
    node = app.extract_node(hostname)
    return [(i.src, i.dst) for i in node.get("injections") or []]
