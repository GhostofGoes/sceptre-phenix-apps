import contextlib
import io
import json
import os
import signal
import socket
import sys
import threading
import time
import uuid

import minimega
import pytest
from box import Box
from pydantic import BaseModel

from phenix_apps.apps.scorch import ComponentBase, app
from phenix_apps.apps.scorch.app import (
    FilePath,
    Hostname,
    Interface,
    MetadataBlock,
    StageCanceled,
    Token,
    validate_metadata,
)
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.common import utils


class Meta(BaseModel):
    count: int
    password: str = ""


class Component(ComponentBase):
    metadata_model = Meta

    def __init__(self):
        ComponentBase.__init__(self, "test")

    def configure(self):
        return f"count={self.config.count}"


@pytest.fixture
def run_component(monkeypatch, tmp_path):
    """Build a component the way phenix calls it, with the given metadata."""

    monkeypatch.setenv("PHENIX_FILES_DIR", str(tmp_path))

    def run(
        metadata: object,
        ctype: str | None = "test",
        cls: type[ComponentBase] = Component,
    ) -> ComponentBase:
        experiment = {
            "spec": {
                "experimentName": "exp",
                "baseDir": str(tmp_path),
                "scenario": {
                    "apps": [
                        {
                            "name": "scorch",
                            "metadata": {
                                "components": [
                                    {"name": "c", "type": ctype, "metadata": metadata}
                                ]
                            },
                        }
                    ]
                },
            }
        }
        monkeypatch.setattr(sys, "argv", ["x", "configure", "c", "0", "0", "0"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(experiment)))
        return cls()

    return run


def status(component: ComponentBase) -> dict:
    (path,) = component.base_dir.glob("configure-*.json")
    return json.loads(path.read_text())


def test_valid_metadata_reaches_the_stage(run_component):
    component = run_component({"count": 3})
    component.execute_stage()

    assert status(component)["return"] == "count=3"


def test_invalid_metadata_fails_the_stage_with_a_status_file(run_component):
    component = run_component({"count": "many"})

    with pytest.raises(RuntimeError, match="invalid metadata for component 'c'"):
        component.execute_stage()

    assert "count: Input should be a valid integer" in status(component)["return"]


class LegacyComponent(ComponentBase):
    """An out-of-tree component written before metadata_model existed."""

    def __init__(self):
        ComponentBase.__init__(self, "test")

    @property
    def config(self):
        return "own config"

    def configure(self):
        assert type(self.metadata) is Box
        return f"count={self.metadata.count}"


def test_component_without_a_model_reads_raw_metadata(run_component):
    # nothing is validated, and the base leaves its config property alone
    component = run_component({"count": "many", "typo": 1}, cls=LegacyComponent)
    component.execute_stage()

    assert status(component)["return"] == "count=many"
    assert component.config == "own config"


class Block(MetadataBlock):
    port: int = 1


class Outer(BaseModel):
    flag: bool = True
    blocks: list[Block] = []
    single: Block = Block()


def test_unknown_keys_warn_with_the_full_path_and_a_hint():
    md = {"blocks": [{}, {"prot": 2}], "single": {"other": 1}}
    _, warnings = validate_metadata(Outer, md, "c")

    assert warnings == [
        "blocks.1.prot: unknown key, ignored. Fix: remove it (did you mean 'port'?)",
        "single.other: unknown key, ignored. Fix: remove it (known: port)",
    ]


@pytest.mark.parametrize("value", [None, "maybe", "false", 2, [1]])
def test_values_are_typed_strictly(value):
    with pytest.raises(ValueError, match="flag"):
        validate_metadata(Outer, {"flag": value}, "c")


def test_numeric_strings_are_not_coerced():
    with pytest.raises(ValueError, match="port"):
        validate_metadata(Outer, {"single": {"port": "6"}}, "c")


@pytest.mark.parametrize("metadata", [False, [], 0, ""])
def test_only_missing_metadata_defaults_to_empty(metadata):
    with pytest.raises(ValueError, match="invalid metadata"):
        validate_metadata(Outer, metadata, "c")


def test_omitted_type_defaults_to_the_name(run_component):
    # phenix core treats a component with no type as type == name
    component = run_component({"count": 3}, ctype=None)
    component.name = component.type = "c"

    assert component.extract_metadata() == {"count": 3}


def test_a_traceback_does_not_leak_metadata_values(run_component, capsys):
    component = run_component({"count": "many", "password": "hunter2-secret"})

    with pytest.raises(RuntimeError):
        component.execute_stage()

    assert "hunter2-secret" not in capsys.readouterr().out
    assert "hunter2-secret" not in json.dumps(status(component))


class Fields(BaseModel):
    host: Hostname | None = None
    iface: Interface | None = None
    path: FilePath | None = None
    token: Token | None = None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "rtu-1"),
        ("host", "AD"),
        ("iface", "eth0"),
        ("iface", "ens3.100"),
        ("iface", "br_mgmt"),
        ("path", "/tmp/out.json"),
        ("path", "C:/phenix/results.json"),
        ("path", "relative/dir/file-1.txt"),
        ("token", "--opt=value"),
    ],
)
def test_shared_field_types_accept(field, value):
    validate_metadata(Fields, {field: value}, "c")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "a"),
        ("host", "x" * 64),
        ("host", "-rtu"),
        ("host", "rtu_1"),
        ("host", "123"),
        ("host", "phenix"),
        ("iface", "eth 0"),
        ("iface", "a" * 16),
        ("iface", "eth0:1"),
        ("iface", "../eth0"),
        ("path", "/out.json&whoami"),
        ("path", "C:\\phenix\\out.json"),
        ("path", "/tmp/$(id)"),
        ("path", "/tmp/*.json"),
        ("path", "/tmp/a b"),
        ("token", "rtu#ignored"),
        ("token", "a\\tb"),
    ],
)
def test_shared_field_types_reject(field, value):
    with pytest.raises(ValueError, match=field):
        validate_metadata(Fields, {field: value}, "c")


def test_stage_the_component_does_not_implement_skips_metadata(run_component):
    component = run_component({"count": "many"})
    component.stage = "cleanup"

    component.execute_stage()  # Component has no cleanup(), so no error

    assert component.config is None


# How a SCORCH component's stage ends when phenix sends it SIGTERM.
class _Waits(ComponentBase):
    """Sets the cc filter, then gets SIGTERM while it waits under it."""

    def __init__(self):
        ComponentBase.__init__(self, "waits")
        self.finished = False
        self.execute_stage()

    def _wait(self):
        with utils.mm_cc_filtered(self.mm, "uuid=vm-1"):
            os.kill(os.getpid(), signal.SIGTERM)
            self.finished = True

    def start(self):
        self._wait()

    def stop(self):
        self._wait()


@pytest.fixture
def mm(mocker):
    fake = mocker.MagicMock(name="mm")
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    return fake


def _run(component_args, stage, background=False):
    component = {"name": "w", "type": "waits", "metadata": {}}
    if background:
        component["background"] = True
    files_dir = component_args(
        scorch_experiment([component], [{"start": ["w"], "stop": ["w"]}]), stage, "w"
    )
    return files_dir / "scorch/run-0/w/loop-0-count-0"


@pytest.mark.parametrize(
    ("stage", "background"),
    [("start", False), ("stop", False), ("stop", True)],
    ids=["foreground-start", "foreground-stop", "background-components-stop"],
)
def test_sigterm_cancels_the_stage_and_runs_its_finally_blocks(
    component_args, mm, mocker, stage, background
):
    out = _run(component_args, stage, background)

    with pytest.raises(RuntimeError, match="stage canceled by signal 15"):
        _Waits()

    assert mm.method_calls == [
        mocker.call.cc_filter("uuid=vm-1"),
        mocker.call.clear_cc_filter(),
    ]
    (status,) = out.glob(f"{stage}-*.json")
    assert "stage canceled by signal 15" in json.loads(status.read_text())["return"]


def test_a_background_start_ignores_sigterm(component_args, mm):
    _run(component_args, "start", background=True)

    component = _Waits()

    assert component.finished


def test_a_background_start_without_a_type_ignores_sigterm(component_args, mm):
    # phenix core defaults an omitted type to the component's name
    component = {"name": "waits", "background": True, "metadata": {}}
    component_args(
        scorch_experiment([component], [{"start": ["waits"]}]), "start", "waits"
    )

    assert _Waits().finished


class _FakeMinimega:
    """A minimega socket that answers each command with ``reply-to:<command>``,
    in order, on every connection, except that with ``silent_first`` it never
    answers on the first connection and sets ``first_command`` once a command
    arrives there."""

    def __init__(self, path, silent_first=False):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen()
        self.silent_first = silent_first
        self.first_command = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        silent = self.silent_first
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(
                target=self._serve, args=(conn, silent), daemon=True
            ).start()
            silent = False

    def _serve(self, conn, silent):
        # The peer may close the connection with a reply still unsent.
        with contextlib.suppress(OSError), conn:
            self._answer(conn, silent)

    def _answer(self, conn, silent):
        decoder, buf = json.JSONDecoder(), ""
        while data := conn.recv(4096):
            buf += data.decode()
            while buf:
                try:
                    msg, end = decoder.raw_decode(buf)
                except ValueError:
                    break
                buf = buf[end:]
                if silent:
                    self.first_command.set()
                    continue
                resp = {"Response": f"reply-to:{msg['Command']}", "Error": ""}
                conn.sendall(
                    (json.dumps({"Resp": [resp], "More": False}) + "\n").encode()
                )


def test_a_cancel_inside_a_request_leaves_later_calls_their_own_replies():
    """The cc filter clear in a finally block must not read the reply to the
    request the cancel interrupted."""
    # An abstract socket: a path below tmp_path can exceed AF_UNIX's limit.
    path = f"\0phenix-apps-test-{uuid.uuid4().hex}"
    server = _FakeMinimega(path)
    mm = minimega.minimega(path, True, False, "exp")
    app._CONNECTIONS.add(mm)

    try:
        # A request whose reply the cancel left unread.
        mm._socket.sendall(
            json.dumps({"Command": "namespace exp cc prefix x"}).encode()
        )

        with pytest.raises(StageCanceled):
            app._cancel_stage(signal.SIGTERM, None)

        (resp,) = mm.clear_cc_filter()
        assert resp["Response"] == "reply-to:namespace exp clear cc filter"
    finally:
        app._CONNECTIONS.discard(mm)
        server.server.close()


def test_a_sigterm_during_a_blocked_minimega_read_cancels_the_stage():
    """A real SIGTERM while the stage waits for minimega's reply must raise
    StageCanceled, not the RuntimeError a reentrant close of the file under
    the interrupted readline raises, and leave a working connection."""
    path = f"\0phenix-apps-test-{uuid.uuid4().hex}"
    server = _FakeMinimega(path, silent_first=True)
    mm = minimega.minimega(path, True, False, "exp")
    # Fails the test, rather than hanging it, if the signal never arrives.
    mm._socket.settimeout(10)
    app._CONNECTIONS.add(mm)

    def cancel():
        server.first_command.wait(10)
        # Let the main thread get into the readline that waits for the reply.
        time.sleep(0.2)
        os.kill(os.getpid(), signal.SIGTERM)

    previous = signal.signal(signal.SIGTERM, app._cancel_stage)
    sender = threading.Thread(target=cancel, daemon=True)
    try:
        sender.start()
        with pytest.raises(StageCanceled):
            mm.cc_prefix("x")

        (resp,) = mm.clear_cc_filter()
        assert resp["Response"] == "reply-to:namespace exp clear cc filter"
    finally:
        sender.join(15)
        signal.signal(signal.SIGTERM, previous)
        app._CONNECTIONS.discard(mm)
        server.server.close()
