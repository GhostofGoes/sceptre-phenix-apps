"""Lint the scripts, units, and desktop entry that the app injects unchanged.

* shellcheck, at style level, on the shell scripts of ``templates/scripts``.
  The shebang tells which scripts are shell.
* ``systemd-analyze verify`` on the units of ``templates/systemd``: syntax,
  unknown or deprecated directives, and ordering and dependency mistakes. A
  missing ``ExecStart=`` binary is not a finding, because the binaries exist
  only in the VMs.
* ``systemd-analyze security --offline --threshold`` on the same units: fails
  when the exposure score is above the limit, which keeps the hardening
  directives from being removed.
* ``desktop-file-validate`` on the entries of ``templates/desktop``.

The tests read no topology checkout, so conftest.py runs them without one. The
tools are system packages. Without a tool, its tests are skipped; with ``CI``
set, they fail instead.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final, NoReturn

import pytest

TEMPLATES: Final[Path] = Path(__file__).resolve().parents[1] / "templates"
SCRIPTS: Final[list[Path]] = sorted(
    path for path in (TEMPLATES / "scripts").iterdir() if path.is_file()
)
UNITS: Final[list[Path]] = sorted((TEMPLATES / "systemd").glob("*.service"))
DESKTOP_ENTRIES: Final[list[Path]] = sorted((TEMPLATES / "desktop").glob("*.desktop"))

#: The Debian and Ubuntu package of each tool.
PACKAGES: Final[dict[str, str]] = {
    "shellcheck": "shellcheck",
    "systemd-analyze": "systemd",
    "desktop-file-validate": "desktop-file-utils",
}
#: The shebang interpreters that shellcheck takes.
SHELLS: Final[frozenset[str]] = frozenset({"sh", "bash", "dash", "ksh"})

#: Fail when ``systemd-analyze security`` scores a unit above this (0 safest, 10
#: most exposed). The units here score 1.1 to 1.4.
EXPOSURE_LIMIT: Final[float] = 3.0
#: ``systemd-analyze security --threshold`` needs systemd 250.
_MIN_SECURITY_VERSION: Final[int] = 250
_MISSING_BINARY: Final[re.Pattern[str]] = re.compile(
    r"Command \S+ is not executable: No such file or directory"
)


def _unavailable(reason: str) -> NoReturn:
    """Skip the test, or fail it in CI, where a check must not pass unseen."""
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def _tool(name: str) -> str:
    """The path of a lint tool."""
    path: str | None = shutil.which(name)
    if path is None:
        package: str = PACKAGES[name]
        _unavailable(
            f"{name} not found: install the {package} package "
            f"(sudo apt-get install {package})"
        )
    return path


def _scoring_tool() -> str:
    """The path of a ``systemd-analyze`` that can check an exposure limit."""
    analyze: str = _tool("systemd-analyze")
    out: str = subprocess.run(
        [analyze, "--version"], capture_output=True, text=True, check=True
    ).stdout
    version: int = int(out.split()[1])
    if version < _MIN_SECURITY_VERSION:
        _unavailable(
            f"systemd {version} cannot check the exposure limit: "
            f"it needs systemd {_MIN_SECURITY_VERSION}"
        )
    return analyze


def _interpreter(script: Path) -> str:
    """The program a script's shebang names, or "" without a shebang."""
    with script.open("rb") as file:
        line: bytes = file.readline()
    if not line.startswith(b"#!"):
        return ""
    words: list[str] = line[2:].decode().split()
    if words and Path(words[0]).name == "env":
        words = [word for word in words[1:] if not word.startswith("-")]
    return Path(words[0]).name if words else ""


def _verify(analyze: str, unit: Path) -> list[str]:
    """The ``systemd-analyze verify`` findings, minus missing binaries."""
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        [analyze, "verify", "--man=no", str(unit)],
        capture_output=True,
        text=True,
        check=False,
    )
    # verify exits 1 when it has findings; anything else (a crash, a signal, a
    # usage error) must not read as a clean unit.
    if proc.returncode not in (0, 1):
        return [f"{unit.name}: systemd-analyze verify exited {proc.returncode}"]
    # systemd-analyze also loads every unit on the machine and complains about
    # those (the runner's xfs_scrub and walinuxagent units, for example). Keep
    # only the findings about this unit. It checks a template unit as the
    # instance "i", and names that instance in what is not tied to a line.
    names: tuple[str, str] = (unit.name, unit.name.replace("@.", "@i."))
    lines: list[str] = [
        line.replace(str(unit), unit.name)
        for line in (proc.stdout + proc.stderr).splitlines()
    ]
    return list(
        dict.fromkeys(
            line
            for line in lines
            if line.startswith(names) and not _MISSING_BINARY.search(line)
        )
    )


def _exposure(analyze: str, unit: Path) -> list[str]:
    """The exposure findings, empty when the score is within the limit."""
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        [
            analyze,
            "security",
            "--offline=true",
            "--no-pager",
            # systemd scales 0-10 to 0-100
            f"--threshold={round(EXPOSURE_LIMIT * 10)}",
            str(unit),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return []
    overall: list[str] = [
        line for line in proc.stdout.splitlines() if "Overall exposure" in line
    ]
    return [
        *overall,
        f"{unit.name}: exposure is above {EXPOSURE_LIMIT}; add hardening directives",
    ]


def test_every_script_names_a_known_interpreter() -> None:
    """shellcheck takes the shell scripts. A script with no shebang, or in a
    language no check here knows, would get no check and nobody would see it."""
    assert SCRIPTS, f"no scripts in {TEMPLATES / 'scripts'}"
    unknown: list[str] = [
        f"{script.name}: {_interpreter(script) or 'no shebang'}"
        for script in SCRIPTS
        if _interpreter(script) not in SHELLS
        and not _interpreter(script).startswith("python")
    ]
    assert not unknown, "\n".join(unknown)


def test_shellcheck() -> None:
    shellcheck: str = _tool("shellcheck")
    scripts: list[str] = [
        str(script.relative_to(TEMPLATES))
        for script in SCRIPTS
        if _interpreter(script) in SHELLS
    ]
    assert scripts, f"no shell scripts in {TEMPLATES / 'scripts'}"
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        [shellcheck, "--severity=style", "--exclude=SC1090,SC1091", *scripts],
        cwd=TEMPLATES,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_systemd_analyze_verify() -> None:
    analyze: str = _tool("systemd-analyze")
    assert UNITS, f"no units in {TEMPLATES / 'systemd'}"
    findings: list[str] = [line for unit in UNITS for line in _verify(analyze, unit)]
    assert not findings, "\n".join(findings)


def test_systemd_analyze_exposure() -> None:
    analyze: str = _scoring_tool()
    assert UNITS, f"no units in {TEMPLATES / 'systemd'}"
    findings: list[str] = [line for unit in UNITS for line in _exposure(analyze, unit)]
    assert not findings, "\n".join(findings)


def test_desktop_file_validate() -> None:
    validate: str = _tool("desktop-file-validate")
    assert DESKTOP_ENTRIES, f"no entries in {TEMPLATES / 'desktop'}"
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        [validate, *(str(entry.relative_to(TEMPLATES)) for entry in DESKTOP_ENTRIES)],
        cwd=TEMPLATES,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("name", ["cm-broken.service", "cm-broken@.service"])
def test_verify_finds_the_mistakes_of_a_unit(tmp_path: Path, name: str) -> None:
    """The filter on the unit's name keeps a real finding, of a template unit
    too, and drops only the missing binary."""
    unit: Path = tmp_path / name
    unit.write_text(
        "[Unit]\nDescription=Broken\nRequires=cm-absent.service\n"
        "[Service]\nNoSuchDirective=1\nExecStart=/opt/cm-absent/run\n",
        encoding="utf-8",
    )
    findings: list[str] = _verify(_tool("systemd-analyze"), unit)
    assert len(findings) == 2, findings
    assert f"{name}:5: Unknown key name 'NoSuchDirective'" in findings[0]
    assert "cm-absent.service not found" in findings[1]


def test_exposure_finds_a_unit_without_hardening(tmp_path: Path) -> None:
    unit: Path = tmp_path / "cm-open.service"
    unit.write_text(
        "[Unit]\nDescription=Open\n[Service]\nExecStart=/bin/true\n", encoding="utf-8"
    )
    findings: list[str] = _exposure(_scoring_tool(), unit)
    assert findings[-1] == (
        f"cm-open.service: exposure is above {EXPOSURE_LIMIT}; add hardening directives"
    )
