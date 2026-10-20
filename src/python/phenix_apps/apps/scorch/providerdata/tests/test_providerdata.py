"""providerdata leaves no cc filter in the namespace."""

import pytest

from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.providerdata.providerdata import ProviderData

METADATA = {
    "hostname": "provider",
    "export_config": False,
    "csv_files": {"path": "/root/provider_data"},
}


@pytest.fixture
def run(component_args, cc_namespace, mocker):
    mocker.patch("phenix_apps.apps.scorch.providerdata.providerdata.sleep")
    mocker.patch.object(ProviderData, "ensure_vm_running")

    def run(stage):
        component_args(
            scorch_experiment(
                [{"name": "pd", "type": "providerdata", "metadata": METADATA}],
                [{"configure": ["pd"], "start": ["pd"]}],
            ),
            stage,
            "pd",
        )
        ProviderData()

    return run


def test_start_checks_the_provider_then_clears_the_cc_filter(cc_namespace, run):
    cc_namespace.result["stdout"] = "root 1 pybennu-power-solver"

    run("start")

    assert cc_namespace.queued == [
        ("cc_exec_once", "ps -ef", "uuid=provider-uuid"),
        ("cc_exec_once", "ls -lh /root/provider_data", "uuid=provider-uuid"),
    ]
    assert cc_namespace.filter is None


def test_failed_check_still_clears_the_cc_filter(cc_namespace, run):
    cc_namespace.result = {"exitcode": 1, "stdout": "", "stderr": "no ntpq"}

    with pytest.raises(RuntimeError, match="no ntpq"):
        run("configure")

    assert cc_namespace.filter is None
