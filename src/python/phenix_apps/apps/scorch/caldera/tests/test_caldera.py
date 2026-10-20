"""caldera leaves no cc filter in the namespace."""

import json

import pytest

from phenix_apps.apps.scorch.caldera.caldera import Caldera
from phenix_apps.apps.scorch.conftest import scorch_experiment

MODULE = "phenix_apps.apps.scorch.caldera.caldera"
METADATA = {
    "server": "caldera",
    "adversary": "0f4c3c67-845e-49a0-927e-90ed33c044e0",
    "facts": "ed32b9c3-9593-4c33-b0db-e2007315096b",
}


@pytest.fixture
def run(component_args, cc_namespace, mocker, tmp_path):
    mocker.patch(f"{MODULE}.time.sleep")
    mocker.patch("phenix_apps.apps.scorch.app.PHENIX_DIR", str(tmp_path))
    (tmp_path / "images" / "exp").mkdir(parents=True)

    def run():
        component_args(
            scorch_experiment(
                [{"name": "op", "type": "caldera", "metadata": METADATA}],
                [{"start": ["op"]}],
            ),
            "start",
            "op",
        )
        Caldera()

    return run


def test_operation_clears_the_cc_filter(cc_namespace, run):
    cc_namespace.result["stdout"] = json.dumps({"id": "op-1", "state": "finished"})

    run()

    # The new operation, its state and its report.
    assert [(m, f) for m, _, f in cc_namespace.queued] == [
        ("cc_send", "uuid=caldera-uuid"),
        ("cc_exec_once", "uuid=caldera-uuid"),
    ] * 3
    assert cc_namespace.filter is None


def test_failed_api_call_still_clears_the_cc_filter(cc_namespace, run):
    cc_namespace.result = {"exitcode": 1, "stdout": "", "stderr": ""}

    with pytest.raises(RuntimeError, match="new operation"):
        run()

    assert cc_namespace.filter is None
