from unittest import mock

from box import Box

from phenix_apps.apps.scorch.opcexport import opcexport
from phenix_apps.apps.scorch.opcexport.opcexport import OPCExport


def test_stop_deletes_the_windows_log_with_del(monkeypatch):
    comp = OPCExport.__new__(OPCExport)
    comp.name = "opc"
    comp.metadata = Box({"opc_hostname": "opc"})
    comp.mm = mock.Mock()
    comp.recv_file = mock.Mock()
    monkeypatch.setattr(opcexport.utils, "mm_kill_process", mock.Mock())

    comp.stop()

    assert comp.mm.method_calls == [
        mock.call.cc_filter("name=opc"),
        mock.call.cc_exec_once(mock.ANY),
        mock.call.clear_cc_filter(),
    ]
    command = comp.mm.cc_exec_once.call_args.args[0]
    assert command.startswith("cmd /c del /q c:")
    assert command.endswith("scada_to_elastic.log")
