"""ettercap leaves no cc filter in the namespace."""

import pytest

from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.ettercap.ettercap import Ettercap
from phenix_apps.common import settings, utils

VMS = [
    {"hostname": "mitm-1", "iface": "eth0", "targets": "/10.0.0.1// /10.0.0.2//"},
    {"hostname": "mitm-2", "iface": "eth1", "targets": "/10.0.0.3//"},
]


def _run(component_args, stage):
    component_args(
        scorch_experiment(
            [{"name": "ett", "type": "ettercap", "metadata": {"vms": VMS}}],
            [{"start": ["ett"], "stop": ["ett"]}],
        ),
        stage,
        "ett",
    )
    Ettercap()


def test_start_runs_ettercap_in_each_vm_then_clears_the_cc_filter(
    component_args, cc_namespace
):
    _run(component_args, "start")

    assert cc_namespace.queued == [
        ("cc_exec_once", "ip link set eth0 up", "name=mitm-1"),
        (
            "cc_background_once",
            "ettercap -Tq -i eth0 -M arp /10.0.0.1// /10.0.0.2//",
            "name=mitm-1",
        ),
        ("cc_exec_once", "ip link set eth1 up", "name=mitm-2"),
        (
            "cc_background_once",
            "ettercap -Tq -i eth1 -M arp /10.0.0.3//",
            "name=mitm-2",
        ),
    ]
    assert cc_namespace.filter is None


def test_stop_kills_ettercap_in_each_vm_then_clears_the_cc_filter(
    component_args, cc_namespace
):
    _run(component_args, "stop")

    assert cc_namespace.queued == [
        ("cc_exec_once", "pkill ettercap", "name=mitm-1"),
        ("cc_exec_once", "pkill ettercap", "name=mitm-2"),
    ]
    assert cc_namespace.filter is None


def test_failed_start_still_clears_the_cc_filter(component_args, cc_namespace):
    cc_namespace.mm.cc_background_once.side_effect = RuntimeError("no client")

    with pytest.raises(RuntimeError, match="no client"):
        _run(component_args, "start")

    assert cc_namespace.filter is None


def test_stop_reaches_every_vm_when_one_has_no_client(
    component_args, cc_namespace, mocker
):
    """mm_cc_once raises for a VM whose miniccc client never registers."""

    def locate(_mm, vm, **_):
        if vm == "mitm-1":
            raise RuntimeError("no cc client for mitm-1")
        return vm, "host"

    mocker.patch.object(utils, "mm_cc_client_locate", side_effect=locate)

    with pytest.raises(RuntimeError, match="could not stop ettercap in mitm-1: no cc"):
        _run(component_args, "stop")

    assert cc_namespace.queued == [("cc_exec_once", "pkill ettercap", "name=mitm-2")]
    assert cc_namespace.filter is None


def test_stop_waits_only_the_teardown_grace_for_a_vm_without_a_client(
    component_args, cc_namespace, unregistered
):
    """phenix gives a canceled run's stop and cleanup stages 4 minutes in all,
    less than the client grace a start waits."""
    unregistered.vms.add("mitm-1")

    with pytest.raises(
        RuntimeError,
        match=f"in mitm-1: timed out after {settings.CC_TEARDOWN_GRACE}s",
    ):
        _run(component_args, "stop")

    assert unregistered.now <= settings.CC_TEARDOWN_GRACE + settings.CC_POLL_RATE
    assert cc_namespace.queued == [("cc_exec_once", "pkill ettercap", "name=mitm-2")]
