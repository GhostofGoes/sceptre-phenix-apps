"""An app-level `api-endpoint: null` turns the CPU API off unless a host sets one."""

import pytest

from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node

NODES = [topo_node("rtu-1", "10.20.0.11")]
BROKER = {"helics": {"broker": {"address": "10.20.0.5"}}}
OFF = {**BROKER, "cpu-module": {"api-endpoint": None}}


def _rtu(cpu_module=None):
    md = {"type": "fd-server", "modbus": [{"name": "bus", "type": "bus"}]}
    if cpu_module is not None:
        md["cpu-module"] = cpu_module
    return {"hostname": "rtu-1", "metadata": md}


@pytest.mark.parametrize(
    "cpu_module", [None, {}, {"api-endpoint": None}], ids=["none", "empty", "null"]
)
def test_a_host_without_its_own_endpoint_gets_no_api(run_otsim, cpu_module):
    app = run_otsim(NODES, [_rtu(cpu_module)], OFF)

    assert config_xml(app, "rtu-1").find("cpu/api") is None


@pytest.mark.parametrize(
    ("cpu_module", "endpoint"),
    [
        ({"api-endpoint": "0.0.0.0:9200"}, "0.0.0.0:9200"),
        ({"api": {"endpoint": "0.0.0.0:9443"}}, "0.0.0.0:9443"),
        ({"api": {}}, "0.0.0.0:9101"),
    ],
    ids=["api-endpoint", "api", "api-without-endpoint"],
)
def test_a_host_can_still_turn_its_api_on(run_otsim, cpu_module, endpoint):
    app = run_otsim(NODES, [_rtu(cpu_module)], OFF)

    assert config_xml(app, "rtu-1").findtext("cpu/api/endpoint") == endpoint


@pytest.mark.parametrize(
    ("app_cpu_module", "host_cpu_module", "endpoint"),
    [
        (None, None, "0.0.0.0:9101"),
        ({"api": None}, None, "0.0.0.0:9101"),
        ({"api": {"endpoint": "0.0.0.0:9300"}}, None, "0.0.0.0:9300"),
        ({"api": {"endpoint": "0.0.0.0:9300"}}, {"api": None}, "0.0.0.0:9300"),
    ],
    ids=["app-null", "app-api-null", "host-null", "host-api-null"],
)
def test_a_null_cpu_module_or_api_is_unset(
    run_otsim, app_cpu_module, host_cpu_module, endpoint
):
    """YAML with every key of the section commented out gives a null."""
    rtu = _rtu()
    rtu["metadata"]["cpu-module"] = host_cpu_module
    app = run_otsim(NODES, [rtu], {**BROKER, "cpu-module": app_cpu_module})

    assert config_xml(app, "rtu-1").findtext("cpu/api/endpoint") == endpoint
