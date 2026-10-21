"""rtds leaves no cc filter in the namespace."""

import pytest

from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.rtds.rtds import RTDS

MODULE = "phenix_apps.apps.scorch.rtds.rtds"
METADATA = {
    "hostname": "provider",
    "export_config": False,
    "csv_files": {"path": "/root/rtds_data"},
}
EXEC = "uuid=provider-uuid"


@pytest.fixture
def run(component_args, cc_namespace, mocker):
    mocker.patch(f"{MODULE}.sleep")
    mocker.patch.object(RTDS, "ensure_vm_running")

    def run(stage):
        component_args(
            scorch_experiment(
                [{"name": "rtds", "type": "rtds", "metadata": METADATA}],
                [{"configure": ["rtds"], "start": ["rtds"], "cleanup": ["rtds"]}],
            ),
            stage,
            "rtds",
        )
        RTDS()

    return run


@pytest.mark.parametrize(
    ("stage", "running", "commands"),
    [
        (
            "configure",
            False,
            [
                ("ntpq -p", EXEC),
                ("ps -ef", EXEC),
                ("/usr/local/bin/pybennu-power-solver start -d", EXEC),
            ],
        ),
        ("start", True, [("ps -ef", EXEC), ("ls -lh /root/rtds_data", EXEC)]),
        (
            "cleanup",
            True,
            [
                ("ps -ef", EXEC),
                ("/usr/local/bin/pybennu-power-solver stop", EXEC),
                ("rm -rf /root/rtds_data", EXEC),
                ("rm -f /var/log/bennu-pybennu.out", "name=provider"),
                ("rm -f /var/log/bennu-pybennu.err", "name=provider"),
            ],
        ),
    ],
)
def test_stage_clears_the_cc_filters_it_sets(
    cc_namespace, run, stage, running, commands
):
    if running:
        cc_namespace.result["stdout"] = "root 1 pybennu-power-solver"

    run(stage)

    assert [(c, f) for _, c, f in cc_namespace.queued] == commands
    assert cc_namespace.filter is None


def test_failed_check_still_clears_the_cc_filter(cc_namespace, run):
    cc_namespace.result = {"exitcode": 1, "stdout": "", "stderr": "no ntpq"}

    with pytest.raises(RuntimeError, match="no ntpq"):
        run("configure")

    assert cc_namespace.filter is None
