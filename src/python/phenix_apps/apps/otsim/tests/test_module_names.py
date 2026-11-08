"""Each client is named after the device it polls, apart from the servers."""

from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node

NODES = [
    topo_node("rtu-1", "10.20.0.11"),
    topo_node("rtu-2", "10.20.0.12"),
    topo_node("fep-1", "10.20.0.21"),
]

APP_MD = {"helics": {"broker": {"address": "10.20.0.5"}}}


def rtu(hostname):
    return {
        "hostname": hostname,
        "metadata": {
            "type": "fd-server",
            "modbus": [{"name": "brk", "type": "breaker"}],
        },
    }


FEP = {
    "hostname": "fep-1",
    "metadata": {
        "type": "fep",
        "upstream": ["rtu-1", "rtu-2"],
        "downstream": ["modbus"],
    },
}


def test_fep_modbus_clients_are_named_apart_from_its_server(run_otsim):
    app = run_otsim(NODES, [rtu("rtu-1"), rtu("rtu-2"), FEP], APP_MD)

    root = config_xml(app, "fep-1")
    clients = {
        m.findtext("endpoint"): m.get("name")
        for m in root.findall("modbus[@mode='client']")
    }
    assert clients == {
        "10.20.0.11:502": "modbus-client-rtu-1",
        "10.20.0.12:502": "modbus-client-rtu-2",
    }
    assert root.find("modbus[@mode='server']").get("name") == "modbus-outstation"


def test_fd_server_keeps_its_modbus_server_name(run_otsim):
    app = run_otsim(NODES, [rtu("rtu-1")], APP_MD)

    names = [m.get("name") for m in config_xml(app, "rtu-1").findall("modbus")]
    assert names == ["modbus-outstation"]


def test_fd_client_clients_are_named_after_the_devices_they_poll(run_otsim):
    dnp3_rtu = {
        "hostname": "rtu-2",
        "metadata": {"type": "fd-server", "dnp3": [{"name": "bus", "type": "bus"}]},
    }
    client = {
        "hostname": "fep-1",
        "metadata": {"type": "fd-client", "connected_rtus": ["rtu-1", "rtu-2"]},
    }
    app = run_otsim(NODES, [rtu("rtu-1"), dnp3_rtu, client], APP_MD)

    root = config_xml(app, "fep-1")
    assert [(e.tag, e.get("name")) for e in root if e.get("mode") == "client"] == [
        ("modbus", "modbus-client-rtu-1"),
        ("dnp3", "dnp3-client-rtu-2"),
    ]


def test_fep_dnp3_clients_are_named_after_the_devices_they_poll(run_otsim):
    dnp3_rtu = {
        "hostname": "rtu-1",
        "metadata": {"type": "fd-server", "dnp3": [{"name": "bus", "type": "bus"}]},
    }
    fep = {"hostname": "fep-1", "metadata": {"type": "fep", "upstream": ["rtu-1"]}}
    app = run_otsim(NODES, [dnp3_rtu, fep], APP_MD)

    root = config_xml(app, "fep-1")
    assert root.find("dnp3[@mode='client']").get("name") == "dnp3-client-rtu-1"
    assert root.find("dnp3[@mode='server']").get("name") == "dnp3-outstation"
