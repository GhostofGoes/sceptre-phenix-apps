"""Run the app on the recorded ci experiment (fixtures/experiment-ci.json).

The app reads a checkout of the CherryMountain Brewery topology, which
``topology.py`` finds. Without one, the test modules here are not collected
(some read the checkout when they are imported) and test_topology_checkout.py
reports the skip.
"""

from __future__ import annotations

import copy
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from phenix_apps.apps.cherrymountain.app import CherryMountain
from phenix_apps.apps.cherrymountain.tests import topology

HERE: Path = Path(__file__).resolve().parent
_FOUND: Path | None = topology.find()
#: The cherrymountain-brewery directory: the app reads plant.yaml, the
#: plantgen output, and phenix-injects/ from it, as sourceDir in a range.
#: Without a checkout it is a path that does not exist, and no test runs.
ROOT: Path = _FOUND or HERE / "no-topology-checkout"
if _FOUND is None:
    collect_ignore: list[str] = sorted(
        path.name
        for path in HERE.glob("test_*.py")
        if path.name != "test_topology_checkout.py"
    )
EXPERIMENT: dict[str, Any] = json.loads(
    (HERE / "fixtures" / "experiment-ci.json").read_text()
)


def app_block(exp: dict[str, Any]) -> dict[str, Any]:
    return next(
        a for a in exp["spec"]["scenario"]["apps"] if a["name"] == "cherrymountain"
    )


def app_hosts(app: CherryMountain) -> Any:
    """The hosts of the app's scenario block, as the stage left them."""
    assert app.app is not None
    return app.app.hosts


def node(exp: dict[str, Any], hostname: str) -> dict[str, Any]:
    return next(
        n
        for n in exp["spec"]["topology"]["nodes"]
        if n["general"]["hostname"] == hostname
    )


@pytest.fixture(autouse=True)
def _topology_checkout() -> None:
    if _FOUND is None:
        pytest.skip(topology.MISSING)


@pytest.fixture
def experiment(tmp_path: Path) -> dict[str, Any]:
    """A fresh copy of the ci experiment, rooted at tmp_path."""
    exp: dict[str, Any] = copy.deepcopy(EXPERIMENT)
    exp["spec"]["baseDir"] = str(tmp_path / "exp")
    app_block(exp)["metadata"]["sourceDir"] = str(ROOT)
    return exp


RunApp = Callable[..., CherryMountain]


@pytest.fixture
def run_app(monkeypatch: pytest.MonkeyPatch, experiment: dict[str, Any]) -> RunApp:
    """Build the app from the experiment on stdin and run one stage."""

    def run(
        stage: str, exp: dict[str, Any] | None = None, dryrun: bool = False
    ) -> CherryMountain:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(exp or experiment)))
        app: CherryMountain = CherryMountain("cherrymountain", stage, dryrun)
        {
            "configure": app.configure,
            "pre-start": app.pre_start,
            "post-start": app.post_start,
            "running": app.running,
            "cleanup": app.cleanup,
        }[stage]()
        return app

    return run
