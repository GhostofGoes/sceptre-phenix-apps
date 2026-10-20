"""Tests for how field device servers pick their infrastructure.

The app-level `infrastructure` drives both register maps and I/O tags.
"""

import pytest
from box import Box

from phenix_apps.apps.otsim.device import FieldDeviceServer
from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node


def server(metadata, *args):
    device = FieldDeviceServer(Box({"metadata": metadata}), *args)
    device.process({})
    return {reg.tag for reg in device.registers["dnp3"]}


def test_server_uses_default_infrastructure():
    tags = server(
        {"dnp3": [{"type": "bus", "name": "bus-1"}]}, "power-3-phase-distribution"
    )

    assert "bus-1.Va-mag" in tags
    assert "bus-1.voltage" not in tags


def test_host_infrastructure_overrides_default():
    md = {
        "infrastructure": "power-distribution",
        "dnp3": [{"type": "bus", "name": "bus-1"}],
    }

    assert server(md, "power-3-phase-distribution") == {"bus-1.voltage"}


NODES = [topo_node("power", "10.20.0.5"), topo_node("rtu-1", "10.20.0.11")]

THREE_PHASE_BUS = {
    f"bus-01.V{phase}-{part}" for phase in "abc" for part in ("mag", "ang")
}


def _tags(root):
    registers = {t.text for t in root.iterfind("modbus[@mode='server']/register/tag")}
    subscriptions = {t.text for t in root.iterfind("io/subscription/tag")}
    return registers, subscriptions


@pytest.mark.parametrize("where", ["app", "host"])
def test_infrastructure_reaches_registers(run_otsim, where):
    rtu_md = {"type": "fd-server", "modbus": [{"name": "bus-01", "type": "bus"}]}
    app_md = {"helics": {"broker": {"address": "10.20.0.5"}}}
    if where == "app":
        app_md["infrastructure"] = "power-3-phase-distribution"
    else:
        rtu_md["infrastructure"] = "power-3-phase-distribution"

    app = run_otsim(NODES, [{"hostname": "rtu-1", "metadata": rtu_md}], app_md)

    registers, subscriptions = _tags(config_xml(app, "rtu-1"))
    assert registers == THREE_PHASE_BUS
    assert subscriptions == THREE_PHASE_BUS


def test_host_infrastructure_overrides_app(run_otsim):
    rtu_md = {
        "type": "fd-server",
        "infrastructure": "power-distribution",
        "modbus": [{"name": "bus-01", "type": "bus"}],
    }
    app_md = {
        "infrastructure": "power-3-phase-distribution",
        "helics": {"broker": {"address": "10.20.0.5"}},
    }

    app = run_otsim(NODES, [{"hostname": "rtu-1", "metadata": rtu_md}], app_md)

    registers, subscriptions = _tags(config_xml(app, "rtu-1"))
    assert registers == {"bus-01.voltage"}
    assert subscriptions == {"bus-01.voltage"}
