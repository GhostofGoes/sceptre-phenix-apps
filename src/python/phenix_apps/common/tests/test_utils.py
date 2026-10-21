import socket
import uuid

import minimega
import pytest

from phenix_apps.common import settings, utils
from phenix_apps.testing.minicli import namespaced_rebuild


class _FakeClock:
    """Simulated clock: ``sleep`` advances time instead of blocking."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _install_fake_clock(monkeypatch) -> _FakeClock:
    """Patch ``utils.time`` with a shared ``_FakeClock`` and return it."""
    clock = _FakeClock()
    monkeypatch.setattr(utils.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(utils.time, "sleep", clock.sleep)

    return clock


class _StubMM:
    """Stand-in for minimega.minimega.

    Effect lists are replayed per call; the last entry sticks so a wait can run
    for hundreds of polls. Rows carrying an ``Error`` raise only while
    ``_raise_errors`` is set.
    """

    def __init__(
        self,
        effects=None,
        client_effects=None,
        vm_info_rows=None,
        cc_commands_rows=None,
        cc_commands_effects=None,
    ):
        self._effects = list(effects or [])
        self._client_effects = list(client_effects or [])
        self._vm_info_rows = vm_info_rows or []
        self._cc_commands_rows = cc_commands_rows or []
        self._cc_commands_effects = (
            list(cc_commands_effects) if cc_commands_effects is not None else None
        )
        self._raise_errors = True
        self.calls = 0
        self.client_calls = 0
        self.vm_info_calls = 0
        self.vm_info_kwargs = None
        self.cc_commands_calls = 0

    def _replay(self, effects):
        # Once down to the last entry, peek instead of popping so it replays
        # indefinitely rather than raising IndexError on the next call.
        effect = effects[0] if len(effects) == 1 else effects.pop(0)

        # An Exception effect models a transport/namespace failure, which the
        # binding raises whether or not per-host errors are being raised.
        if isinstance(effect, Exception):
            raise effect

        if self._raise_errors:
            for row in effect:
                if row.get("Error"):
                    raise minimega.Error(row["Error"])

        return effect

    def cc_exitcode(self, *_args):
        self.calls += 1

        return self._replay(self._effects)

    def cc_clients(self, *_args):
        self.client_calls += 1

        return self._replay(self._client_effects)

    def cc_commands(self, *_args):
        self.cc_commands_calls += 1

        if self._cc_commands_effects is not None:
            return self._replay(self._cc_commands_effects)

        return self._cc_commands_rows

    def vm_info(self, **kwargs):
        self.vm_info_calls += 1
        self.vm_info_kwargs = kwargs

        return self._vm_info_rows


def _vm_info_row(name, uuid, host="gibson1336"):
    """One `vm info summary` per-host row. Columns are read from Header, not
    fixed offsets -- this fixture's default header/column order matches what
    a real minimega instance sends, but a test may pass its own row with a
    different order to prove that."""
    return {
        "Host": host,
        "Header": ["id", "name", "state", "uptime", "uuid"],
        "Tabular": [["0", name, "RUNNING", "1m0s", uuid]],
        "Error": "",
    }


def _clients_row(uuid, hostname, host="gibson1336", header=None):
    """One `cc clients` per-host row, with the tabular row derived from the
    header so a caller can drop columns without misaligning the values."""
    header = header or ["uuid", "hostname", "arch", "os"]
    values = {"uuid": uuid, "hostname": hostname, "arch": "amd64", "os": "linux"}

    return {
        "Host": host,
        "Header": header,
        "Tabular": [[values[col] for col in header]],
        "Error": "",
    }


# Multi-host cc_exitcode fan-out: the sibling host that doesn't run the VM
# reports "no client"; only the VM's host carries the code.
_SIBLING_ONLY = [{"Host": "gibson1337", "Error": "no client foo", "Response": ""}]
_WITH_CODE = [
    {"Host": "gibson1337", "Error": "no client foo", "Response": ""},
    {"Host": "gibson1336", "Error": "", "Response": "0"},
]


def test_mm_cc_all_hosts_suppresses_host_errors_and_restores_the_flag():
    # With _raise_errors set (the binding default) a sibling host's "no client"
    # row aborts the whole call and discards the valid row...
    mm = _StubMM([_WITH_CODE])

    with pytest.raises(minimega.Error):
        mm.cc_exitcode("1", "foo")

    # ...which is precisely what mm_cc_all_hosts exists to suppress.
    mm = _StubMM([_WITH_CODE])

    out = utils.mm_cc_all_hosts(mm, mm.cc_exitcode, "1", "foo")

    assert out == _WITH_CODE  # sibling error row NOT dropped
    assert mm._raise_errors is True  # restored after the call


def test_mm_cc_all_hosts_forwards_kwargs():
    mm = _StubMM(vm_info_rows=[_vm_info_row("foo", "abc-1234")])

    utils.mm_cc_all_hosts(mm, mm.vm_info, summary="summary")

    assert mm.vm_info_kwargs == {"summary": "summary"}


def test_mm_cc_exitcode_wait_picks_host_with_code_ignoring_sibling(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Sibling reports "no client" twice before the VM's host records the code.
    mm = _StubMM([_SIBLING_ONLY, _SIBLING_ONLY, _WITH_CODE])

    row = utils.mm_cc_exitcode_wait(mm, "1", "foo", grace=60.0, poll_rate=0.0)

    assert row["Response"] == "0"
    assert mm.calls == 3


def test_mm_cc_exitcode_wait_transport_error_raises_immediately(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # A transport/namespace error (not a per-host data error) propagates.
    mm = _StubMM([minimega.Error("vm not found: foo")])

    with pytest.raises(minimega.Error):
        utils.mm_cc_exitcode_wait(mm, "1", "foo")

    assert mm.calls == 1


def test_mm_cc_exitcode_wait_grace_exceeded(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # No host ever reports the code (e.g. the client never came back).
    mm = _StubMM([_SIBLING_ONLY] * 5)

    with pytest.raises(RuntimeError):
        utils.mm_cc_exitcode_wait(mm, "1", "foo", grace=0.0, poll_rate=0.0)


def test_mm_cc_exitcode_wait_surfaces_host_errors_in_the_timeout(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # minimega's complaint must survive into the timeout message.
    rows = [{"Host": "gibson1336", "Error": "no such command id 99", "Response": ""}]
    mm = _StubMM([rows])

    with pytest.raises(RuntimeError, match="no such command id 99"):
        utils.mm_cc_exitcode_wait(mm, "99", "foo", grace=0.0, poll_rate=0.0)


def test_mm_command_id_reads_data_field():
    # minimega returns the new command id (an int) in the Data field; it must be
    # stringified to match the string id in `cc commands` tabular output.
    resp = [{"Host": "headnode", "Data": 36, "Error": ""}]

    with pytest.deprecated_call():
        assert utils.mm_command_id(resp) == "36"


# Broadcast: every host creates its own command, so the ids deliberately disagree.
_SPLIT_IDS = [
    {"Host": "gibson1336", "Data": 21, "Error": ""},
    {"Host": "gibson1337", "Data": 20, "Error": ""},
]


def test_mm_command_ids_maps_every_host_to_its_own_id():
    assert utils.mm_command_ids(_SPLIT_IDS) == {"gibson1336": "21", "gibson1337": "20"}


def test_mm_command_id_for_host_picks_the_owning_hosts_id():
    # The client lives on gibson1337, so its id is 20 -- not the 21 that the
    # local/headnode leg reports first and that mm_command_id would return.
    assert utils.mm_command_id_for_host(_SPLIT_IDS, "gibson1337") == "20"
    with pytest.deprecated_call():
        assert utils.mm_command_id(_SPLIT_IDS) == "21"


def test_mm_command_id_for_host_raises_when_that_host_never_created_it():
    # The owning host having no id means the command was created somewhere else
    # entirely (another namespace). Nothing to wait for -- fail immediately.
    with pytest.raises(RuntimeError, match="never created its own copy"):
        utils.mm_command_id_for_host(_SPLIT_IDS, "gibson1338")


def test_mm_command_id_missing_data_raises():
    with pytest.raises(RuntimeError), pytest.deprecated_call():
        utils.mm_command_id([{"Host": "headnode", "Data": None, "Error": ""}])


# cc client returns one per-host response per cluster host; each carries a
# Tabular of registered miniccc clients on that host.
_CLIENTS_EMPTY = [{"Host": "gibson1337", "Header": [], "Tabular": [], "Error": ""}]
_CLIENTS_OTHER = [_clients_row("zzz-9999", "bar", host="gibson1337")]
_CLIENTS_MATCH = [_clients_row("abc-1234", "foo")]
_VM_INFO_FOO = [_vm_info_row("foo", "abc-1234")]


def test_mm_cc_client_locate_found_by_hostname():
    mm = _StubMM(client_effects=[_CLIENTS_MATCH], vm_info_rows=_VM_INFO_FOO)

    assert utils.mm_cc_client_locate(mm, "foo", grace=60.0, poll_rate=0.0) == (
        "abc-1234",
        "gibson1336",
    )
    assert mm.client_calls == 1


def test_mm_cc_client_locate_accepts_a_uuid_with_by_uuid():
    # The name lookup finds nothing (there is no VM called "abc-1234"), which is
    # what tells us the caller handed us a UUID rather than a name.
    mm = _StubMM(client_effects=[_CLIENTS_MATCH], vm_info_rows=_VM_INFO_FOO)

    utils.mm_cc_client_locate(mm, "abc-1234", grace=60.0, poll_rate=0.0, by_uuid=True)

    assert mm.client_calls == 1


# The hostname a miniccc client reports can differ from the minimega VM name,
# e.g. a Windows VM that still has its image's hostname because the startup app
# has not yet renamed it and rebooted.
_CLIENTS_UNRENAMED = [_clients_row("abc-1234", "WIN-3K7Q2M9J1AB")]
_VM_INFO_WIN = [_vm_info_row("win-ws01", "abc-1234")]


def test_mm_cc_client_locate_by_uuid_still_resolves_a_vm_name():
    # by_uuid must still try the name lookup first.
    mm = _StubMM(client_effects=[_CLIENTS_UNRENAMED], vm_info_rows=_VM_INFO_WIN)

    got = utils.mm_cc_client_locate(
        mm, "win-ws01", grace=0.0, poll_rate=0.0, by_uuid=True
    )

    assert got == ("abc-1234", "gibson1336")


def test_mm_cc_client_locate_matches_vm_whose_guest_hostname_differs():
    mm = _StubMM(client_effects=[_CLIENTS_UNRENAMED], vm_info_rows=_VM_INFO_WIN)

    assert utils.mm_cc_client_locate(mm, "win-ws01", grace=0.0, poll_rate=0.0) == (
        "abc-1234",
        "gibson1336",
    )


def test_mm_cc_client_locate_never_matches_on_hostname():
    # A matching hostname with a different uuid is a different VM.
    mm = _StubMM(
        client_effects=[[_clients_row("zzz-9999", "foo")]],
        vm_info_rows=[_vm_info_row("Foo", "abc-1234")],
    )

    with pytest.raises(RuntimeError, match="timed out"):
        utils.mm_cc_client_locate(mm, "Foo", grace=0.0, poll_rate=0.0)


def test_mm_cc_client_locate_unknown_vm_raises_only_after_grace(monkeypatch):
    # One `vm info` miss is a sample, not proof -- retry until grace is up.
    clock = _install_fake_clock(monkeypatch)
    mm = _StubMM(client_effects=[_CLIENTS_MATCH], vm_info_rows=_VM_INFO_FOO)

    with pytest.raises(RuntimeError, match="does not exist"):
        utils.mm_cc_client_locate(mm, "nope", grace=30.0, poll_rate=1.0)

    assert clock.now >= 30.0
    assert mm.vm_info_calls > 1  # retried rather than resolved once up front


def test_mm_cc_client_locate_polls_until_visible(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Two empty rounds (client not yet registered) before it appears.
    mm = _StubMM(
        client_effects=[_CLIENTS_EMPTY, _CLIENTS_OTHER, _CLIENTS_MATCH],
        vm_info_rows=_VM_INFO_FOO,
    )

    utils.mm_cc_client_locate(mm, "foo", grace=60.0, poll_rate=0.0)

    assert mm.client_calls == 3


def test_mm_cc_client_locate_grace_exceeded(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)

    # Client never appears within the grace window.
    mm = _StubMM(client_effects=[_CLIENTS_EMPTY] * 3, vm_info_rows=_VM_INFO_FOO)

    with pytest.raises(RuntimeError, match="timed out"):
        utils.mm_cc_client_locate(mm, "foo", grace=0.0, poll_rate=0.0)


def test_mm_cc_client_locate_ignores_non_matching_clients():
    # Other clients are registered, but ours isn't -- must NOT return.
    mm = _StubMM(client_effects=[_CLIENTS_OTHER], vm_info_rows=_VM_INFO_FOO)

    with pytest.raises(RuntimeError, match="timed out"):
        utils.mm_cc_client_locate(mm, "foo", grace=0.0, poll_rate=0.0)


def test_mm_cc_client_seen_matches_by_uuid():
    # uuid comparison is case-insensitive.
    mm = _StubMM(client_effects=[_CLIENTS_MATCH])

    assert utils.mm_cc_client_seen(mm, "ABC-1234") == "gibson1336"


def test_mm_cc_client_seen_returns_none_when_nothing_matches():
    mm = _StubMM(client_effects=[_CLIENTS_OTHER])

    assert utils.mm_cc_client_seen(mm, "abc-1234") is None


def test_mm_cc_client_seen_returns_the_host_owning_the_uuid():
    # Guest hostnames are not unique; the decoy is listed first.
    mm = _StubMM(
        client_effects=[
            [
                _clients_row("zzz-9999", "foo", host="gibson1336"),
                _clients_row("abc-1234", "foo", host="gibson1337"),
            ]
        ]
    )

    assert utils.mm_cc_client_seen(mm, "abc-1234") == "gibson1337"


def test_mm_cc_client_locate_returns_the_uuid_owner_not_a_hostname_decoy():
    # cc ids are per-host, so the wrong host would wait forever.
    mm = _StubMM(
        client_effects=[
            [
                _clients_row("zzz-9999", "foo", host="gibson1336"),
                _clients_row("abc-1234", "foo", host="gibson1337"),
            ]
        ],
        vm_info_rows=_VM_INFO_FOO,
    )

    assert utils.mm_cc_client_locate(mm, "foo") == ("abc-1234", "gibson1337")


def test_mm_cc_client_seen_tolerates_a_host_row_with_no_header_or_tabular():
    # A host with no cc traffic reports None rather than [].
    mm = _StubMM(
        client_effects=[
            [{"Host": "gibson1337", "Header": None, "Tabular": None, "Error": ""}]
        ]
    )

    assert utils.mm_cc_client_seen(mm, "abc-1234") is None


def test_mm_vm_uuid_tolerates_a_host_with_no_vms():
    # `vm info summary` leaves Tabular null for a host with zero VMs.
    mm = _StubMM(
        vm_info_rows=[
            {"Host": "gibson1337", "Header": [], "Tabular": None, "Error": ""},
            _vm_info_row("foo", "abc-1234"),
        ]
    )

    assert utils.mm_vm_uuid(mm, "foo") == "abc-1234"
    assert utils.mm_vm_uuid(mm, "absent") is None


def test_mm_vm_uuid_reads_columns_from_a_differently_ordered_header():
    # Nothing pins column order -- the code must look up "name"/"uuid" in
    # Header rather than assuming fixed offsets.
    row = {
        "Host": "gibson1336",
        "Header": ["uuid", "id", "name", "state"],
        "Tabular": [["abc-1234", "0", "foo", "RUNNING"]],
        "Error": "",
    }
    mm = _StubMM(vm_info_rows=[row])

    assert utils.mm_vm_uuid(mm, "foo") == "abc-1234"


def test_mm_vm_uuid_returns_none_when_header_lacks_name_or_uuid():
    row = {
        "Host": "gibson1336",
        "Header": ["id", "state"],
        "Tabular": [["0", "RUNNING"]],
        "Error": "",
    }
    mm = _StubMM(vm_info_rows=[row])

    assert utils.mm_vm_uuid(mm, "foo") is None


# `cc commands` header, from minimega cmd/minimega/cc_cli.go (cliCCCommand).
_CC_CMD_HEADER = (
    "id",
    "prefix",
    "command",
    "responses",
    "issued",
    "background",
    "once",
    "sent",
    "received",
    "connectivity",
    "level",
    "filter",
)
# Before minimega 3.3.0 there was no `issued` column.
_CC_CMD_HEADER_LEGACY = tuple(c for c in _CC_CMD_HEADER if c != "issued")


def _cc_cmd_row(host="gibson1336", header=_CC_CMD_HEADER, **cols):
    """One `cc commands` per-host response. Pass any subset of columns by name."""
    values = {"id": "7", "prefix": "", "command": "[whoami]", "responses": "0"}
    values.update(cols)

    return {
        "Host": host,
        "Header": list(header),
        "Tabular": [[values.get(col, "") for col in header]],
        "Error": "",
    }


_CMD_ANSWERED = [
    {"Host": "gibson1337", "Tabular": None, "Error": ""},
    _cc_cmd_row(responses="1"),
]
_CMD_UNANSWERED = [_cc_cmd_row(responses="0")]


def test_mm_wait_for_cmd_returns_once_a_host_reports_a_response():
    # Also covers a sibling host whose Tabular is null.
    mm = _StubMM(cc_commands_rows=_CMD_ANSWERED)

    utils.mm_wait_for_cmd(mm, "7", poll_rate=0.0)


def test_mm_wait_for_cmd_default_is_unbounded(monkeypatch):
    # With no timeout and no client, the wait must never give up on its own.
    clock = _install_fake_clock(monkeypatch)

    mm = _StubMM(cc_commands_effects=[_CMD_UNANSWERED] * 400 + [_CMD_ANSWERED])

    utils.mm_wait_for_cmd(mm, "7")  # no client, no timeout override

    # Pinned exactly: scorch's responsiveness is bounded by the poll interval.
    assert clock.now == 400.0
    assert mm.cc_commands_calls == 401
    assert settings.CC_CMD_GRACE == 0.0


def test_mm_wait_for_cmd_unbounded_with_live_client_waits_past_client_grace(
    monkeypatch,
):
    # A registered client must never cause the unbounded wait to be abandoned.
    clock = _install_fake_clock(monkeypatch)

    mm = _StubMM(
        cc_commands_effects=[_CMD_UNANSWERED] * 400 + [_CMD_ANSWERED],
        client_effects=[_CLIENTS_MATCH],  # visible on every poll
    )

    utils.mm_wait_for_cmd(mm, "7", client="abc-1234")

    assert clock.now > 300.0
    assert mm.cc_commands_calls == 401
    assert mm.client_calls > 0  # liveness was actually polled, not skipped


def test_mm_wait_for_cmd_unbounded_raises_once_client_absence_exceeds_grace(
    monkeypatch,
):
    _install_fake_clock(monkeypatch)

    # An absence outlasting client_grace ends even an unbounded wait.
    mm = _StubMM(
        cc_commands_rows=_CMD_UNANSWERED,
        client_effects=[_CLIENTS_EMPTY],
    )

    with pytest.raises(RuntimeError, match=r"client abc-1234.*cc command 7"):
        utils.mm_wait_for_cmd(mm, "7", client="abc-1234", client_grace=50.0)


def test_mm_wait_for_cmd_tolerates_a_single_missed_liveness_poll(monkeypatch):
    _install_fake_clock(monkeypatch)

    # One missed liveness check is a mesh hiccup, not a dead client.
    mm = _StubMM(
        cc_commands_effects=[_CMD_UNANSWERED] * 25 + [_CMD_ANSWERED],
        client_effects=[_CLIENTS_EMPTY, _CLIENTS_MATCH],
    )

    utils.mm_wait_for_cmd(mm, "7", client="abc-1234", client_grace=15.0)

    assert mm.client_calls >= 2  # both the miss and the recovery were polled


def test_mm_wait_for_cmd_positive_timeout_still_enforces_wall_clock_deadline(
    monkeypatch,
):
    # Passing a positive timeout must still bound the wait in wall-clock time,
    # independent of any client supervision.
    clock = _install_fake_clock(monkeypatch)

    mm = _StubMM(cc_commands_rows=_CMD_UNANSWERED)  # never answers

    with pytest.raises(RuntimeError, match=r"timed out after .*timeout=100"):
        utils.mm_wait_for_cmd(mm, "7", timeout=100.0)

    assert clock.now >= 100.0


# `cc commands` row with a prefix that never accumulates enough responses.
_PREFIX_UNANSWERED = [_cc_cmd_row(id="9", prefix="testing", responses="0")]


def test_mm_wait_for_prefix_is_bounded_by_default(monkeypatch):
    # Unlike mm_wait_for_cmd, a prefix targets a whole filter with no single
    # client to supervise, so it must stay bounded by CC_SEND_GRACE by default.
    clock = _install_fake_clock(monkeypatch)

    mm = _StubMM(cc_commands_rows=_PREFIX_UNANSWERED)

    with pytest.raises(RuntimeError, match=r"timed out after .*timeout=300"):
        utils.mm_wait_for_prefix(mm, "testing", 1)

    assert clock.now >= settings.CC_SEND_GRACE
    assert settings.CC_SEND_GRACE == 300.0


def test_wait_log_due_gates_by_interval_then_doubles_up_to_max(monkeypatch):
    clock = _install_fake_clock(monkeypatch)

    log = utils._WaitLog(interval=5.0, max_interval=100.0)

    assert log.due() is False  # nothing has elapsed yet

    clock.sleep(5.0)
    assert log.due() is True  # fires exactly at the first interval
    assert log.due() is False  # must not immediately re-fire
    assert log.interval == 10.0  # doubled

    clock.sleep(10.0)
    assert log.due() is True
    assert log.interval == 20.0

    clock.sleep(20.0)
    assert log.due() is True
    assert log.interval == 40.0

    clock.sleep(40.0)
    assert log.due() is True
    assert log.interval == 80.0

    clock.sleep(80.0)
    assert log.due() is True
    assert log.interval == 100.0  # saturates: min(160, 100)

    clock.sleep(100.0)
    assert log.due() is True
    assert log.interval == 100.0  # stays saturated


# --- host-scoped cc command identity ------------------------------------
#
# Observed live: the owning host (gibson1337) has our answered command at id 20,
# while the host answering first has an unrelated one at id 21.
_SPLIT_COMMANDS = [
    _cc_cmd_row("gibson1336", id="21", responses="0", sent="[exp/other.sh]"),
    _cc_cmd_row("gibson1337", id="20", responses="1", sent="[exp/ours.sh]"),
]


def test_mm_wait_for_cmd_scoped_to_owning_host_finds_its_id():
    mm = _StubMM(cc_commands_rows=_SPLIT_COMMANDS)

    utils.mm_wait_for_cmd(mm, "20", host="gibson1337", poll_rate=0.0)


def test_mm_wait_for_cmd_ignores_the_same_id_on_another_host(monkeypatch):
    # id 21 exists only on the host that does NOT own the client.
    clock = _install_fake_clock(monkeypatch)
    mm = _StubMM(cc_commands_rows=_SPLIT_COMMANDS)

    with pytest.raises(RuntimeError, match="never appeared on host gibson1337"):
        utils.mm_wait_for_cmd(mm, "21", host="gibson1337", appear_grace=30.0)

    assert clock.now >= 30.0


def test_mm_wait_for_cmd_content_mismatch_counts_as_absent(monkeypatch):
    # Right host, right id, wrong payload: on this host that id belongs to some
    # other command, so ours was never created here.
    clock = _install_fake_clock(monkeypatch)
    mm = _StubMM(cc_commands_rows=_SPLIT_COMMANDS)

    with pytest.raises(RuntimeError, match="never appeared"):
        utils.mm_wait_for_cmd(
            mm,
            "20",
            host="gibson1337",
            match_column="sent",
            match_value="[exp/not-ours.sh]",
            appear_grace=30.0,
        )

    assert clock.now >= 30.0


def test_mm_wait_for_cmd_appearance_is_bounded_but_the_response_is_not(monkeypatch):
    # Once the row appears, appear_grace must not also cap the response wait.
    clock = _install_fake_clock(monkeypatch)
    mm = _StubMM(
        cc_commands_effects=[[_cc_cmd_row("gibson1336", responses="0")]] * 400
        + [[_cc_cmd_row("gibson1336", responses="1")]],
    )

    utils.mm_wait_for_cmd(mm, "7", host="gibson1336", appear_grace=30.0, poll_rate=1.0)

    assert clock.now == 400.0  # far past appear_grace, without raising


def test_mm_wait_for_cmd_without_a_host_keeps_the_legacy_any_host_behaviour():
    # With no host to scope to, the appearance phase is skipped entirely.
    mm = _StubMM(cc_commands_rows=_CMD_ANSWERED)

    utils.mm_wait_for_cmd(mm, "7", poll_rate=0.0)


def test_mm_cc_client_seen_returns_the_owning_host():
    mm = _StubMM(client_effects=[[_clients_row("abc-1234", "foo", host="gibson1337")]])

    assert utils.mm_cc_client_seen(mm, "abc-1234") == "gibson1337"


def test_mm_cc_client_seen_returns_none_when_absent():
    mm = _StubMM(client_effects=[_CLIENTS_OTHER])

    assert utils.mm_cc_client_seen(mm, "abc-1234") is None


def test_mm_cc_client_locate_returns_uuid_and_host():
    mm = _StubMM(
        client_effects=[[_clients_row("abc-1234", "foo", host="gibson1337")]],
        vm_info_rows=[_vm_info_row("foo", "abc-1234")],
    )

    assert utils.mm_cc_client_locate(mm, "foo", grace=0.0, poll_rate=0.0) == (
        "abc-1234",
        "gibson1337",
    )


def test_mm_cc_exitcode_wait_ignores_a_sibling_hosts_answer(monkeypatch):
    # A sibling holding an unrelated command at the same id must never be
    # mistaken for the answer.
    clock = _install_fake_clock(monkeypatch)
    rows = [{"Host": "gibson1336", "Error": "", "Response": "0"}]
    mm = _StubMM([rows])

    with pytest.raises(RuntimeError, match="timed out"):
        utils.mm_cc_exitcode_wait(mm, "20", "foo", grace=5.0, host="gibson1337")

    assert clock.now >= 5.0


def test_mm_wait_for_prefix_sums_responses_across_hosts():
    # num_responses is a namespace-wide expectation while each host counts only
    # the clients it owns, so a per-host comparison can never reach it on a mesh.
    mm = _StubMM(
        cc_commands_rows=[
            _cc_cmd_row("gibson1336", id="9", prefix="testing", responses="2"),
            _cc_cmd_row("gibson1337", id="8", prefix="testing", responses="3"),
        ]
    )

    utils.mm_wait_for_prefix(mm, "testing", 5, poll_rate=0.0)


def test_mm_wait_for_prefix_ignores_other_prefixes(monkeypatch):
    clock = _install_fake_clock(monkeypatch)
    mm = _StubMM(
        cc_commands_rows=[_cc_cmd_row("gibson1336", prefix="other", responses="9")]
    )

    with pytest.raises(RuntimeError, match="timed out"):
        utils.mm_wait_for_prefix(mm, "testing", 1, timeout=5.0)

    assert clock.now >= 5.0


@pytest.mark.parametrize("header", [_CC_CMD_HEADER, _CC_CMD_HEADER_LEGACY])
def test_mm_wait_for_cmd_reads_columns_by_header(monkeypatch, header):
    # Columns are located by name, so a minimega that adds or reorders
    # columns must not break the content match.
    _install_fake_clock(monkeypatch)
    row = _cc_cmd_row(
        "gibson1337", header=header, id="20", responses="1", sent="[exp/ours.sh]"
    )
    mm = _StubMM(cc_commands_rows=[row])

    utils.mm_wait_for_cmd(
        mm,
        "20",
        host="gibson1337",
        match_column="sent",
        match_value="[exp/ours.sh]",
        appear_grace=30.0,
    )


@pytest.mark.parametrize("header", [_CC_CMD_HEADER, _CC_CMD_HEADER_LEGACY])
def test_mm_wait_for_prefix_reads_columns_by_header(header):
    mm = _StubMM(
        cc_commands_rows=[_cc_cmd_row(header=header, prefix="testing", responses="2")]
    )

    utils.mm_wait_for_prefix(mm, "testing", 2, poll_rate=0.0)


_UUID = "0ab5dbc3-8ca6-4b75-a503-b5a191995dae"


def _cc_responses_text(cmd_id="3", uuid=_UUID, **files):
    """`cc responses` text as minimega prints it: files in lexical order, each a
    `<id>/<uuid>/<file>:` header line followed by the contents."""
    return "".join(
        f"{cmd_id}/{uuid}/{name}:\n{body}\n" for name, body in sorted(files.items())
    )


class _StubCCResponses:
    def __init__(self, rows):
        self._rows = rows
        self._raise_errors = True

    def cc_exec_once(self, _cmd):
        return [{"Host": "gibson1336", "Data": 3}]

    def cc_responses(self, *_args):
        return self._rows


def test_cc_response_files_splits_stdout_and_stderr():
    text = _cc_responses_text(stderr="warn: x\n", stdout='{"path": "/etc/hosts"}\n')

    assert utils._cc_response_files(text) == {
        ("3", _UUID): {"stderr": "warn: x", "stdout": '{"path": "/etc/hosts"}'}
    }


def test_cc_response_files_keeps_multiple_ids_and_clients():
    other = "11111111-2222-3333-4444-555555555555"
    text = _cc_responses_text("3", stdout="a/b") + _cc_responses_text(
        "12", other, stdout="c: d"
    )

    assert utils._cc_response_files(text) == {
        ("3", _UUID): {"stdout": "a/b"},
        ("12", other): {"stdout": "c: d"},
    }


def test_mm_get_cc_responses_skips_response_without_files(monkeypatch):
    # A prefix whose commands only recorded an exit code: minimega returns "\n".
    mm = _StubCCResponses([{"Host": "h", "Response": "\n", "Error": ""}])

    assert utils.mm_get_cc_responses(mm, "silent") == []


def test_mm_exec_wait_separates_stdout_and_stderr(monkeypatch):
    monkeypatch.setattr(utils, "mm_cc_filter_vm", lambda *_a, **_k: (_UUID, "h"))
    monkeypatch.setattr(utils, "mm_command_id_for_host", lambda *_: "3")
    monkeypatch.setattr(utils, "mm_wait_for_cmd", lambda *_a, **_k: None)
    monkeypatch.setattr(
        utils, "mm_cc_exitcode_wait", lambda *_a, **_k: {"Response": "0"}
    )
    text = _cc_responses_text(stderr="warn: x", stdout="/usr/bin/ls")
    mm = _StubCCResponses([{"Host": "h", "Response": text, "Error": ""}])

    result = utils.mm_exec_wait(mm, "foo", "which ls")

    assert result["stderr"] == "warn: x"
    assert result["stdout"] == "/usr/bin/ls"
    assert result["exitcode"] == 0


def test_mm_get_cc_responses_one_result_per_client(monkeypatch):
    monkeypatch.setattr(
        utils, "mm_cc_exitcode_wait", lambda *_a, **_k: {"Response": "0"}
    )
    text = _cc_responses_text(stderr="warn: x", stdout="tcp 0.0.0.0:22 sshd/1")
    mm = _StubCCResponses([{"Host": "h", "Response": text, "Error": ""}])

    (result,) = utils.mm_get_cc_responses(mm, "netstat_linux")

    assert result["id"] == "3"
    assert result["uuid"] == _UUID
    assert result["stderr"] == "warn: x"
    assert result["stdout"] == "tcp 0.0.0.0:22 sshd/1"
    assert result["exitcode"] == 0


def test_cc_cmd_rows_reads_columns_by_header():
    # minimega added `issued` after `responses`. Columns are looked up by the
    # response's header, so an added column does not shift the cell `once` reads.
    old = ["id", "prefix", "command", "responses", "background", "once"]
    new = ["id", "prefix", "command", "responses", "issued", "background", "once"]

    (old_row,) = utils._cc_cmd_rows(
        {"Header": old, "Tabular": [["7", "", "[x]", "1", "false", "[f]"]]}
    )
    (new_row,) = utils._cc_cmd_rows(
        {"Header": new, "Tabular": [["7", "", "[x]", "1", "1", "false", "[f]"]]}
    )
    (short_row,) = utils._cc_cmd_rows({"Header": new, "Tabular": [["7"]]})

    assert old_row["once"] == new_row["once"] == "[f]"
    assert new_row["issued"] == "1"
    assert "issued" not in old_row
    assert "responses" not in short_row


def test_mm_cc_filtered_sets_the_filter_then_clears_it(mocker):
    mm = mocker.MagicMock(name="mm")

    with utils.mm_cc_filtered(mm, "hostname=vm-1"):
        mm.cc_exec_once("true")

    assert mm.method_calls == [
        mocker.call.cc_filter("hostname=vm-1"),
        mocker.call.cc_exec_once("true"),
        mocker.call.clear_cc_filter(),
    ]


def test_mm_cc_filtered_clears_the_filter_when_the_block_fails(mocker):
    mm = mocker.MagicMock(name="mm")
    mm.cc_exec_once.side_effect = RuntimeError("boom")

    def block():
        with utils.mm_cc_filtered(mm):
            mm.cc_filter("uuid=abc")
            mm.cc_exec_once("true")

    with pytest.raises(RuntimeError, match="boom"):
        block()

    # Without its own filter it leaves the current one alone until it exits.
    assert mm.method_calls == [
        mocker.call.cc_filter("uuid=abc"),
        mocker.call.cc_exec_once("true"),
        mocker.call.clear_cc_filter(),
    ]


@pytest.mark.parametrize(
    ("call", "command"),
    [
        (lambda mm: utils.mm_kill_process(mm, "iperf=1", "iperf3"), "pkill iperf3"),
        (
            lambda mm: utils.mm_kill_process(mm, "iperf=1", "x.exe", "windows"),
            "taskkill -f -im x.exe",
        ),
        (
            lambda mm: utils.mm_delete_file(mm, "iperf=1", "/out.json"),
            "rm -f /out.json",
        ),
    ],
    ids=["kill-linux", "kill-windows", "delete"],
)
def test_filtered_helpers_clear_the_cc_filter(mocker, call, command):
    mm = mocker.MagicMock(name="mm")

    call(mm)

    assert mm.method_calls == [
        mocker.call.cc_filter("iperf=1"),
        mocker.call.cc_exec_once(command),
        mocker.call.clear_cc_filter(),
    ]


@pytest.mark.parametrize("remote", [False, True], ids=["local", "mesh-peer"])
def test_mm_delete_file_reaches_windows_intact(mocker, remote):
    """minimega reads an unspaced backslash path once more on each mesh peer,
    where it fails and leaves the sender waiting for a reply."""
    mm = mocker.MagicMock(name="mm")

    utils.mm_delete_file(mm, "name=opc", "/opcexport/x.log", os_type="windows")

    cmd = mm.cc_exec_once.call_args.args[0]
    words = namespaced_rebuild(f"cc exec {cmd}", remote=remote)
    assert words == ["cc", "exec", "cmd", "/c", "del /q c:\\opcexport\\x.log"]


def test_kill_process_sets_no_filter_for_an_unknown_os(mocker):
    mm = mocker.MagicMock(name="mm")

    with pytest.raises(ValueError, match="unknown os_type 'bsd'"):
        utils.mm_kill_process(mm, "iperf=1", "iperf3", "bsd")

    assert mm.method_calls == []


@pytest.mark.parametrize(
    ("bpf_filter", "arg"),
    [
        (None, "' '"),
        ("", "' '"),
        ("arp", "'arp'"),
        ("udp or arp", "'udp or arp'"),
        ("ether proto \\ip", "'ether proto \\\\ip'"),
        ("ether[0] = 'a'", "'ether[0] = \\'a\\''"),
    ],
    ids=["none", "empty", "one-word", "multi-word", "backslash", "quote"],
)
@pytest.mark.parametrize("remote", [False, True], ids=["local", "mesh-peer"])
def test_mm_capture_filter_arg_survives_a_namespaced_rebuild(bpf_filter, arg, remote):
    """A namespaced `capture pcap filter ''` loses its argument and only queries."""
    assert utils.mm_capture_filter_arg(bpf_filter) == arg

    words = namespaced_rebuild(f"capture pcap filter {arg}", remote=remote)

    assert words[:3] == ["capture", "pcap", "filter"]
    assert len(words) == 4, "the rebuilt command lost its filter argument"
    assert words[3].strip() == (bpf_filter or "")


def test_an_empty_capture_filter_does_not_survive_a_namespaced_rebuild():
    """Why the clear is a blank filter: an empty one turns into a query."""
    assert len(namespaced_rebuild("capture pcap filter ''")) == 3


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        "Create a new user in a command prompt",
        'say "hi" now',
        "it's ok",
        "C:\\Program Files\\art",
        "a # b",
        "tab\there",
        "line\nbreak",
        "café au lait",
        "C:/Users/art",
    ],
)
@pytest.mark.parametrize("remote", [False, True], ids=["local", "mesh-peer"])
def test_mm_cc_arg_survives_a_namespaced_rebuild(value, remote):
    arg = utils.mm_cc_arg(value)
    words = namespaced_rebuild(f"cc exec goart {arg} -q", remote=remote)

    assert words == ["cc", "exec", "goart", value, "-q"]


# Go quotes a word with whitespace and writes these as \u, \x or \a escapes,
# which minicli does not read: the namespaced lex fails and minimega exits.
NOT_RELAYABLE_IN_A_QUOTED_WORD = [
    "a\u00a0b",
    "a\u2003b",
    "a\u200bb c",
    "a\u0007b c",
    "x \u001b[0m",
    "a\u00adb c",
    "a\x7fb c",
    "a\u2028b",
    # Unicode 15.1 added these: Go 1.24, at Unicode 15.0, escapes them even
    # where the running Python prints them.
    "a\u2ffcb c",
    "a\U0002ebf0b c",
]
# minimega rebuilds a word without whitespace raw, so each hop reads one more
# level of escapes: no form of these reaches both the local host and a peer.
NOT_RELAYABLE_WITHOUT_WHITESPACE = ["C:\\Users\\art", "it's", 'a"b', "a#b", "x\\"]


@pytest.mark.parametrize(
    "value", NOT_RELAYABLE_IN_A_QUOTED_WORD + NOT_RELAYABLE_WITHOUT_WHITESPACE
)
def test_mm_cc_arg_refuses_what_minimega_cannot_relay(value):
    with pytest.raises(ValueError, match="holds"):
        utils.mm_cc_arg(value)


@pytest.mark.parametrize("value", NOT_RELAYABLE_IN_A_QUOTED_WORD)
def test_a_quoted_non_printable_character_fails_the_namespaced_lex(value):
    """Why mm_cc_arg refuses them: quoting them as it quotes any word with
    whitespace gives a command minimega cannot lex once rebuilt."""
    quoted = '"' + value + '"'

    with pytest.raises(ValueError, match="unexpected escaped character"):
        namespaced_rebuild(f"cc exec goart {quoted} -q")


@pytest.mark.parametrize(
    "bpf_filter", ["tcp\u00a0port 80", "a\\b", "it's", 'say"hi', "port\u0007 80"]
)
def test_mm_capture_filter_arg_refuses_what_minimega_cannot_relay(bpf_filter):
    with pytest.raises(ValueError, match="holds"):
        utils.mm_capture_filter_arg(bpf_filter)


@pytest.mark.parametrize(
    ("background", "method"),
    [(False, "cc_exec_once"), (True, "cc_background_once")],
)
def test_mm_cc_once_waits_for_the_client_then_queues_once(mocker, background, method):
    """minimega resends a command that is not once to a client that reconnects,
    and marks a once command sent even when no client matched it."""
    mm = mocker.MagicMock(name="mm")
    locate = mocker.patch.object(utils, "mm_cc_client_locate")
    locate.side_effect = lambda *_, **__: mm.located()

    utils.mm_cc_once(mm, "vm-1", "rm -rf /var/log/snort", background=background)

    locate.assert_called_once_with(mm, "vm-1", grace=settings.CC_CLIENT_GRACE)
    assert [c[0] for c in mm.method_calls] == ["located", method]
    getattr(mm, method).assert_called_once_with("rm -rf /var/log/snort")


@pytest.mark.parametrize(
    ("hostname", "compute", "local"),
    [
        ("phenix-head", "phenix-head", True),
        # A shared prefix is another host.
        ("phenix-head", "phenix-c1", False),
        ("head", "head2", False),
        # Docker Compose suffixes, as phenix core trims them.
        ("myhost-phenix", "myhost-minimega", True),
    ],
)
def test_mm_compute_cmd_runs_locally_only_on_this_host(
    mocker, monkeypatch, hostname, compute, local
):
    monkeypatch.delenv("PHENIX_HOSTNAME_SUFFIXES", raising=False)
    monkeypatch.setattr(utils.socket, "gethostname", lambda: hostname)
    send = mocker.patch.object(utils, "_mm_socket_cmd", return_value=[])
    mm = mocker.MagicMock(name="mm", _namespace=None)

    utils.mm_compute_cmd(
        mm, experiment="exp", computes=compute, command_type="tap", command="delete t"
    )

    cmd = send.call_args.args[0]
    if local:
        assert cmd == "namespace exp tap delete t"
    else:
        assert cmd == f"namespace exp mesh send {compute} tap delete t"


@pytest.mark.parametrize(
    ("value", "suffixes"),
    [
        (None, ("-minimega", "-phenix")),
        ("", ()),
        ("-mm", ("-mm",)),
        ("-mm,-px", ("-mm", "-px")),
        (",-mm,", ("-mm",)),
    ],
    ids=["unset", "empty", "one", "two", "blank-entries"],
)
def test_hostname_suffixes_follow_what_phenix_passes(monkeypatch, value, suffixes):
    """Unset means core's defaults; set but empty means none, as phenix's
    --hostname-suffixes is then empty."""
    if value is None:
        monkeypatch.delenv("PHENIX_HOSTNAME_SUFFIXES", raising=False)
    else:
        monkeypatch.setenv("PHENIX_HOSTNAME_SUFFIXES", value)

    assert settings.hostname_suffixes() == suffixes


@pytest.mark.parametrize(
    ("value", "hostname", "node", "local"),
    [
        # phenix's own suffixes, not the defaults.
        ("-mm", "head-mm", "head", True),
        (None, "head-mm", "head", False),
        # No suffixes: a Docker Compose suffix is part of the name.
        ("", "myhost-phenix", "myhost-minimega", False),
        (None, "myhost-phenix", "myhost-minimega", True),
    ],
    ids=["custom", "custom-unset", "none", "none-unset"],
)
def test_is_headnode_trims_the_suffixes_phenix_passes(
    monkeypatch, value, hostname, node, local
):
    monkeypatch.setattr(utils.socket, "gethostname", lambda: hostname)

    if value is None:
        monkeypatch.delenv("PHENIX_HOSTNAME_SUFFIXES", raising=False)
    else:
        monkeypatch.setenv("PHENIX_HOSTNAME_SUFFIXES", value)

    assert utils.is_headnode(node) is local


def test_is_headnode_reads_the_suffixes_at_each_call(mocker, monkeypatch):
    """A long-lived process sees a change, and minimega's first host is
    trimmed the same way."""
    monkeypatch.setattr(utils.socket, "gethostname", lambda: "other")
    mm = mocker.MagicMock(name="mm", _namespace=None)
    mm.host.return_value = [
        {"Host": "head-mm", "Header": ["name"], "Tabular": [["head-mm"]]}
    ]

    monkeypatch.setenv("PHENIX_HOSTNAME_SUFFIXES", "-mm")
    assert utils.is_headnode("head-px", mm) is False

    monkeypatch.setenv("PHENIX_HOSTNAME_SUFFIXES", "-mm,-px")
    assert utils.is_headnode("head-px", mm) is True


@pytest.mark.parametrize(
    "tshark", ["echo partial; exit 2", None], ids=["fails", "missing"]
)
def test_pcap_to_jsonl_leaves_no_output_when_it_fails(tmp_path, monkeypatch, tshark):
    """A partial .jsonl would pass for a finished conversion."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if tshark:
        (bin_dir / "tshark").write_text(f"#!/bin/sh\n{tshark}\n")
        (bin_dir / "tshark").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    out = tmp_path / "x.pcap.jsonl"

    if tshark:
        assert utils.pcap_to_jsonl(tmp_path / "x.pcap", out) == 2
    else:
        with pytest.raises(FileNotFoundError):
            utils.pcap_to_jsonl(tmp_path / "x.pcap", out)

    assert not out.exists()


def test_run_cleanups_runs_each_and_keeps_the_block_error(mocker):
    first = mocker.Mock(side_effect=RuntimeError("socket closed"))
    second = mocker.Mock()

    with pytest.raises(ValueError, match="the block failed"):
        with utils.run_cleanups(first, second):
            raise ValueError("the block failed")

    first.assert_called_once_with()
    second.assert_called_once_with()


def test_run_cleanups_raises_the_first_cleanup_error_after_a_good_block(mocker):
    first = mocker.Mock(side_effect=RuntimeError("first"))
    second = mocker.Mock(side_effect=RuntimeError("second"))

    with pytest.raises(RuntimeError, match="first"), utils.run_cleanups(first, second):
        pass

    second.assert_called_once_with()


def test_record_failure_records_errors_and_lets_a_cancel_through():
    failures = []

    with utils.record_failure(failures, "vm-1"):
        raise RuntimeError("no client")

    assert failures == ["vm-1: no client"]

    with pytest.raises(KeyboardInterrupt), utils.record_failure(failures, "vm-2"):
        raise KeyboardInterrupt

    assert failures == ["vm-1: no client"]


@pytest.mark.parametrize(
    ("compute", "local"), [("foo-mm", True), ("c1", False)], ids=["head", "compute"]
)
def test_mm_compute_cmd_knows_the_headnode_by_minimegas_own_name(
    mocker, monkeypatch, compute, local
):
    """phenix's --hostname-suffixes may differ from the default suffixes, and
    minimega refuses a mesh send to itself."""
    monkeypatch.setattr(utils.socket, "gethostname", lambda: "foo-px")
    send = mocker.patch.object(utils, "_mm_socket_cmd", return_value=[])
    mm = mocker.MagicMock(name="mm", _namespace=None)
    mm.host.return_value = [
        {"Host": "foo-mm", "Header": ["name"], "Tabular": [["foo-mm"]]},
        {"Host": "c1", "Header": ["name"], "Tabular": [["c1"]]},
    ]

    utils.mm_compute_cmd(
        mm, experiment="exp", computes=compute, command_type="tap", command="delete t"
    )

    cmd = send.call_args.args[0]
    if local:
        assert cmd == "namespace exp tap delete t"
    else:
        assert cmd == f"namespace exp mesh send {compute} tap delete t"


@pytest.mark.parametrize("ignore_error", [False, True])
def test_mm_compute_cmd_raises_when_minimega_cannot_be_reached(
    mocker, monkeypatch, tmp_path, ignore_error
):
    """ignore_error returns minimega's errors; it does not hide a dead socket."""
    monkeypatch.setattr(settings, "MM_SOCKET_PATH", str(tmp_path / "none"))
    mm = mocker.MagicMock(name="mm", _namespace=None)

    with pytest.raises(RuntimeError, match="Command failed"):
        utils.mm_compute_cmd(
            mm,
            experiment="exp",
            computes="c1",
            command_type="tap",
            command="delete t",
            ignore_error=ignore_error,
        )


def test_mm_compute_cmd_raises_on_a_minimega_error(mocker, monkeypatch):
    """A minimega error in the reply is raised as a RuntimeError naming it."""
    path = f"\0phenix-apps-test-{uuid.uuid4().hex}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen()
        monkeypatch.setattr(settings, "MM_SOCKET_PATH", path)
        mocker.patch.object(
            utils,
            "_mm_get_response",
            return_value={"Resp": [{"Host": "c1", "Error": "tap already on bridge"}]},
        )
        mm = mocker.MagicMock(name="mm", _namespace=None)

        with pytest.raises(RuntimeError, match="tap already on bridge"):
            utils.mm_compute_cmd(
                mm, experiment="exp", computes="c1", command_type="tap", command="x"
            )


def test_run_command_runs_an_argument_vector_without_a_shell(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    out = utils.run_command(["printf", "%s", "a$(touch${IFS}PWNED)"])

    assert out == "a$(touch${IFS}PWNED)"
    assert not (tmp_path / "PWNED").exists()
