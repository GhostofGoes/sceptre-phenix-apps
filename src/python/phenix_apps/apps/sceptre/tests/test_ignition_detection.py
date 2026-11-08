"""An Ignition host, by label or by metadata.type, delays providers and RTUs."""

from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.sceptre.tests.conftest import run_both_stages

INPUT_FILE = Path(__file__).parent / "test_sceptre_input.yaml"

RTU_RESTART = "bennu-field-deviced --c restart"


def _start_scripts(monkeypatch, tmp_path, ignition_metadata):
    exp = Box.from_yaml(INPUT_FILE.read_text())
    exp.spec.baseDir = str(tmp_path / "exp")
    if ignition_metadata is not None:
        exp.spec.scenario.apps[0].hosts.append(
            {"hostname": "ignition", "metadata": ignition_metadata}
        )
        exp.spec.topology.nodes.append(
            {
                "general": {"hostname": "ignition"},
                "hardware": {"os_type": "linux"},
                "network": {
                    "interfaces": [
                        {
                            "name": "IF0",
                            "type": "ethernet",
                            "vlan": "scada",
                            "address": "10.1.0.60",
                            "mask": 24,
                        }
                    ]
                },
            }
        )

    app = run_both_stages(monkeypatch, exp)

    startup = Path(app.startup_dir)
    return {
        name: (startup / f"{name}-start.sh").read_text()
        for name in ("rtu-1", "provider-pp")
    }


@pytest.mark.parametrize(
    "ignition", [{"labels": ["ignition"]}, {"type": "ignition"}], ids=["label", "type"]
)
def test_ignition_host_delays_rtus_and_providers(monkeypatch, tmp_path, ignition):
    scripts = _start_scripts(monkeypatch, tmp_path, ignition)

    assert RTU_RESTART in scripts["rtu-1"]
    assert "sleep 60s" in scripts["provider-pp"]


def test_no_ignition_host_no_delay(monkeypatch, tmp_path):
    scripts = _start_scripts(monkeypatch, tmp_path, None)

    assert RTU_RESTART not in scripts["rtu-1"]
    assert "sleep 60s" not in scripts["provider-pp"]
