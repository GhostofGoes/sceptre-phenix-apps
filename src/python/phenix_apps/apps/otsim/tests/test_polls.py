"""Clients poll the servers a device runs, at the addresses it serves them."""

import pytest

from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node

NODES = [
    topo_node("rtu-1", "10.20.0.11"),
    topo_node("fep-1", "10.20.0.21"),
    topo_node("fep-2", "10.20.0.22"),
    topo_node("client-1", "10.20.0.31"),
]

APP_MD = {"helics": {"broker": {"address": "10.20.0.5"}}}

RTU = {
    "hostname": "rtu-1",
    "metadata": {
        "type": "fd-server",
        "modbus": [{"name": "brk", "type": "breaker"}],
        "dnp3": {
            "interface": "eth0:20001",
            "devices": [{"name": "bus", "type": "bus"}],
        },
    },
}


def fep(hostname, upstream, downstream=None):
    md = {"type": "fep", "upstream": [upstream]}
    if downstream is not None:
        md["downstream"] = downstream
    return {"hostname": hostname, "metadata": md}


def client(polled):
    return {
        "hostname": "client-1",
        "metadata": {"type": "fd-client", "connected_rtus": [polled]},
    }


def _points(block):
    """(kind, type, address) -> (tag, data-type, scaling) for a block's points."""
    elems = (
        block.findall("register") + block.findall("*/input") + block.findall("*/output")
    )
    return {
        (e.tag, e.get("type"), e.findtext("address")): (
            e.findtext("tag"),
            e.get("data-type"),
            e.findtext("scaling"),
        )
        for e in elems
    }


def _opposite(scaling):
    return None if scaling is None else str(-int(scaling))


def _assert_polls_servers(poller, device):
    """Every client block of `poller` polls a server of `device` exactly."""
    polled = set()

    for proto in ("modbus", "dnp3"):
        for conn in poller.findall(f"{proto}[@mode='client']"):
            endpoint = conn.findtext("endpoint")
            servers = [
                s
                for s in device.findall(f"{proto}[@mode='server']")
                if s.findtext("endpoint") == endpoint
            ]
            assert servers, f"polls {proto} at {endpoint}, where no server runs"

            served = _points(servers[0])
            points = _points(conn)
            assert points.keys() == served.keys(), f"{proto} at {endpoint}"

            for where, (tag, data_type, scaling) in points.items():
                want = served[where]
                assert (tag, data_type, scaling) == (
                    want[0],
                    want[1],
                    _opposite(want[2]),
                ), f"{proto} at {endpoint} {where}"

            polled.add(proto)

    return polled


@pytest.mark.parametrize(
    ("downstream", "protocols"),
    [
        (["dnp3", "modbus"], {"dnp3", "modbus"}),
        (["modbus"], {"modbus"}),
        (None, {"dnp3"}),
    ],
    ids=["dnp3-and-modbus", "modbus", "default-dnp3"],
)
def test_fd_client_polls_the_servers_the_fep_runs(run_otsim, downstream, protocols):
    hosts = [RTU, fep("fep-1", "rtu-1", downstream), client("fep-1")]
    app = run_otsim(NODES, hosts, APP_MD)

    polled = _assert_polls_servers(
        config_xml(app, "client-1"), config_xml(app, "fep-1")
    )
    assert polled == protocols


def test_fep_polls_the_servers_an_upstream_fep_runs(run_otsim):
    hosts = [RTU, fep("fep-1", "rtu-1", ["modbus"]), fep("fep-2", "fep-1")]
    app = run_otsim(NODES, hosts, APP_MD)

    polled = _assert_polls_servers(config_xml(app, "fep-2"), config_xml(app, "fep-1"))
    assert polled == {"modbus"}


def test_fd_client_polls_the_servers_an_fd_server_runs(run_otsim):
    app = run_otsim(NODES, [RTU, client("rtu-1")], APP_MD)

    polled = _assert_polls_servers(
        config_xml(app, "client-1"), config_xml(app, "rtu-1")
    )
    assert polled == {"dnp3", "modbus"}


def _server_tags(root, proto):
    (server,) = root.findall(f"{proto}[@mode='server']")
    return sorted(tag for tag, _, _ in _points(server).values())


def test_a_fep_chain_serves_each_point_once(run_otsim):
    """fep-1 serves every point over DNP3 and Modbus, and fep-2 polls both."""
    hosts = [RTU, fep("fep-1", "rtu-1", ["dnp3", "modbus"]), fep("fep-2", "fep-1")]
    app = run_otsim(NODES, hosts, APP_MD)

    fep1, fep2 = config_xml(app, "fep-1"), config_xml(app, "fep-2")
    tags = _server_tags(fep1, "dnp3")
    assert len(tags) == len(set(tags))
    assert _server_tags(fep1, "modbus") == tags
    assert _server_tags(fep2, "dnp3") == tags
