"""Analog Modbus points use a register type wide enough for signed values."""

import lxml.etree as ET
import pytest

from phenix_apps.apps.otsim.device import Register
from phenix_apps.apps.otsim.protocols.modbus import Modbus
from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node

NODES = [
    topo_node("power", "10.20.0.5"),
    topo_node("rtu-1", "10.20.0.11"),
    topo_node("fep-1", "10.20.0.21"),
]

APP_MD = {"helics": {"broker": {"address": "10.20.0.5"}}}

RTU = {
    "hostname": "rtu-1",
    "metadata": {"type": "fd-server", "modbus": [{"name": "brk", "type": "breaker"}]},
}

FEP = {
    "hostname": "fep-1",
    "metadata": {"type": "fep", "upstream": ["rtu-1"], "downstream": ["modbus"]},
}


def _registers(root, mode, endpoint):
    (block,) = [
        m
        for m in root.findall(f"modbus[@mode='{mode}']")
        if m.findtext("endpoint") == endpoint
    ]
    return [
        (
            r.get("type"),
            r.get("data-type"),
            int(r.findtext("address")),
            r.findtext("tag"),
        )
        for r in block.findall("register")
    ]


BREAKER = [
    ("input", "int32", 30001, "brk.voltage"),
    ("input", "int32", 30003, "brk.current"),
    ("input", "int32", 30005, "brk.freq"),
    ("input", "int32", 30007, "brk.power"),
    ("discrete", None, 10001, "brk.status"),
    ("coil", None, 1, "brk.controls"),
]


def test_default_analog_points_are_int32(run_otsim):
    app = run_otsim(NODES, [RTU, FEP], APP_MD)

    server = _registers(config_xml(app, "rtu-1"), "server", "10.20.0.11:502")
    assert server == BREAKER

    # The FEP polls rtu-1 and re-serves its points with the same layout.
    fep = config_xml(app, "fep-1")
    assert _registers(fep, "client", "10.20.0.11:502") == BREAKER
    assert _registers(fep, "server", "10.20.0.21:502") == BREAKER


def test_infrastructure_can_choose_the_data_type(run_otsim):
    md = {
        **APP_MD,
        "infrastructures": {
            "power-distribution": {
                "breaker": {
                    "voltage": {
                        "type": "analog-read",
                        "modbus": {"scaling": 2, "data-type": "uint16"},
                    },
                    "current": {
                        "type": "analog-read",
                        "modbus": {"data-type": "float"},
                    },
                }
            }
        },
    }
    app = run_otsim(NODES, [RTU], md)

    server = config_xml(app, "rtu-1").find("modbus[@mode='server']")
    regs = {r.findtext("tag"): r for r in server.findall("register")}
    assert regs["brk.voltage"].get("data-type") == "uint16"
    assert regs["brk.voltage"].findtext("scaling") == "-2"
    assert regs["brk.current"].get("data-type") == "float"
    assert regs["brk.current"].find("scaling") is None
    assert [int(r.findtext("address")) for r in regs.values()][:4] == [
        30001,
        30002,
        30004,
        30006,
    ]


def test_unknown_data_type_names_the_tag():
    mb = Modbus()
    mb.mode = "server"
    mb.root = ET.Element("modbus")

    with pytest.raises(ValueError, match=r"brk\.power.*int8"):
        mb.registers_to_xml(
            [Register("analog-read", "brk.power", {"data-type": "int8"})]
        )


def test_registers_without_a_data_type_keep_one_register_each():
    """wind-turbine and the scale plugin build their own registers."""
    mb = Modbus()
    mb.mode = "client"
    mb.root = ET.Element("modbus")

    mb.registers_to_xml(
        [
            Register("analog-read", "a", {"scaling": 2}),
            Register("analog-read", "b", {"scaling": 2}),
        ]
    )

    regs = mb.root.findall("register")
    assert [r.get("data-type") for r in regs] == [None, None]
    assert [r.findtext("address") for r in regs] == ["30001", "30002"]


def test_fep_serves_dnp3_points_over_modbus_with_modbus_settings(run_otsim):
    """A point the FEP polls over DNP3 needs a Modbus type and scale to serve."""
    rtu = {
        "hostname": "rtu-1",
        "metadata": {
            "type": "fd-server",
            "dnp3": [{"name": "bus", "type": "bus"}],
            "modbus": [{"name": "brk", "type": "breaker"}],
        },
    }
    md = {
        **APP_MD,
        "infrastructures": {
            "power-distribution": {
                "bus": {
                    "voltage": {
                        "type": "analog-read",
                        "modbus": {"scaling": 3},
                        "dnp3": {"sgvar": "Group30Var6"},
                    }
                },
                "breaker": {
                    "voltage": {
                        "type": "analog-read",
                        "modbus": {"scaling": 2},
                        "dnp3": {"class": "Class1"},
                    }
                },
            }
        },
    }
    fep = {**FEP, "metadata": {**FEP["metadata"], "downstream": ["dnp3", "modbus"]}}
    app = run_otsim(NODES, [rtu, fep], md)

    root = config_xml(app, "fep-1")
    server = root.find("modbus[@mode='server']")
    bus = server.find("register[tag='bus.voltage']")
    assert bus.get("type") == "input"
    assert bus.get("data-type") == "int32"
    assert bus.findtext("scaling") == "-3"
    assert _registers(root, "server", "10.20.0.21:502") == [
        ("input", "int32", 30001, "bus.voltage"),
        *[(t, d, a + 2 if t == "input" else a, n) for t, d, a, n in BREAKER],
    ]

    # The DNP3 outstation gets each point's DNP3 settings, not its Modbus ones.
    outstation = root.find("dnp3[@mode='server']/outstation")
    assert outstation.findtext("input[tag='bus.voltage']/sgvar") == "Group30Var6"
    assert outstation.findtext("input[tag='brk.voltage']/class") == "Class1"


@pytest.mark.parametrize("proto", ["modbus", "dnp3"])
def test_a_null_protocol_setting_is_no_setting(proto):
    """YAML `modbus:` with every setting commented out is null."""
    var_type = {"type": "analog-read", proto: None}

    assert Register("analog-read", "x", var_type=var_type).for_protocol(proto).md == (
        {"data-type": "int32"} if proto == "modbus" else {}
    )
