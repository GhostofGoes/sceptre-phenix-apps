"""One site of the fleet (docs/multisite/PLANS.md in the topology
repository): the app on the files that the generators write for each of the
four sites.

The experiment of a site is built here from the generated workflow, topology
file, and scenario of the checkout (``phenix-site-<code>.yml`` and
``phenix-configs/{topology,scenario}-site-<code>.yml``), with the scenario's
own cherrymountain block, so the tests fail when the generators and the app
stop fitting each other.
"""

from __future__ import annotations

import base64
import copy
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from phenix_apps.apps.cherrymountain import render
from phenix_apps.apps.cherrymountain.app import CherryMountain
from phenix_apps.apps.cherrymountain.metadata import (
    FuxaHost,
    GuacamoleHost,
    HmiHost,
    OpenPlcHost,
    SimCtlHost,
    SimFederateHost,
)
from phenix_apps.apps.cherrymountain.render import Context, Injection
from phenix_apps.apps.cherrymountain.sources import Sources
from phenix_apps.apps.cherrymountain.tests.conftest import ROOT, RunApp, app_block
from phenix_apps.apps.cherrymountain.tests.test_full import ctx as full_ctx  # noqa: F401 - fixture
from phenix_apps.apps.cherrymountain.tests.test_full import env, full  # noqa: F401 - fixture
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger

CODES: Final[list[str]] = ["fr", "ep", "cs", "fc"]
#: What each site has (plant/sites.yaml in the topology repository): its PLCs,
#: its FUXA hosts, and whether it has a jump host, a workstation, and a Wazuh.
PLCS: Final[dict[str, list[str]]] = {
    "fr": ["brewhouse", "cellar", "packaging", "utilities", "power"],
    "ep": ["brewhouse", "cellar", "packaging", "utilities", "power"],
    "cs": ["brewhouse", "cellar", "packaging", "utilities"],
    "fc": ["brewhouse", "cellar", "utilities"],
}
FUXA: Final[dict[str, list[str]]] = {
    "fr": ["scada-fuxa", "bas-fuxa"],
    "ep": ["scada-fuxa", "bas-fuxa"],
    "cs": ["scada-fuxa", "bas-fuxa"],
    "fc": ["scada-fuxa"],
}
JUMP_HOST: Final[set[str]] = {"fr", "ep"}
WORKSTATION: Final[set[str]] = {"fr", "ep", "cs"}
WAZUH: Final[set[str]] = {"fr"}
#: The sites whose own jump host has accounts of the company's staff
#: (plant/sites.yaml, `staff`), with the accounts.
STAFF: Final[dict[str, list[str]]] = {"ep": ["corp-controls", "ep-maint"]}
#: The MGMT network of each site: 172.16.0.0/16 moved by the site's index.
MGMT: Final[dict[str, str]] = {
    "fr": "172.16.",
    "fc": "172.17.",
    "ep": "172.18.",
    "cs": "172.19.",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def site_experiment(code: str, base_dir: Path) -> dict[str, Any]:
    """The experiment that phenix makes of a site's workflow, as JSON data."""
    topology: Any = load(ROOT / "phenix-configs" / f"topology-site-{code}.yml")
    workflow: Any = load(ROOT / f"phenix-site-{code}.yml")["spec"]
    scenario: Any = load(ROOT / "phenix-configs" / f"scenario-site-{code}.yml")
    name: str = topology["metadata"]["name"]
    assert workflow["topology"] == workflow["scenario"] == name
    exp: dict[str, Any] = {
        "apiVersion": "phenix.sandia.gov/v1",
        "kind": "Experiment",
        "metadata": {
            "name": name,
            "annotations": {"topology": name, "scenario": name},
        },
        "spec": {
            "experimentName": name,
            "baseDir": str(base_dir),
            "defaultBridge": workflow["defaultBridge"],
            "topology": {"nodes": topology["spec"]["nodes"]},
            "scenario": {"apps": scenario["spec"]["apps"]},
            "vlans": {
                "aliases": workflow["vlans"],
                "min": workflow["vlanRange"]["min"],
                "max": workflow["vlanRange"]["max"],
            },
            "schedules": {},
            "deployMode": "no-headnode",
            "useGREMesh": False,
        },
        "status": {"startTime": "", "schedules": {}, "apps": {}, "vlans": {}},
    }
    app_block(exp)["metadata"]["sourceDir"] = str(ROOT)
    return exp


@pytest.fixture(params=CODES)
def code(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def site(code: str, tmp_path: Path) -> dict[str, Any]:
    return site_experiment(code, tmp_path / "exp")


@pytest.fixture
def app(run_app: RunApp, site: dict[str, Any]) -> CherryMountain:
    return run_app("configure", exp=site)


@pytest.fixture
def ctx(app: CherryMountain) -> Context:
    assert app.config is not None
    assert app.sources is not None
    return app._context(app.config, app.sources)


@pytest.fixture
def plan(ctx: Context) -> dict[str, list[Injection]]:
    return render.render_all(ctx)


def by_dst(injects: list[Injection]) -> dict[str, Injection]:
    return {inject.dst: inject for inject in injects}


def mgmt(ctx: Context, hostname: str) -> str:
    return ctx.ip(hostname, "mgmt")


# ------------------------------------------------------------ the scenario


def test_the_generated_scenario_names_its_site(code: str, site: dict[str, Any]) -> None:
    """plantgen writes the key, and the scenario has no helics app: the site's
    broker is this app's unit."""
    assert app_block(site)["metadata"] == {
        "variant": code,
        "site": code,
        "sourceDir": str(ROOT),
        **({"wazuh": app_block(site)["metadata"]["wazuh"]} if code in WAZUH else {}),
        **({"staffAccounts": STAFF[code]} if code in STAFF else {}),
    }
    names: list[str] = [a["name"] for a in site["spec"]["scenario"]["apps"]]
    assert names == ["startup", "ot-sim", "cherrymountain", "ntp", "vrouter", "soh"]


# ------------------------------------------------------------ configure


def test_configure_names_the_hosts_of_the_site(code: str, app: CherryMountain) -> None:
    """A key that names a host and was left to its default gets the site's name."""
    config = app.config
    assert config is not None
    assert (config.site, config.variant) == (code, code)
    assert config.sim_ctl.hostname == f"{code}-sim-ctl"
    kiosks = {n: md for n, md in app.hosts_md.items() if isinstance(md, HmiHost)}
    assert kiosks
    assert all(md.fuxa == f"{code}-scada-fuxa" for md in kiosks.values())
    assert all(name.startswith(f"{code}-") for name in app.hosts_md)
    jump = [md for md in app.hosts_md.values() if isinstance(md, GuacamoleHost)]
    assert bool(jump) == (code in JUMP_HOST)
    for md in jump:
        assert [(c.name, c.hostname) for c in md.connections] == [
            ("ews-rdp", f"{code}-ews"),
            ("ews-ssh", f"{code}-ews"),
        ]
    # Only the head office has a Wazuh. A site without one enrolls no agent.
    if code in WAZUH:
        assert config.wazuh is not None
        assert config.wazuh.manager == f"{code}-wazuh"
        assert all(agent.startswith(f"{code}-") for agent in config.wazuh.agents)
    else:
        assert config.wazuh is None


def test_a_site_has_the_hosts_that_sites_yaml_gives_it(
    code: str, app: CherryMountain
) -> None:
    kinds: dict[type, list[str]] = {}
    for name, md in app.hosts_md.items():
        kinds.setdefault(type(md), []).append(name)
    assert kinds[OpenPlcHost] == [f"{code}-plc-{plc}" for plc in PLCS[code]]
    assert kinds[FuxaHost] == [f"{code}-{host}" for host in FUXA[code]]
    assert kinds[SimCtlHost] == [f"{code}-sim-ctl"]
    assert (f"{code}-ews" in app.hosts_md) == (code in WORKSTATION)
    assert (f"{code}-dmz-jump" in app.hosts_md) == (code in JUMP_HOST)


def test_the_sources_of_a_site(code: str, app: CherryMountain) -> None:
    sources = app.sources
    assert sources is not None
    assert sources.site == code
    assert sources.generated == ROOT / "plant" / "generated" / "fleet" / code
    plant: Any = sources.plant()
    # plantgen's own expansion of the site: its hosts, under its names.
    assert plant.site == code
    assert plant.variant == code
    assert set(app.hosts_md) <= set(plant.hosts)
    assert plant.hosts[f"{code}-sim-ctl"].ip("mgmt").startswith(MGMT[code])
    # A site runs the full variant's programs, under their plain names.
    plc: str = f"{code}-plc-cellar"
    assert sources.program_name(plc) == "plc-cellar"
    assert sources.program_zip("plc-cellar") == (
        ROOT / "phenix-injects" / "openplc" / "full" / "plc-cellar.zip"
    )
    assert sources.plc_conf_dir("plc-cellar") == sources.generated / "openplc" / plc
    assert (sources.plc_conf_dir("plc-cellar") / "modbus_master.json").is_file()


# ------------------------------------------------------------ pre-start


def test_every_host_of_a_site_is_rendered(
    code: str, ctx: Context, plan: dict[str, list[Injection]]
) -> None:
    for name, md in ctx.hosts.items():
        if type(md) in render.RENDERERS:
            assert plan.get(name), name
    for host, injects in plan.items():
        assert host.startswith(f"{code}-")
        dsts: list[str] = [i.dst for i in injects]
        assert len(dsts) == len(set(dsts)), (host, "two injections to one destination")
        for inject in injects:
            assert inject.src.is_file(), (host, inject.dst)


def test_the_sim_ctl_of_a_site_gets_the_sites_broker(
    code: str, ctx: Context, plan: dict[str, list[Injection]]
) -> None:
    """One broker for each site (decision D8): the unit, its settings, and the
    hook that starts it, on the site's own sim-ctl and nowhere else."""
    hub: str = f"{code}-sim-ctl"
    got = by_dst(plan[hub])
    settings: dict[str, str] = env(got["/etc/default/cm-helics-broker"].src)
    helics: Any = json.loads(
        (ROOT / "plant" / "generated" / "fleet" / code / "helics.json").read_text()
    )
    assert settings == {
        "CM_BROKER_NAME": hub,
        "CM_BROKER_FEDERATES": str(helics["federate_count"]),
        "CM_BROKER_ADDRESS": mgmt(ctx, hub),
    }
    assert settings["CM_BROKER_ADDRESS"].startswith(MGMT[code])
    # plantgen's helics.json of the site names the same broker.
    assert helics["broker"]["host"] == hub
    assert helics["broker"]["address"] == settings["CM_BROKER_ADDRESS"]
    unit = got["/etc/systemd/system/cm-helics-broker.service"]
    text: str = unit.src.read_text(encoding="utf-8")
    assert (
        "ExecStart=/usr/local/bin/helics_broker --name ${CM_BROKER_NAME} "
        "-f${CM_BROKER_FEDERATES} --ipv4 --local_interface ${CM_BROKER_ADDRESS} "
    ) in text
    assert "EnvironmentFile=/etc/default/cm-helics-broker" in text
    assert "Restart=always" in text
    hook = got["/etc/phenix/startup/55-cm-helics-broker.sh"]
    assert hook.permissions == "0755"
    assert "systemctl enable --now --no-block cm-helics-broker.service" in (
        hook.src.read_text(encoding="utf-8")
    )
    for host, injects in plan.items():
        if host != hub:
            assert not [i.dst for i in injects if "helics-broker" in i.dst], host


def test_the_federates_of_a_site_join_the_sites_broker(
    code: str, ctx: Context, plan: dict[str, list[Injection]]
) -> None:
    broker: str = mgmt(ctx, f"{code}-sim-ctl")
    seen: int = 0
    for name, md in ctx.hosts.items():
        if not isinstance(md, (SimCtlHost, SimFederateHost)):
            continue
        for fed in ctx.federates_of(name, md):
            settings = env(by_dst(plan[name])[f"/etc/default/cm-federate-{fed}"].src)
            assert settings["HELICS_BROKER_ADDRESS"] == broker, (name, fed)
            seen += 1
        if ctx.federates_of(name, md):
            copied = by_dst(plan[name])["/etc/cherrymountain/helics.json"].src
            assert json.loads(copied.read_text())["broker"]["address"] == broker
    assert seen >= 4
    # The annotation, should a helics app ever count it, names the site's host.
    assert render.helics_annotation(ctx, 1) == [
        {"broker": f"{code}-sim-ctl|mgmt", "fed-count": 1}
    ]


def test_the_mgmt_policy_of_a_site_has_the_sites_hub(
    code: str, ctx: Context, plan: dict[str, list[Injection]]
) -> None:
    hub: str = mgmt(ctx, f"{code}-sim-ctl")
    members: dict[str, str] = render.mgmt_members(ctx)
    assert all(address.startswith(MGMT[code]) for address in members.values())
    rules: str = by_dst(plan[f"{code}-sim-process"])[
        "/etc/cherrymountain/nftables-mgmt.nft"
    ].src.read_text(encoding="utf-8")
    assert hub in rules
    for other in set(MGMT.values()) - {MGMT[code]}:
        assert other not in rules


def test_a_plc_of_a_site_runs_the_plain_program_with_the_sites_plugin_configs(
    code: str, ctx: Context, plan: dict[str, list[Injection]]
) -> None:
    for plc in PLCS[code]:
        host: str = f"{code}-plc-{plc}"
        got = by_dst(plan[host])
        program: str = f"plc-{plc}"
        archive = got[f"/opt/cherrymountain/openplc/{program}.zip"]
        assert zipfile.is_zipfile(archive.src)
        assert (
            archive.src.read_bytes()
            == (
                ROOT / "phenix-injects" / "openplc" / "full" / f"{program}.zip"
            ).read_bytes()
        )
        settings = env(got["/etc/default/cm-openplc"].src)
        assert settings["CM_PLC_ZIP"] == f"/opt/cherrymountain/openplc/{program}.zip"
        master = got["/opt/cherrymountain/openplc/conf/modbus_master.json"]
        generated: Path = (
            ROOT / "plant" / "generated" / "fleet" / code / "openplc" / host
        )
        assert (
            master.src.read_bytes() == (generated / "modbus_master.json").read_bytes()
        )


def test_the_fuxa_project_of_a_site_reads_the_sites_devices(
    code: str, ctx: Context, plan: dict[str, list[Injection]]
) -> None:
    """The builder builds the project of ``<code>-scada-fuxa`` from the site's
    tag lists, and the kiosks open that host."""
    scada: str = f"{code}-scada-fuxa"
    got = by_dst(plan[scada])
    project: Path = next(
        i.src for dst, i in got.items() if dst.endswith("project.json")
    )
    doc: Any = json.loads(project.read_text(encoding="utf-8"))
    committed: Path = ROOT / "fuxa" / "fleet" / code / f"{scada}-project.json"
    built: Any = json.loads(committed.read_text(encoding="utf-8"))
    assert sorted(doc["devices"]) == sorted(built["devices"])
    text: str = project.read_text(encoding="utf-8")
    plc_address: str = ctx.ip(f"{code}-plc-cellar", "IF0")
    assert plc_address in text
    if code != "fr":
        # No address of the Front Range plant, which fr keeps.
        assert "10.20.10.12" not in text
    for name, md in ctx.hosts.items():
        if isinstance(md, HmiHost):
            assert render.kiosk_url(ctx, md).startswith(
                f"http://{ctx.ip(scada, md.interface)}:"
            ), name


def test_the_pub_is_one_scada_host_and_no_wazuh(
    run_app: RunApp, tmp_path: Path
) -> None:
    """``fc`` has none of several kinds: no building FUXA, no workstation, no
    jump host, no Wazuh, no packaging and no power PLC. The app renders it."""
    app = run_app("configure", exp=site_experiment("fc", tmp_path / "exp"))
    assert app.config is not None
    assert app.sources is not None
    assert app.config.wazuh is None
    names: set[str] = set(app.hosts_md)
    for absent in (
        "bas-fuxa",
        "ews",
        "dmz-jump",
        "wazuh",
        "plc-packaging",
        "plc-power",
    ):
        assert f"fc-{absent}" not in names
    plan = render.render_all(app._context(app.config, app.sources))
    assert not [
        i.dst for injects in plan.values() for i in injects if "wazuh" in i.dst.lower()
    ]
    # Its one SCADA host has the building's points too.
    assert sorted(p.name for p in (app.sources.generated / "fuxa").iterdir()) == [
        "fc-scada-fuxa-tags.json"
    ]


# ------------------------------------------------------------ the staff accounts

#: The site's copy of the roster, with placeholder values that anyone can read.
COMMITTED_ROSTER: Final[str] = "phenix-injects/fleet/{code}/guacamole/staff.env"


def test_the_staff_accounts_of_a_site_get_credentials_of_the_experiment(
    code: str, ctx: Context, plan: dict[str, list[Injection]]
) -> None:
    """The jump host and the workstation of a site with staff accounts get one
    roster, and no value of it is the committed placeholder."""
    takers: dict[str, Injection] = {
        host: by_dst(injects)[render.STAFF_ENV]
        for host, injects in plan.items()
        if render.STAFF_ENV in by_dst(injects)
    }
    assert list(ctx.app.staff_accounts) == STAFF.get(code, [])
    if code not in STAFF:
        assert takers == {}
        assert not (ctx.out_dir / "staff.json").exists()
        return
    assert set(takers) == {f"{code}-dmz-jump", f"{code}-ews"}
    texts: set[str] = {
        Path(inject.src).read_text(encoding="utf-8") for inject in takers.values()
    }
    assert len(texts) == 1
    for inject in takers.values():
        assert inject.permissions == "0600"
        assert Path(inject.src).stat().st_mode & 0o077 == 0
    values: dict[str, str] = env(Path(takers[f"{code}-ews"].src))
    committed: dict[str, str] = env(ROOT / COMMITTED_ROSTER.format(code=code))
    assert set(values) == set(committed)
    assert values["STAFF_COUNT"] == committed["STAFF_COUNT"] == str(len(STAFF[code]))
    secret: list[str] = []
    for n, account in enumerate(STAFF[code], 1):
        assert values[f"STAFF{n}_USER"] == committed[f"STAFF{n}_USER"] == account
        for key in ("GUAC_PASSWORD", "TOTP_SECRET", "EWS_PASSWORD"):
            value: str = values[f"STAFF{n}_{key}"]
            assert value, (account, key)
            assert value != committed[f"STAFF{n}_{key}"], (account, key)
            secret.append(value)
        assert len(base64.b32decode(values[f"STAFF{n}_TOTP_SECRET"])) == 20
        # A person types the passwords: letters and digits only.
        assert values[f"STAFF{n}_GUAC_PASSWORD"].isalnum()
        assert values[f"STAFF{n}_EWS_PASSWORD"].isalnum()
    assert len(set(secret)) == len(secret)
    # A restart of the experiment renders the same roster.
    again: Injection = by_dst(render.render_staff(ctx)[f"{code}-ews"])[render.STAFF_ENV]
    assert env(Path(again.src)) == values
    assert (ctx.out_dir / "staff.json").stat().st_mode & 0o077 == 0


def test_the_jump_hosts_script_takes_the_roster_that_the_app_renders(
    tmp_path: Path, run_app: RunApp
) -> None:
    """cm-guacamole-start gives the rendered file to cm_staff_sql.py of the
    topology, as here. The SQL names every account and no placeholder."""
    exp = site_experiment("ep", tmp_path / "exp")
    app: CherryMountain = run_app("configure", exp=exp)
    assert app.config is not None
    assert app.sources is not None
    made: dict[str, list[Injection]] = render.render_staff(
        app._context(app.config, app.sources)
    )
    roster = Path(by_dst(made["ep-dmz-jump"])[render.STAFF_ENV].src)
    script: Path = ROOT / "phenix-injects" / "guacamole" / "cm_staff_sql.py"
    done = subprocess.run(
        [sys.executable, "-I", str(script), "--env", str(roster), "--salt", "ab" * 32],
        capture_output=True,
        text=True,
        check=False,
        cwd="/",
    )
    assert done.returncode == 0, done.stderr
    values: dict[str, str] = env(roster)
    for n, account in enumerate(STAFF["ep"], 1):
        assert f"VALUES ('{account}', 'USER') ON CONFLICT DO NOTHING;" in done.stdout
        assert (
            f"'guac-totp-key-secret', '{values[f'STAFF{n}_TOTP_SECRET']}'"
            in done.stdout
        )
        assert f"'password', '{values[f'STAFF{n}_EWS_PASSWORD']}'" in done.stdout
        assert f"ews-rdp-{account}" in done.stdout
        assert f"ews-ssh-{account}" in done.stdout
    assert done.stdout.rstrip().endswith("COMMIT;")


def test_a_roster_with_no_account_or_with_no_node_is_refused(
    run_app: RunApp, tmp_path: Path
) -> None:
    """Without `staffAccounts`, the two nodes would keep the committed
    placeholders. With it and no node that takes the roster, nobody would get
    an account. The app stops at both."""
    exp = site_experiment("ep", tmp_path / "ep")
    del app_block(exp)["metadata"]["staffAccounts"]
    app: CherryMountain = run_app("configure", exp=exp)
    assert app.config is not None
    assert app.sources is not None
    with pytest.raises(render.SourceError) as none:
        render.render_staff(app._context(app.config, app.sources))
    assert "ep-dmz-jump, ep-ews" in str(none.value)
    assert "metadata.staffAccounts names no account" in str(none.value)

    exp = site_experiment("cs", tmp_path / "cs")
    app_block(exp)["metadata"]["staffAccounts"] = ["cs-maint"]
    app = run_app("configure", exp=exp)
    assert app.config is not None
    assert app.sources is not None
    with pytest.raises(render.SourceError) as nobody:
        render.render_staff(app._context(app.config, app.sources))
    assert "names cs-maint, and no node" in str(nobody.value)


@pytest.mark.parametrize(
    ("accounts", "said"),
    [
        (["ep-maint", "ep-maint"], "staffAccounts must not repeat an account"),
        (["ridgeline-akim"], "the prefix of the vendor's technicians"),
        (["Corp Controls"], "metadata.staffAccounts"),
        ([f"staff-{n}" for n in range(9)], "metadata.staffAccounts"),
    ],
    ids=["twice", "a-vendor-name", "not-an-account-name", "too-many"],
)
def test_a_wrong_staff_account_is_reported(
    run_app: RunApp, tmp_path: Path, accounts: list[str], said: str
) -> None:
    exp = site_experiment("ep", tmp_path / "exp")
    app_block(exp)["metadata"]["staffAccounts"] = accounts
    assert said in refused(run_app, exp)


def refused(run_app: RunApp, exp: dict[str, Any]) -> str:
    """Run configure, which must refuse the experiment, and return its report."""
    lines: list[str] = []
    sink: int = logger.add(lambda message: lines.append(str(message)), level="ERROR")
    try:
        with pytest.raises(AppError, match="cherrymountain app check failed"):
            run_app("configure", exp=exp)
    finally:
        logger.remove(sink)
    return "\n".join(lines)


# ------------------------------------------------------------ what does not fit


def test_a_site_scenario_with_the_helics_app_is_refused(
    run_app: RunApp, tmp_path: Path
) -> None:
    """The helics app and this app's unit would both start a broker on the
    site's sim-ctl."""
    exp = site_experiment("fc", tmp_path / "exp")
    exp["spec"]["scenario"]["apps"].append(
        {"name": "helics", "metadata": {"broker": {"root": "fc-sim-ctl|mgmt"}}}
    )
    report: str = refused(run_app, exp)
    assert "metadata.site" in report
    assert "root broker on fc-sim-ctl" in report
    assert "remove the helics app block" in report


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"site": "ep"}, "site is ep and variant is fc"),
        ({"site": "zz", "variant": "zz"}, "plant/sites.yaml has no site zz"),
        ({"site": "FC"}, "metadata.site"),
    ],
    ids=["site-is-not-the-variant", "no-such-site", "not-a-site-code"],
)
def test_a_wrong_site_key_is_reported(
    run_app: RunApp, tmp_path: Path, change: dict[str, str], said: str
) -> None:
    exp = site_experiment("fc", tmp_path / "exp")
    app_block(exp)["metadata"].update(change)
    assert said in refused(run_app, exp)


def test_without_the_site_key_the_files_of_a_site_do_not_fit(
    run_app: RunApp, tmp_path: Path
) -> None:
    """This is what the key is for: the single-site names and directory."""
    exp = site_experiment("fc", tmp_path / "exp")
    del app_block(exp)["metadata"]["site"]
    report: str = refused(run_app, exp)
    assert "metadata.simCtl.hostname" in report
    assert "unknown variant 'fc'" in report


def test_a_name_that_the_scenario_gives_is_kept(
    run_app: RunApp, tmp_path: Path
) -> None:
    exp = site_experiment("ep", tmp_path / "exp")
    block = app_block(exp)
    block["metadata"]["simCtl"] = {"hostname": "ep-sim-ctl", "eventPort": 8081}
    for host in block["hosts"]:
        if host["metadata"]["type"] == "hmi":
            host["metadata"]["fuxa"] = "ep-bas-fuxa"
    app = run_app("configure", exp=exp)
    assert app.config is not None
    assert app.config.sim_ctl.hostname == "ep-sim-ctl"
    assert app.config.sim_ctl.event_port == 8081
    kiosks = [md for md in app.hosts_md.values() if isinstance(md, HmiHost)]
    assert kiosks
    assert all(md.fuxa == "ep-bas-fuxa" for md in kiosks)


# ------------------------------------------------------------ the single site


def test_the_single_site_gets_no_broker_unit(full_ctx: Context) -> None:  # noqa: F811
    """Without the site key nothing changes: the helics app starts the root
    broker, and the names are the single site's."""
    assert full_ctx.app.site is None
    assert full_ctx.app.sim_ctl.hostname == "sim-ctl"
    assert full_ctx.sources.site is None
    assert full_ctx.sources.generated == ROOT / "plant" / "generated" / "full"
    assert full_ctx.sources.program_name("plc-cellar") == "plc-cellar"
    assert full_ctx.sources.plc_conf_dir("plc-cellar") == (
        ROOT / "plant" / "generated" / "full" / "openplc" / "plc-cellar"
    )
    plan = render.render_all(full_ctx)
    assert not [
        i.dst for injects in plan.values() for i in injects if "helics-broker" in i.dst
    ]


def test_sources_of_a_variant_are_as_before() -> None:
    ci = Sources(ROOT, "ci")
    assert ci.generated == ROOT / "plant" / "generated" / "ci"
    assert ci.program_zip("plc-cellar") == (
        ROOT / "phenix-injects" / "openplc" / "plc-cellar.zip"
    )
    lite = Sources(ROOT, "lite")
    assert lite.program_zip("plc-cellar") == (
        ROOT / "phenix-injects" / "openplc" / "lite" / "plc-cellar.zip"
    )


def test_the_unit_check_of_a_site_asks_for_the_broker(
    monkeypatch: pytest.MonkeyPatch, run_app: RunApp, tmp_path: Path
) -> None:
    app = run_app("configure", exp=site_experiment("fc", tmp_path / "exp"))
    assert app.config is not None
    asked: list[str] = []

    def fake(self: CherryMountain, name: str, cmd: str, *args: Any) -> dict[str, Any]:
        asked.append(cmd)
        units: list[str] = cmd.split("systemctl is-active ", 1)[1].split()
        return {"stdout": "\n".join("active" for _ in units), "exitcode": 0}

    monkeypatch.setattr(CherryMountain, "_exec", fake)
    check = app._check_host("fc-sim-ctl", app.hosts_md["fc-sim-ctl"], app.config)
    assert check.state == "provisioned"
    assert "cm-helics-broker.service" in asked[0].split()
    asked.clear()
    app._check_host("fc-sim-process", app.hosts_md["fc-sim-process"], app.config)
    assert "cm-helics-broker.service" not in asked[0].split()


def test_copy_is_not_shared_between_sites(tmp_path: Path) -> None:
    """Two experiments built from one checkout do not share data."""
    first = site_experiment("fc", tmp_path / "a")
    second = copy.deepcopy(site_experiment("fc", tmp_path / "b"))
    app_block(first)["metadata"]["site"] = "ep"
    assert app_block(second)["metadata"]["site"] == "fc"
