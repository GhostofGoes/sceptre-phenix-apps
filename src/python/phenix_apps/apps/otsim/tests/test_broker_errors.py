"""A missing HELICS broker fails pre-start naming the host and the field."""

import pytest

from phenix_apps.apps.otsim.tests.conftest import topo_node
from phenix_apps.common.error import AppError

NODES = [topo_node("power", "10.20.0.5"), topo_node("rtu-1", "10.20.0.11")]

DEVICES = {"type": "fd-server", "modbus": [{"name": "bus-01", "type": "bus"}]}

APP_LEVEL = (
    r"ot-sim: fd-server 'rtu-1' has modbus or dnp3 devices, so its I/O module "
    r"needs a HELICS broker, but neither its metadata nor the app metadata sets "
    r"helics\.broker\.hostname or helics\.broker\.address"
)


@pytest.mark.parametrize(
    ("host", "app"),
    [
        ({}, None),
        ({}, {"helics": {"federate": "OpenDSS"}}),
        ({"helics": {"federate": "rtu"}}, {"helics": {"broker": {}}}),
    ],
    ids=["no-helics", "app-helics-without-broker", "empty-app-broker"],
)
def test_no_broker_anywhere(run_otsim, host, app):
    rtu = {"hostname": "rtu-1", "metadata": {**DEVICES, **host}}

    with pytest.raises(AppError, match=APP_LEVEL):
        run_otsim(NODES, [rtu], app)


def test_host_broker_without_hostname_or_address(run_otsim):
    md = {**DEVICES, "helics": {"broker": {"log-level": "DEBUG"}}}
    app_md = {"helics": {"broker": {"address": "10.20.0.5"}}}

    with pytest.raises(
        AppError,
        match=r"fd-server 'rtu-1' .* its helics\.broker sets neither hostname nor "
        r"address",
    ):
        run_otsim(NODES, [{"hostname": "rtu-1", "metadata": md}], app_md)


def test_broker_hostname_without_an_addressed_interface(run_otsim):
    app_md = {"helics": {"broker": {"hostname": "power|eth9"}}}

    with pytest.raises(
        AppError,
        match=r"helics\.broker\.hostname 'power\|eth9' names no interface",
    ):
        run_otsim(NODES, [{"hostname": "rtu-1", "metadata": DEVICES}], app_md)
