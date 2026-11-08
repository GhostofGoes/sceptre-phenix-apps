"""The CPU API gets only the TLS files the metadata sets."""

import pytest

from phenix_apps.apps.otsim.tests.conftest import config_xml, injections, topo_node
from phenix_apps.common.error import AppError

NODES = [topo_node("rtu-1", "10.20.0.11"), topo_node("fep-1", "10.20.0.21")]

BROKER = {"helics": {"broker": {"address": "10.20.0.5"}}}

RTU = {
    "hostname": "rtu-1",
    "metadata": {"type": "fd-server", "modbus": [{"name": "bus", "type": "bus"}]},
}

FEP = {"hostname": "fep-1", "metadata": {"type": "fep", "upstream": ["rtu-1"]}}

KEY = ("tls-key", "/phenix/key", "/etc/ot-sim/certs/api.key")
CERT = ("tls-certificate", "/phenix/crt", "/etc/ot-sim/certs/api.crt")
CA = ("ca-certificate", "/phenix/ca", "/etc/ot-sim/certs/api.ca.crt")


def _api(fields, **extra):
    return {"endpoint": "0.0.0.0:9443", **{f: src for f, src, _ in fields}, **extra}


def _assert_tls(app, hostname, fields):
    api = config_xml(app, hostname).find("cpu/api")
    assert api.findtext("endpoint") == "0.0.0.0:9443"
    assert [e.tag for e in api if e.tag != "endpoint"] == [f for f, _, _ in fields]
    for field, _, dst in fields:
        assert api.findtext(field) == dst

    injected = injections(app, hostname)
    assert all(src for src, _ in injected), f"{hostname} injects a null source"
    assert [i for i in injected if i[1].startswith("/etc/ot-sim/certs/")] == [
        (src, dst) for _, src, dst in fields
    ]


@pytest.mark.parametrize(
    "fields",
    [[], [KEY, CERT], [KEY, CERT, CA]],
    ids=["none", "key-and-certificate", "mutual"],
)
def test_app_level_api_adds_only_the_tls_files_it_sets(run_otsim, fields):
    md = {**BROKER, "cpu-module": {"api": _api(fields)}}
    app = run_otsim(NODES, [RTU, FEP], md)

    for hostname in ("rtu-1", "fep-1"):
        _assert_tls(app, hostname, fields)


@pytest.mark.parametrize(
    ("level", "where"), [("app", "the app-level"), ("host", "host 'rtu-1'")]
)
@pytest.mark.parametrize(
    ("fields", "have", "missing"),
    [
        ([KEY], "tls-key", "tls-certificate"),
        ([CERT], "tls-certificate", "tls-key"),
        # A misspelled field is a missing one.
        ([KEY, ("tls-cert", "/phenix/crt", None)], "tls-key", "tls-certificate"),
        # OT-sim uses the CA only for an API it serves over TLS.
        ([CA], "ca-certificate", "tls-key and tls-certificate"),
    ],
    ids=["key-only", "certificate-only", "misspelled-certificate", "ca-only"],
)
def test_half_configured_tls_fails_naming_where(
    run_otsim, level, where, fields, have, missing
):
    """A key without a certificate would serve the API over plain HTTP."""
    api = {"cpu-module": {"api": _api(fields)}}
    if level == "app":
        hosts, md = [RTU], {**BROKER, **api}
    else:
        hosts, md = [{**RTU, "metadata": {**RTU["metadata"], **api}}], BROKER

    with pytest.raises(AppError) as err:
        run_otsim(NODES, hosts, md)

    assert f"{where} cpu-module.api sets {have} without {missing}" in str(err.value)


def test_host_level_api_skips_null_tls_fields(run_otsim):
    api = _api([KEY, CERT], **{"ca-certificate": None})
    rtu = {**RTU, "metadata": {**RTU["metadata"], "cpu-module": {"api": api}}}
    app = run_otsim(NODES, [rtu], BROKER)

    _assert_tls(app, "rtu-1", [KEY, CERT])


@pytest.mark.parametrize(
    "cpu_module",
    [
        {"api": {"endpoint": "0.0.0.0:9600"}},
        {"api": None},
        {"api-endpoint": "0.0.0.0:9600"},
        {},
    ],
    ids=["api", "api-null", "api-endpoint", "empty"],
)
def test_a_host_cpu_module_without_tls_fails_when_the_app_sets_it(
    run_otsim, cpu_module
):
    """A host's cpu-module replaces the app's TLS files too, so it would serve
    the API over plain HTTP."""
    md = {**BROKER, "cpu-module": {"api": _api([KEY, CERT])}}
    rtu = {**RTU, "metadata": {**RTU["metadata"], "cpu-module": cpu_module}}

    with pytest.raises(AppError, match="host 'rtu-1' sets its own cpu-module"):
        run_otsim(NODES, [rtu], md)


@pytest.mark.parametrize(
    ("cpu_module", "fields"),
    [
        ({"api": _api([KEY, CERT])}, [KEY, CERT]),
        ({"api": _api([], **{"tls-key": None, "tls-certificate": None})}, []),
    ],
    ids=["own-tls", "explicit-plain-http"],
)
def test_a_host_cpu_module_can_set_its_own_tls_when_the_app_sets_it(
    run_otsim, cpu_module, fields
):
    md = {**BROKER, "cpu-module": {"api": _api([KEY, CERT, CA])}}
    rtu = {**RTU, "metadata": {**RTU["metadata"], "cpu-module": cpu_module}}

    app = run_otsim(NODES, [rtu], md)

    _assert_tls(app, "rtu-1", fields)


def test_a_host_cpu_module_can_turn_the_api_off_when_the_app_sets_tls(run_otsim):
    md = {**BROKER, "cpu-module": {"api": _api([KEY, CERT])}}
    off = {"cpu-module": {"api-endpoint": None}}
    rtu = {**RTU, "metadata": {**RTU["metadata"], **off}}

    app = run_otsim(NODES, [rtu], md)

    assert config_xml(app, "rtu-1").find("cpu/api") is None
