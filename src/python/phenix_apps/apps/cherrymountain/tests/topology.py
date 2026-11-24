"""Where the tests find the CherryMountain Brewery topology directory.

The app reads plant.yaml, the plantgen output, the program ZIPs, and the
injects from the ``cherrymountain-brewery`` directory of
sceptre-phenix-topologies (``sourceDir`` in a range), which is not part of this
repository. The tests run the app on a checkout of it:

* ``CHERRYMOUNTAIN_TOPOLOGY_DIR`` names the directory, or
* a ``sceptre-phenix-topologies`` checkout next to this repository is used.

Without either, the tests that need the directory are skipped.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

ENV: Final[str] = "CHERRYMOUNTAIN_TOPOLOGY_DIR"
#: What a skipped test reports.
MISSING: Final[str] = (
    f"needs the CherryMountain Brewery topology: set {ENV} to the "
    "cherrymountain-brewery directory of a sceptre-phenix-topologies checkout "
    "(with its Git LFS files), or put that checkout next to this repository"
)
#: How far above this file the directory that holds this repository's checkout
#: is: tests, cherrymountain, apps, phenix_apps, python, src, the repository.
_LEVELS_TO_REPOSITORY_PARENT: Final[int] = 7


def _is_topology(path: Path) -> bool:
    return (path / "plant" / "plant.yaml").is_file()


def find() -> Path | None:
    """The topology directory, or None when there is no checkout to use.

    A directory the environment names must be the topology: a wrong value
    fails instead of skipping the tests it was set to run."""
    named: str | None = os.environ.get(ENV)
    if named:
        path: Path = Path(named).resolve()
        if not _is_topology(path):
            raise FileNotFoundError(
                f"{ENV}={named} is not a cherrymountain-brewery directory: "
                "it has no plant/plant.yaml"
            )
        return path
    # An installed copy of the package can sit less deep than a checkout.
    parents = Path(__file__).resolve().parents
    if len(parents) <= _LEVELS_TO_REPOSITORY_PARENT:
        return None
    sibling: Path = (
        parents[_LEVELS_TO_REPOSITORY_PARENT]
        / "sceptre-phenix-topologies"
        / "cherrymountain-brewery"
    )
    return sibling if _is_topology(sibling) else None
