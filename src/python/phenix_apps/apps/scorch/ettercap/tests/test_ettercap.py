from unittest import mock

import pytest
from box import Box

from phenix_apps.apps.scorch.ettercap.ettercap import Ettercap


@pytest.fixture
def ettercap():
    component = Ettercap.__new__(Ettercap)
    component.name = "ett"
    component.metadata = Box(
        {"vms": [{"hostname": "g3", "iface": "eth0", "targets": "/10.0.0.1// /"}]}
    )
    component.mm_init = mock.Mock(return_value=mock.Mock())
    return component


def test_start_targets_the_vm_and_clears_the_filter(ettercap):
    ettercap.start()

    assert ettercap.mm_init.return_value.method_calls == [
        mock.call.cc_filter("name=g3"),
        mock.call.cc_exec("ip link set eth0 up"),
        mock.call.cc_background("ettercap -Tq -i eth0 -M arp /10.0.0.1// /"),
        mock.call.clear_cc_filter(),
    ]


def test_stop_targets_the_vm_and_clears_the_filter(ettercap):
    ettercap.stop()

    assert ettercap.mm_init.return_value.method_calls == [
        mock.call.cc_filter("name=g3"),
        mock.call.cc_exec("pkill ettercap"),
        mock.call.clear_cc_filter(),
    ]
