"""The credentials between Malcolm and the network sensors of the fleet
(docs/multisite/PLANS.md 4.6 in the topology repository).

A site's experiment has Malcolm (the head office) or a sensor (any other
site), never both, so the app renders none of these files for a site alone.
The experiment of the whole fleet does not exist yet. The tests here put the
sensor node of another site into the head office's experiment to get one with
both, and compare what the app renders with what the first-boot scripts of the
topology read (phenix-injects/malcolm/cm-malcolm-provision and
phenix-injects/sensor/cm-sensor-provision).
"""

from __future__ import annotations

import datetime
import re
import stat
from pathlib import Path
from typing import Any, Final

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID

from phenix_apps.apps.cherrymountain import credentials, render
from phenix_apps.apps.cherrymountain.app import CherryMountain
from phenix_apps.apps.cherrymountain.render import Context, Injection
from phenix_apps.apps.cherrymountain.tests.conftest import ROOT, RunApp
from phenix_apps.apps.cherrymountain.tests.test_full import env
from phenix_apps.apps.cherrymountain.tests.test_sites import site_experiment

MALCOLM: Final[str] = "fr-malcolm"
SENSORS: Final[list[str]] = ["cs-sensor", "ep-sensor"]
SCRIPTS: Final[dict[str, Path]] = {
    "malcolm": ROOT / "phenix-injects" / "malcolm" / "cm-malcolm-provision",
    "sensor": ROOT / "phenix-injects" / "sensor" / "cm-sensor-provision",
}
#: What the app renders only when Malcolm and a sensor are in one experiment.
LINK_FILES: Final[tuple[str, ...]] = ("sensors.json", "sensor-tls")


def site_node(code: str, hostname: str) -> dict[str, Any]:
    topology: Any = yaml.safe_load(
        (ROOT / "phenix-configs" / f"topology-site-{code}.yml").read_text("utf-8")
    )
    return next(
        node
        for node in topology["spec"]["nodes"]
        if node["general"]["hostname"] == hostname
    )


def context(run_app: RunApp, code: str, base_dir: Path) -> Context:
    app: CherryMountain = run_app("configure", exp=site_experiment(code, base_dir))
    assert app.config is not None
    assert app.sources is not None
    return app._context(app.config, app.sources)


@pytest.fixture
def fleet(run_app: RunApp, tmp_path: Path) -> Context:
    """The head office with the sensors of two other sites."""
    ctx: Context = context(run_app, "fr", tmp_path / "exp")
    for name in SENSORS:
        ctx.nodes[name] = site_node(name.split("-")[0], name)
    return ctx


def by_dst(injects: list[Injection]) -> dict[str, Injection]:
    assert len({i.dst for i in injects}) == len(injects)
    return {i.dst: i for i in injects}


def certificate(text: str) -> x509.Certificate:
    return x509.load_pem_x509_certificate(text.encode("ascii"))


def private_key(text: str) -> rsa.RSAPrivateKey:
    key: Any = serialization.load_pem_private_key(text.encode("ascii"), password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


# ------------------------------------------------------------ one site alone


@pytest.mark.parametrize("code", ["fr", "ep", "cs", "fc"])
def test_a_site_alone_gets_none_of_it(
    code: str, run_app: RunApp, tmp_path: Path
) -> None:
    """Malcolm then opens no port for a sensor, and a sensor stays idle."""
    ctx: Context = context(run_app, code, tmp_path / "exp")
    assert render.sensor_link(ctx) is None
    assert render.render_sensors(ctx) == {}
    plan: dict[str, list[Injection]] = render.render_all(ctx)
    destinations: set[str] = {i.dst for injects in plan.values() for i in injects}
    assert render.SENSOR_CREDENTIALS not in destinations
    assert not any(dst.startswith(render.SENSOR_TLS) for dst in destinations)
    for name in LINK_FILES:
        assert not (ctx.out_dir / name).exists()
    if code == "fr":
        inject = by_dst(plan[MALCOLM])[render.MALCOLM_CREDENTIALS]
        assert set(env(Path(inject.src))) == {"MALCOLM_ADMIN_PASSWORD"}


def test_the_sites_have_the_nodes_that_the_tests_name() -> None:
    assert render.MALCOLM_PROVISION in {
        i["dst"] for i in site_node("fr", MALCOLM)["injections"]
    }
    for name in SENSORS:
        assert render.SENSOR_PROVISION in {
            i["dst"] for i in site_node(name.split("-")[0], name)["injections"]
        }


# ------------------------------------------------------------ both in one


def test_malcolm_and_each_sensor_get_the_same_two_values(fleet: Context) -> None:
    malcolm = by_dst(render.render_malcolm(fleet)[MALCOLM])
    sensors = render.render_sensors(fleet)
    assert sorted(sensors) == SENSORS
    at_malcolm: dict[str, str] = env(Path(malcolm[render.MALCOLM_CREDENTIALS].src))
    assert set(at_malcolm) == {
        "MALCOLM_ADMIN_PASSWORD",
        "CM_SENSOR_PASSWORD",
        "CM_ARKIME_SECRET",
    }
    shared: dict[str, str] = {
        key: at_malcolm[key] for key in ("CM_SENSOR_PASSWORD", "CM_ARKIME_SECRET")
    }
    for name in SENSORS:
        inject = by_dst(sensors[name])[render.SENSOR_CREDENTIALS]
        assert inject.permissions == "0600"
        assert stat.S_IMODE(Path(inject.src).stat().st_mode) == 0o600
        assert env(Path(inject.src)) == shared
    # Three different values: no account's password is another's.
    assert len(set(at_malcolm.values())) == 3


def test_the_values_are_ones_that_both_scripts_take(fleet: Context) -> None:
    """Each script tests the two values with a pattern before it uses them."""
    values: dict[str, str] = env(
        Path(
            by_dst(render.render_malcolm(fleet)[MALCOLM])[
                render.MALCOLM_CREDENTIALS
            ].src
        )
    )
    for script in SCRIPTS.values():
        text: str = script.read_text(encoding="utf-8")
        for key in ("CM_SENSOR_PASSWORD", "CM_ARKIME_SECRET"):
            patterns: list[str] = re.findall(
                r"=~ (\^\[A-Za-z0-9\]\{\d+,\d+\}\$) \]\][^\n]*\n?[^\n]*" + key, text
            )
            assert len(patterns) == 1, (script.name, key)
            assert re.fullmatch(patterns[0], values[key]), (script.name, key)


def test_the_files_go_where_the_scripts_read_them(fleet: Context) -> None:
    malcolm = by_dst(render.render_malcolm(fleet)[MALCOLM])
    assert set(malcolm) == {render.MALCOLM_CREDENTIALS} | {
        f"{render.SENSOR_TLS}/{name}" for name in credentials.SENSOR_TLS_FILES
    }
    for name, injects in render.render_sensors(fleet).items():
        assert set(by_dst(injects)) == {render.SENSOR_CREDENTIALS} | {
            f"{render.SENSOR_TLS}/{file}" for file in render.SENSOR_TLS_AT_SENSOR
        }, name
    text: dict[str, str] = {
        kind: script.read_text(encoding="utf-8") for kind, script in SCRIPTS.items()
    }
    for kind in SCRIPTS:
        assert f":-{render.SENSOR_TLS}}}" in text[kind]
    assert render.MALCOLM_CREDENTIALS in text["malcolm"]
    unit: str = (SCRIPTS["sensor"].parent / "cm-sensor-provision.service").read_text(
        encoding="utf-8"
    )
    assert f"EnvironmentFile=-{render.SENSOR_CREDENTIALS}\n" in unit
    # Each side names every file that it gets, and a sensor no file of the
    # server's.
    for name in credentials.SENSOR_TLS_FILES:
        assert name in text["malcolm"]
    for name in render.SENSOR_TLS_AT_SENSOR:
        assert name in text["sensor"]
    assert "server.key" not in render.SENSOR_TLS_AT_SENSOR


def test_no_sensor_gets_the_key_of_the_server_or_of_the_ca(fleet: Context) -> None:
    link = render.sensor_link(fleet)
    assert link is not None
    assert "ca.key" not in link.certificates
    held: set[str] = {link.certificates["server.key"]} | {
        (fleet.out_dir / "sensor-tls" / "ca.key").read_text(encoding="utf-8")
    }
    injects: list[Injection] = [
        i for items in render.render_sensors(fleet).values() for i in items
    ] + render.render_malcolm(fleet)[MALCOLM]
    for inject in injects:
        text: str = Path(inject.src).read_text(encoding="utf-8")
        allowed: bool = inject.dst == f"{render.SENSOR_TLS}/server.key"
        assert (text in held) == allowed, inject.dst
        assert inject.permissions == "0600"
        assert stat.S_IMODE(Path(inject.src).stat().st_mode) == 0o600


def test_the_certificates_are_of_one_ca_and_the_keys_fit(fleet: Context) -> None:
    link = render.sensor_link(fleet)
    assert link is not None
    files: dict[str, str] = link.certificates
    assert tuple(files) == credentials.SENSOR_TLS_FILES
    ca: x509.Certificate = certificate(files["ca.crt"])
    ca.verify_directly_issued_by(ca)
    constraints = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert constraints.ca
    now: datetime.datetime = datetime.datetime.now(datetime.UTC)
    for unit in ("server", "client"):
        leaf: x509.Certificate = certificate(files[f"{unit}.crt"])
        leaf.verify_directly_issued_by(ca)
        assert not leaf.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value.ca
        # As Malcolm's own: Logstash asks for a client certificate, and
        # Filebeat checks the server's against the CA.
        usage = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        assert set(usage) == {
            ExtendedKeyUsageOID.SERVER_AUTH,
            ExtendedKeyUsageOID.CLIENT_AUTH,
        }
        assert leaf.not_valid_before_utc < now < leaf.not_valid_after_utc
        # PKCS #8, not PKCS #1: the Beats input of Logstash reads no other.
        assert files[f"{unit}.key"].startswith("-----BEGIN PRIVATE KEY-----\n")
        key: rsa.RSAPrivateKey = private_key(files[f"{unit}.key"])
        assert key.key_size == credentials.SENSOR_TLS_KEY_BITS
        assert leaf.public_key() == key.public_key()
    assert (
        certificate(files["server.crt"]).subject
        != certificate(files["client.crt"]).subject
    )


def test_a_restart_renders_the_same_values_and_files(fleet: Context) -> None:
    first = render.sensor_link(fleet)
    assert first is not None
    for name in ("sensors.json", "sensor-tls/ca.key", "sensor-tls/server.key"):
        assert stat.S_IMODE((fleet.out_dir / name).stat().st_mode) == 0o600
    assert render.sensor_link(fleet) == first


def test_an_incomplete_set_of_certificates_is_made_again(tmp_path: Path) -> None:
    store: Path = tmp_path / "sensor-tls"
    first: dict[str, str] = credentials.sensor_certificates(store)
    (store / "client.key").unlink()
    again: dict[str, str] = credentials.sensor_certificates(store)
    assert set(again) == set(first)
    assert all(again[name] != first[name] for name in first)
    certificate(again["client.crt"]).verify_directly_issued_by(
        certificate(again["ca.crt"])
    )


def test_render_all_carries_the_sensors_files(fleet: Context) -> None:
    """A sensor is no host of the app's block. Its node gets the files as
    Malcolm's does: by the script that the topology injects."""
    assert not set(SENSORS) & set(fleet.hosts)
    plan: dict[str, list[Injection]] = render.render_all(fleet)
    for name in SENSORS:
        assert render.SENSOR_CREDENTIALS in by_dst(plan[name])
    assert f"{render.SENSOR_TLS}/server.key" in by_dst(plan[MALCOLM])
