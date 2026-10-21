"""DNP3 clients built by ot-sim always get a master block."""

import pytest

from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node

NODES = [
    topo_node("power", "10.20.0.5"),
    topo_node("rtu-1", "10.20.0.11"),
    topo_node("fep-1", "10.20.0.21"),
    topo_node("client-1", "10.20.0.31"),
]

RTU = {
    "hostname": "rtu-1",
    "metadata": {
        "type": "fd-server",
        "dnp3": {
            "interface": "eth0:20001",
            "devices": [{"name": "bus-01", "type": "bus"}],
        },
    },
}

FEP = {
    "hostname": "fep-1",
    "metadata": {"type": "fep", "upstream": ["rtu-1"], "downstream": ["dnp3"]},
}

CLIENT = {
    "hostname": "client-1",
    "metadata": {"type": "fd-client", "connected_rtus": ["fep-1"]},
}

HOST_BROKER = {"helics": {"broker": {"address": "10.20.0.5"}}}


def _master(root, endpoint):
    clients = [
        d
        for d in root.findall("dnp3[@mode='client']")
        if d.findtext("endpoint") == endpoint
    ]
    assert len(clients) == 1, f"no single DNP3 client for {endpoint}"
    master = clients[0].find("master")
    assert master is not None, f"DNP3 client for {endpoint} has no master"
    return master


@pytest.mark.parametrize(
    "metadata",
    [
        {"helics": {"broker": {"address": "10.20.0.5"}}},
        {"helics": {"broker": {"address": "10.20.0.5"}, "scan-rate": 2}},
    ],
    ids=["app-helics", "app-helics-scan-rate"],
)
def test_fd_client_polling_fep_over_dnp3(run_otsim, metadata):
    app = run_otsim(NODES, [RTU, FEP, CLIENT], metadata)

    master = _master(config_xml(app, "client-1"), "10.20.0.21:20000")
    assert master.findtext("local-address") == "1"
    assert master.findtext("remote-address") == "1024"
    # fd-clients use only an explicit scan rate; otherwise ot-sim's default
    expected_rate = metadata["helics"].get("scan-rate")
    assert master.findtext("scan-rate") == (
        None if expected_rate is None else str(expected_rate)
    )
    assert [i.findtext("tag") for i in master.findall("input")] == ["bus-01.voltage"]


def test_fep_without_app_helics_leaves_the_scan_rate_to_ot_sim(run_otsim):
    """With the broker given per host, the app metadata has no `helics` key."""
    rtu = {"hostname": "rtu-1", "metadata": {**RTU["metadata"], **HOST_BROKER}}
    app = run_otsim(NODES, [rtu, FEP, CLIENT])

    fep_master = _master(config_xml(app, "fep-1"), "10.20.0.11:20001")
    assert fep_master.find("scan-rate") is None
    assert [i.findtext("tag") for i in fep_master.findall("input")] == [
        "bus-01.voltage"
    ]

    client_master = _master(config_xml(app, "client-1"), "10.20.0.21:20000")
    assert client_master.find("scan-rate") is None
