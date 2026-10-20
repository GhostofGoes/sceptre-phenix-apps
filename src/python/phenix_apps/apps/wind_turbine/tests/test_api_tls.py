"""Every controller config that points the CPU API at TLS files gets them."""

import pytest
from box import Box

from phenix_apps.apps.wind_turbine.app import WindTurbine

pytestmark = pytest.mark.app_class(cls=WindTurbine, name="wind-turbine")

TLS = {
    "endpoint": "0.0.0.0:9443",
    "tls-key": "/phenix/api.key",
    "tls-certificate": "/phenix/api.crt",
}


def _topology(hostname):
    return Box(
        {
            "general": {"hostname": hostname},
            "network": {"interfaces": [{"name": "eth0", "address": "10.0.0.5"}]},
        }
    )


@pytest.fixture
def app(mock_app, tmp_path):
    mock_app.metadata = Box({"cpu-module": {"api": TLS}})
    mock_app.templates = {}
    mock_app.ot_sim_dir = tmp_path
    mock_app.extract_node.side_effect = _topology
    return mock_app


def _node(hostname, typ, **metadata):
    return Box(
        {
            "hostname": hostname,
            "metadata": {"type": typ, **metadata},
            "topology": _topology(hostname),
        }
    )


@pytest.mark.parametrize(
    "build",
    [
        lambda app: app._WindTurbine__main_controller(
            _node("main-1", "main-controller", controllers={"blades": ["blade-1"]}),
            anemo=_node("anemo-1", "anemometer"),
            yaw=_node("yaw-1", "yaw-controller"),
        ),
        lambda app: app._WindTurbine__anemometer(_node("anemo-1", "anemometer")),
        lambda app: app._WindTurbine__yaw_controller(_node("yaw-1", "yaw-controller")),
        lambda app: app._WindTurbine__blade_controller("blade-1"),
    ],
    ids=["main-controller", "anemometer", "yaw-controller", "blade"],
)
def test_controllers_get_the_api_tls_files(app, build):
    build(app)

    injected = [
        (c.kwargs["inject"]["src"], c.kwargs["inject"]["dst"])
        for c in app.add_inject.call_args_list
    ]
    assert ("/phenix/api.key", "/etc/ot-sim/certs/api.key") in injected
    assert ("/phenix/api.crt", "/etc/ot-sim/certs/api.crt") in injected
