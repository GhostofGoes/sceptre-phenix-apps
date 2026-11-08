import io
import json

import pytest

from phenix_apps.schedulers.single_node.scheduler import SingleNode


def _node(hostname: str) -> dict:
    return {"type": "VirtualMachine", "general": {"hostname": hostname}}


def _run(monkeypatch, experiment):
    monkeypatch.setattr("sys.argv", ["phenix-scheduler-single-node"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(experiment)))
    SingleNode()


def test_schedules_every_unscheduled_vm_on_the_first_host(monkeypatch, capsys):
    experiment = {
        "spec": {
            "topology": {"nodes": [_node("s1"), _node("s2"), _node("s3")]},
            "schedules": {"s3": "pinned"},
        },
        "hosts": [{"name": "compute1"}, {"name": "compute2"}],
        "x-unknown": "kept",
    }

    _run(monkeypatch, experiment)

    out = json.loads(capsys.readouterr().out)

    assert out["spec"]["schedules"] == {
        "s1": "compute1",
        "s2": "compute1",
        "s3": "pinned",
    }
    assert out["x-unknown"] == "kept"


def test_external_nodes_are_not_scheduled(monkeypatch, capsys):
    hw = {**_node("plc-hw"), "external": True}
    experiment = {
        "spec": {"topology": {"nodes": [_node("vm1"), hw]}, "schedules": {}},
        "hosts": [{"name": "compute1"}],
    }

    _run(monkeypatch, experiment)

    assert json.loads(capsys.readouterr().out)["spec"]["schedules"] == {
        "vm1": "compute1"
    }


@pytest.mark.parametrize("hosts", [[], None])
def test_no_cluster_hosts_fails_naming_the_scheduler(monkeypatch, capsys, hosts):
    experiment = {
        "spec": {"topology": {"nodes": [_node("vm1")]}, "schedules": {}},
        "hosts": hosts,
    }

    with pytest.raises(ValueError, match=r"single-node scheduler: .* no cluster hosts"):
        _run(monkeypatch, experiment)

    assert capsys.readouterr().out == ""
