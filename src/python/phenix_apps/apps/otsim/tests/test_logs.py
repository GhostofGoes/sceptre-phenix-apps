"""A host's `logs` settings combine with the app's into one CPU `<logs>`."""

import pytest

from phenix_apps.apps.otsim.tests.conftest import config_xml, topo_node

NODES = [topo_node("rtu-1", "10.20.0.11")]
BROKER = {"helics": {"broker": {"address": "10.20.0.5"}}}
ELASTIC = {"logs": {"elastic": {"endpoint": "http://es:9200", "index": "app-logs"}}}


def _rtu(logs):
    md = {"type": "fd-server", "modbus": [{"name": "bus", "type": "bus"}]}
    return {"hostname": "rtu-1", "metadata": {**md, "logs": logs}}


def _logs(app):
    (logs,) = config_xml(app, "rtu-1").findall("cpu/logs")
    return [(e.tag, e.get("index"), e.text) for e in logs]


@pytest.mark.parametrize(
    ("app_logs", "host_logs", "want"),
    [
        (
            ELASTIC,
            {"loki": "http://loki:3100"},
            [
                ("elastic", "app-logs", "http://es:9200"),
                ("loki", None, "http://loki:3100"),
            ],
        ),
        (
            {},
            {"elastic": {"endpoint": "http://es:9200"}},
            [("elastic", None, "http://es:9200")],
        ),
        (
            {},
            {"elastic": {"endpoint": "http://es:9200"}, "loki": "http://loki:3100"},
            [("elastic", None, "http://es:9200"), ("loki", None, "http://loki:3100")],
        ),
    ],
    ids=["app-elastic-host-loki", "host-elastic-only", "host-elastic-and-loki"],
)
def test_host_logs_combine_with_the_apps(run_otsim, app_logs, host_logs, want):
    app = run_otsim(NODES, [_rtu(host_logs)], {**BROKER, **app_logs})

    assert _logs(app) == want
