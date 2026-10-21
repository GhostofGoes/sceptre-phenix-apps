"""A FEP serves its polled points over the downstream protocols it names."""

import pytest

from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node
from phenix_apps.common.error import AppError

NODES = [topo_node("rtu-1", "10.20.0.11"), topo_node("fep-1", "10.20.0.21")]
APP_MD = {"helics": {"broker": {"address": "10.20.0.5"}}}
RTU = {
    "hostname": "rtu-1",
    "metadata": {"type": "fd-server", "modbus": [{"name": "bus", "type": "bus"}]},
}


def _fep(**md):
    return {
        "hostname": "fep-1",
        "metadata": {"type": "fep", "upstream": ["rtu-1"], **md},
    }


@pytest.mark.parametrize(
    ("downstream", "unknown"),
    [("iec104", "'iec104'"), (["dnp3", "DNP3", "bacnet"], "'DNP3', 'bacnet'")],
    ids=["one", "some-of-a-list"],
)
def test_an_unknown_downstream_protocol_names_the_fep_and_the_value(
    run_otsim, downstream, unknown
):
    with pytest.raises(
        AppError,
        match=(
            rf"ot-sim: fep 'fep-1' sets downstream {unknown}, but a fep serves "
            r"only dnp3 and modbus"
        ),
    ):
        run_otsim(NODES, [RTU, _fep(downstream=downstream)], APP_MD)


@pytest.mark.parametrize(
    ("md", "servers"),
    [
        ({}, ["dnp3-outstation"]),
        ({"downstream": None}, ["dnp3-outstation"]),
        ({"downstream": "modbus"}, ["modbus-outstation"]),
        ({"downstream": ["modbus", "dnp3"]}, ["dnp3-outstation", "modbus-outstation"]),
    ],
    ids=["default", "null", "one", "both"],
)
def test_a_fep_serves_the_downstream_protocols_it_names(run_otsim, md, servers):
    app = run_otsim(NODES, [RTU, _fep(**md)], APP_MD)
    xml = config_xml(app, "fep-1")

    served = [
        e.get("name")
        for e in xml
        if e.tag in ("dnp3", "modbus") and e.get("mode") == "server"
    ]
    assert sorted(served) == servers
