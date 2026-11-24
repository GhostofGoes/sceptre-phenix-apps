"""The topology checkout the other tests in this directory run on.

This is the one module collected without a checkout, so that the run reports
why the rest did not run.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from phenix_apps.apps.cherrymountain.sources import LFS_POINTER
from phenix_apps.apps.cherrymountain.tests.conftest import ROOT


def test_the_checkout_has_its_git_lfs_files() -> None:
    """The program ZIPs are Git LFS files. A checkout without them holds
    pointers, and every pre-start test then fails on a PLC it cannot render."""
    program: Path = ROOT / "phenix-injects" / "openplc" / "plc-cellar.zip"
    assert program.is_file(), f"{program} is missing"
    assert not program.read_bytes().startswith(LFS_POINTER), (
        f"{program} is a Git LFS pointer: run `git lfs pull` in the topology checkout"
    )
    assert zipfile.is_zipfile(program)
