"""An fd-server with a `bacnet` section is a BACnet/IP server and a HELICS federate."""

import copy
import re
from pathlib import Path

import pytest
import yaml

from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node
from phenix_apps.common.error import AppError

NODES = [
    topo_node("sim", "10.20.0.5"),
    topo_node("bas-vent", "10.30.10.22"),
    topo_node("rtu-1", "10.20.0.11"),
    topo_node("fep-1", "10.20.0.21"),
    topo_node("hmi-1", "10.20.0.31"),
]

VENT = {
    "co2_ppm": {
        "type": "analog-read",
        "bacnet": {"units": "partsPerMillion", "description": "Cellar CO2"},
    },
    "fan_status": "binary-read",
    "exhaust_pct": {
        "type": "analog-read-write",
        "bacnet": {"units": "percent", "min": 0, "max": 100},
    },
    "fan": "binary-read-write",
    "setpoint_ppm": {
        "type": "analog-read-write",
        "bacnet": {"object-type": "analog-value", "units": "partsPerMillion"},
    },
    "tier": {"type": "binary-read", "bacnet": {"object-type": "binary-value"}},
    "mode": {
        "type": "analog-read-write",
        "bacnet": {
            "object-type": "multi-state-value",
            "states": ["occupied", "unoccupied", "standby"],
        },
    },
}

APP_MD = {
    "infrastructure": "building",
    "infrastructures": {"building": {"vent": VENT}},
    "helics": {"broker": {"address": "10.20.0.5"}, "federate": "building"},
}


def bas(bacnet=None, **extra):
    section = {
        "instance": 3003,
        "devices": [{"name": "bas-vent", "type": "vent"}],
        **(bacnet or {}),
    }
    return {
        "hostname": "bas-vent",
        "metadata": {"type": "fd-server", "bacnet": section, **extra},
    }


def app_md(**variables):
    """APP_MD with variables of the vent type replaced."""
    md = copy.deepcopy(APP_MD)
    md["infrastructures"]["building"]["vent"].update(variables)
    return md


def objects(root):
    return [
        (obj.get("type"), int(obj.get("instance")), obj.get("name"), obj.get("tag"))
        for obj in root.findall("bacnet/object")
    ]


def test_bacnet_server_is_rendered_with_its_objects(run_otsim):
    app = run_otsim(NODES, [bas()], APP_MD)
    root = config_xml(app, "bas-vent")

    (bacnet,) = root.findall("bacnet")
    assert bacnet.attrib == {"name": "bacnet-server", "mode": "server"}
    # the node's own address with its prefix, and the BACnet/IP port
    assert bacnet.findtext("endpoint") == "10.30.10.22/24:47808"
    assert bacnet.find("device").attrib == {"instance": "3003", "name": "bas-vent"}
    assert bacnet.find("stale-after") is None

    # one object per variable, numbered from 1 within its object type
    assert objects(root) == [
        ("analog-input", 1, "bas-vent.co2_ppm", "bas-vent.co2_ppm"),
        ("binary-input", 1, "bas-vent.fan_status", "bas-vent.fan_status"),
        ("analog-output", 1, "bas-vent.exhaust_pct", "bas-vent.exhaust_pct"),
        ("binary-output", 1, "bas-vent.fan", "bas-vent.fan"),
        ("analog-value", 1, "bas-vent.setpoint_ppm", "bas-vent.setpoint_ppm"),
        ("binary-value", 1, "bas-vent.tier", "bas-vent.tier"),
        ("multi-state-value", 1, "bas-vent.mode", "bas-vent.mode"),
    ]


def test_object_attributes_follow_the_variable(run_otsim):
    root = config_xml(run_otsim(NODES, [bas()], APP_MD), "bas-vent")
    by_tag = {o.get("tag"): o for o in root.findall("bacnet/object")}

    co2 = by_tag["bas-vent.co2_ppm"]
    assert co2.get("units") == "partsPerMillion"
    assert co2.get("description") == "Cellar CO2"
    assert co2.get("commandable") is None

    exhaust = by_tag["bas-vent.exhaust_pct"]
    assert (exhaust.get("min"), exhaust.get("max")) == ("0", "100")
    assert exhaust.get("commandable") == "true"

    # an output is commandable, and so is a value object of a writable variable
    assert by_tag["bas-vent.fan"].get("commandable") == "true"
    assert by_tag["bas-vent.setpoint_ppm"].get("commandable") == "true"
    assert by_tag["bas-vent.tier"].get("commandable") is None

    mode = by_tag["bas-vent.mode"]
    assert [s.text for s in mode.findall("state")] == [
        "occupied",
        "unoccupied",
        "standby",
    ]


def test_bacnet_only_host_gets_its_io_module_and_helics_annotation(run_otsim):
    app = run_otsim(NODES, [bas()], APP_MD)
    root = config_xml(app, "bas-vent")

    modules = {m.get("name"): m.text for m in root.findall("cpu/module")}
    assert modules["i/o"] == "ot-sim-io-module {{config_file}}"
    assert modules["bacnet"] == "ot-sim-bacnet-module {{config_file}}"

    io = root.find("io")
    assert io.findtext("broker-endpoint") == "10.20.0.5"
    subs = {(s.findtext("key"), s.findtext("type")) for s in io.findall("subscription")}
    assert ("building/bas-vent.co2_ppm", "double") in subs
    assert ("building/bas-vent.fan", "boolean") in subs
    assert len(subs) == len(VENT)
    # writable variables are sent to the federate's endpoint
    (endpoint,) = io.findall("endpoint")
    assert endpoint.get("name") == "building/updates"
    assert sorted(t.text for t in endpoint.findall("tag")) == [
        "bas-vent.exhaust_pct",
        "bas-vent.fan",
        "bas-vent.mode",
        "bas-vent.setpoint_ppm",
    ]

    node = app.extract_node("bas-vent")
    assert node.annotations["helics/federate"] == [
        {"broker": "10.20.0.5", "fed-count": 1}
    ]


def test_host_settings(run_otsim):
    host = bas(
        {
            "interface": "eth0:47809",
            "name": "BAS-VENT-1",
            "stale-after": 45,
            "module": "/opt/venv/bin/python /usr/local/lib/bacnet.py {{config_file}}",
        }
    )
    root = config_xml(run_otsim(NODES, [host], APP_MD), "bas-vent")

    bacnet = root.find("bacnet")
    assert bacnet.findtext("endpoint") == "10.30.10.22/24:47809"
    assert bacnet.find("device").attrib == {"instance": "3003", "name": "BAS-VENT-1"}
    assert bacnet.findtext("stale-after") == "45"
    modules = {m.get("name"): m.text for m in root.findall("cpu/module")}
    assert modules["bacnet"] == (
        "/opt/venv/bin/python /usr/local/lib/bacnet.py {{config_file}}"
    )


def test_per_device_objects_override_the_variable_settings(run_otsim):
    host = bas(
        {
            "devices": [
                {
                    "name": "building/bas-vent",
                    "type": "vent",
                    "objects": {
                        "co2_ppm": {
                            "name": "FAC.VENT.AT01.PV",
                            "description": "Cellar CO2 sensor 1",
                            "instance": 7,
                        },
                        "exhaust_pct": {"max": 80},
                    },
                },
                {"name": "building/bas-vent-2", "type": "vent"},
            ]
        }
    )
    root = config_xml(run_otsim(NODES, [host], APP_MD), "bas-vent")
    by_tag = {o.get("tag"): o for o in root.findall("bacnet/object")}

    co2 = by_tag["bas-vent.co2_ppm"]
    assert co2.get("name") == "FAC.VENT.AT01.PV"
    assert co2.get("description") == "Cellar CO2 sensor 1"
    assert co2.get("instance") == "7"
    assert co2.get("units") == "partsPerMillion"  # kept from the variable
    assert by_tag["bas-vent.exhaust_pct"].get("max") == "80"
    assert by_tag["bas-vent.exhaust_pct"].get("min") == "0"

    # the second device's objects take the free instances: 7 is taken, 1 is not
    assert by_tag["bas-vent-2.co2_ppm"].get("instance") == "1"
    assert by_tag["bas-vent-2.exhaust_pct"].get("instance") == "2"

    # the I/O module is rendered as if `objects` were not there
    keys = {s.findtext("key") for s in root.findall("io/subscription")}
    assert "building/bas-vent.co2_ppm" in keys
    assert "building/bas-vent-2.co2_ppm" in keys


def test_a_host_can_serve_bacnet_next_to_modbus(run_otsim):
    host = bas(modbus=[{"name": "bas-vent", "type": "vent"}])
    root = config_xml(run_otsim(NODES, [host], APP_MD), "bas-vent")

    assert root.find("modbus") is not None
    assert root.find("bacnet") is not None
    # one subscription per variable, not one per protocol
    assert len(root.findall("io/subscription")) == len(VENT)
    names = [m.get("name") for m in root.findall("cpu/module")]
    assert {"modbus", "bacnet", "i/o"} <= set(names)


FEP = {
    "hostname": "fep-1",
    "metadata": {"type": "fep", "upstream": ["bas-vent"], "downstream": ["dnp3"]},
}
HMI = {
    "hostname": "hmi-1",
    "metadata": {"type": "fd-client", "connected_rtus": ["bas-vent"]},
}


@pytest.mark.parametrize(
    ("poller", "kind"), [(FEP, "fep 'fep-1'"), (HMI, "fd-client 'hmi-1'")]
)
def test_a_bacnet_only_device_cannot_be_polled(run_otsim, poller, kind):
    with pytest.raises(AppError) as err:
        run_otsim(NODES, [bas(), poller], APP_MD)

    assert str(err.value) == (
        f"ot-sim: {kind} polls 'bas-vent', which serves only bacnet; OT-sim has no "
        "client for it, so give 'bas-vent' a modbus or dnp3 section too or remove "
        f"it from '{poller['hostname']}'"
    )


def test_a_fep_polls_the_other_protocols_of_a_bacnet_device(run_otsim):
    host = bas(modbus=[{"name": "bas-vent", "type": "vent"}])
    root = config_xml(run_otsim(NODES, [host, FEP], APP_MD), "fep-1")

    (client,) = root.findall("modbus[@mode='client']")
    assert client.findtext("endpoint") == "10.30.10.22:502"
    assert root.find("bacnet") is None
    # every point is served downstream once
    outstation = root.find("dnp3[@mode='server']/outstation")
    assert len(outstation.findall("input") + outstation.findall("output")) == len(VENT)


BAD_HOSTS = [
    (
        {"instance": None},
        "ot-sim: fd-server 'bas-vent' bacnet.instance must be an integer from 0 to "
        "4194302",
    ),
    (
        {"instance": "3003"},
        "ot-sim: fd-server 'bas-vent' bacnet.instance must be an integer from 0 to "
        "4194302",
    ),
    (
        {"instance": 4194303},
        "ot-sim: fd-server 'bas-vent' bacnet.instance must be an integer from 0 to "
        "4194302",
    ),
    (
        {"devices": []},
        "ot-sim: fd-server 'bas-vent' bacnet.devices must be a non-empty list",
    ),
    (
        {"devices": [{"name": "bas-vent", "type": "chiller"}]},
        "ot-sim: fd-server 'bas-vent' bacnet device 'bas-vent' has type 'chiller', "
        "which infrastructure 'building' does not define",
    ),
    (
        {"devices": [{"name": "bas-vent", "type": "vent", "objects": {"co2": {}}}]},
        "ot-sim: fd-server 'bas-vent' bacnet device 'bas-vent' sets objects for "
        "'co2'; type 'vent' has co2_ppm, fan_status, exhaust_pct, fan, setpoint_ppm, "
        "tier, mode",
    ),
    (
        {"stale-after": -1},
        "ot-sim: fd-server 'bas-vent' bacnet.stale-after must be a number of "
        "seconds, 0 or more",
    ),
    (
        {"interface": "10.99.0.1"},
        "ot-sim: fd-server 'bas-vent' has no topology interface with address "
        "10.99.0.1; its BACnet endpoint needs that interface's prefix to hear "
        "broadcasts, so set bacnet.interface to an interface name or to one of the "
        "node's addresses",
    ),
]


@pytest.mark.parametrize(("section", "message"), BAD_HOSTS)
def test_bad_host_settings_fail_naming_the_host(run_otsim, section, message):
    with pytest.raises(AppError) as err:
        run_otsim(NODES, [bas(section)], APP_MD)

    assert str(err.value) == message


def test_bacnet_needs_an_instance(run_otsim):
    host = bas()
    del host["metadata"]["bacnet"]["instance"]

    with pytest.raises(AppError) as err:
        run_otsim(NODES, [host], APP_MD)

    assert str(err.value) == (
        "ot-sim: fd-server 'bas-vent' sets bacnet without `instance`, the instance "
        "of its BACnet Device object"
    )


def test_bacnet_has_no_list_form(run_otsim):
    host = bas()
    host["metadata"]["bacnet"] = [{"name": "bas-vent", "type": "vent"}]

    with pytest.raises(AppError) as err:
        run_otsim(NODES, [host], APP_MD)

    assert str(err.value) == (
        "ot-sim: fd-server 'bas-vent' bacnet must be a map with `instance` and "
        "`devices`; it has no list form"
    )


OBJ = "ot-sim: fd-server 'bas-vent' BACnet object for 'bas-vent."
BAD_VARIABLES = [
    (
        {"co2_ppm": {"type": "analog-read", "bacnet": {"object-type": "binary-input"}}},
        f"{OBJ}co2_ppm' sets object-type 'binary-input'; a variable of type "
        "'analog-read' is served as one of analog-input, analog-output, "
        "analog-value, multi-state-value",
    ),
    (
        {
            "co2_ppm": {
                "type": "analog-read",
                "bacnet": {"object-type": "analog-output"},
            }
        },
        f"{OBJ}co2_ppm' is an output object, but the variable is 'analog-read': "
        "nothing would receive a command to it",
    ),
    (
        {
            "fan": {
                "type": "binary-read-write",
                "bacnet": {"object-type": "binary-input"},
            }
        },
        f"{OBJ}fan' is an input object, which cannot be written, but the variable "
        "is 'binary-read-write'; use an output or value object",
    ),
    (
        {"tier": {"type": "binary-read", "bacnet": {"commandable": True}}},
        f"{OBJ}tier' is commandable, but the variable is 'binary-read': nothing "
        "would receive a command to it",
    ),
    (
        {"fan": {"type": "binary-read-write", "bacnet": {"commandable": False}}},
        f"{OBJ}fan' is an output object, so it is commandable",
    ),
    (
        {"fan": {"type": "binary-read-write", "bacnet": {"commandable": "yes"}}},
        f"{OBJ}fan' commandable must be true or false",
    ),
    (
        {"fan": {"type": "binary-read-write", "bacnet": {"units": "percent"}}},
        f"{OBJ}fan' sets units, which only analog objects have",
    ),
    (
        {"exhaust_pct": {"type": "analog-read-write", "bacnet": {"min": 5, "max": 1}}},
        f"{OBJ}exhaust_pct' min is greater than max",
    ),
    (
        {"exhaust_pct": {"type": "analog-read-write", "bacnet": {"max": "100"}}},
        f"{OBJ}exhaust_pct' max must be a number",
    ),
    (
        {
            "mode": {
                "type": "analog-read-write",
                "bacnet": {"object-type": "multi-state-value"},
            }
        },
        f"{OBJ}mode' is a multi-state object, so it needs `states`, a list of "
        "state texts (state 1 first)",
    ),
    (
        {"co2_ppm": {"type": "analog-read", "bacnet": {"states": ["a"]}}},
        f"{OBJ}co2_ppm' sets states, which only a multi-state-value has",
    ),
    (
        {"co2_ppm": {"type": "analog-read", "bacnet": {"instance": -1}}},
        f"{OBJ}co2_ppm' instance must be an integer from 0 to 4194302",
    ),
    (
        {"co2_ppm": {"type": "analog-read", "bacnet": {"name": ""}}},
        f"{OBJ}co2_ppm' name must be a non-empty string",
    ),
    (
        {"co2_ppm": {"type": "counter"}},
        f"{OBJ}co2_ppm': variable type 'counter' has no BACnet object; expected "
        "one of analog-read, analog-read-write, binary-read, binary-read-write",
    ),
]


@pytest.mark.parametrize(("variables", "message"), BAD_VARIABLES)
def test_bad_object_settings_fail_naming_the_tag(run_otsim, variables, message):
    with pytest.raises(AppError) as err:
        run_otsim(NODES, [bas()], app_md(**variables))

    assert str(err.value) == message


def test_two_objects_cannot_share_an_identifier_or_a_name(run_otsim):
    same_instance = app_md(
        co2_ppm={"type": "analog-read", "bacnet": {"instance": 4}},
        fan_status={"type": "analog-read", "bacnet": {"instance": 4}},
    )
    with pytest.raises(AppError) as err:
        run_otsim(NODES, [bas()], same_instance)
    assert str(err.value) == (
        "ot-sim: fd-server 'bas-vent' has two analog-input objects with instance 4 "
        "(second: 'bas-vent.fan_status')"
    )

    same_name = app_md(
        co2_ppm={"type": "analog-read", "bacnet": {"name": "POINT"}},
        fan={"type": "binary-read-write", "bacnet": {"name": "POINT"}},
    )
    with pytest.raises(AppError) as err:
        run_otsim(NODES, [bas()], same_name)
    assert str(err.value) == (
        "ot-sim: fd-server 'bas-vent' names two BACnet objects 'POINT' "
        "('bas-vent.co2_ppm' and 'bas-vent.fan')"
    )


def test_an_unknown_key_warns_and_is_not_rendered(run_otsim, mocker):
    warning = mocker.patch("phenix_apps.apps.otsim.protocols.bacnet.logger.warning")
    variables = {"co2_ppm": {"type": "analog-read", "bacnet": {"unit": "ppm"}}}

    root = config_xml(
        run_otsim(NODES, [bas({"device-id": 1})], app_md(**variables)), "bas-vent"
    )

    messages = [call.args[0] for call in warning.call_args_list]
    assert (
        "ot-sim: fd-server 'bas-vent' sets unknown bacnet key 'device-id'" in messages
    )
    assert (
        "ot-sim: fd-server 'bas-vent' BACnet object for 'bas-vent.co2_ppm' sets "
        "unknown bacnet key 'unit'"
    ) in messages
    (co2,) = [
        o for o in root.findall("bacnet/object") if o.get("tag").endswith("co2_ppm")
    ]
    assert co2.get("unit") is None
    assert co2.get("units") is None


def test_the_readme_example_renders(run_otsim):
    """The BACnet example of the README is a config the app accepts."""
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    section = readme.split("\n# BACnet\n", 1)[1].split("\n# ", 1)[0]
    (block,) = re.findall(r"```yaml\n(.*?)```", section, re.DOTALL)
    example = yaml.safe_load(block)

    nodes = [topo_node("sim", "10.20.0.5"), topo_node("bas-vent", "10.30.10.22", "IF0")]
    root = config_xml(
        run_otsim(nodes, example["hosts"], example["metadata"]), "bas-vent"
    )

    assert root.findtext("bacnet/endpoint") == "10.30.10.22/24:47808"
    assert root.find("bacnet/device").attrib == {
        "instance": "3003",
        "name": "BAS-VENT-1",
    }
    assert objects(root) == [
        ("analog-input", 1, "FAC.VENT.AT01.PV", "bas-vent.co2_ppm"),
        ("binary-input", 1, "bas-vent.fan_status", "bas-vent.fan_status"),
        ("analog-output", 1, "bas-vent.exhaust_pct", "bas-vent.exhaust_pct"),
        ("analog-value", 1, "bas-vent.setpoint_ppm", "bas-vent.setpoint_ppm"),
        ("multi-state-value", 1, "bas-vent.mode", "bas-vent.mode"),
    ]
