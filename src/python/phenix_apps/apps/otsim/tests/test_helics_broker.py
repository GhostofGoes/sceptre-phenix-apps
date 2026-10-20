"""ot-sim and the helics app must not both write a host's broker script."""

import pytest

from phenix_apps.apps.otsim.tests.conftest import injections, topo_node
from phenix_apps.common.error import AppError

BROKER_SCRIPT = "/etc/phenix/startup/90-helics-broker.sh"

NODES = [topo_node("power", "10.20.0.5"), topo_node("rtu-1", "10.20.0.11")]

RTU = {
    "hostname": "rtu-1",
    "metadata": {"type": "fd-server", "modbus": [{"name": "bus-01", "type": "bus"}]},
}

HELICS_APP = {"name": "helics", "metadata": {"broker": {"root": "power|eth0"}}}


def _metadata(**broker):
    return {"helics": {"broker": {"hostname": "power|eth0", **broker}}}


def test_ot_sim_writes_broker_script_without_helics_app(run_otsim):
    app = run_otsim(NODES, [RTU], _metadata(**{"base-fed-count": 1}))

    scripts = [src for src, dst in injections(app, "power") if dst == BROKER_SCRIPT]
    assert len(scripts) == 1
    assert "helics_broker -f2 --ipv4" in open(scripts[0]).read()


@pytest.mark.parametrize("broker", [{"base-fed-count": 1}, {"dynamic": True}])
def test_broker_script_conflicts_with_helics_app(run_otsim, broker):
    with pytest.raises(AppError, match=r"helics app.*power"):
        run_otsim(NODES, [RTU], _metadata(**broker), extra_apps=[HELICS_APP])


def test_helics_app_owns_broker_without_base_fed_count(run_otsim):
    app = run_otsim(NODES, [RTU], _metadata(), extra_apps=[HELICS_APP])

    assert not [dst for _, dst in injections(app, "power") if dst == BROKER_SCRIPT]
    assert app.extract_node("rtu-1").annotations["helics/federate"] == [
        {"broker": "10.20.0.5", "fed-count": 1}
    ]
