"""Unit tests for the mgmt_tap app."""

import pytest
from box import Box

from phenix_apps.apps import AppBase
from phenix_apps.apps.mgmt_tap.app import TAP_NAME_MAX, MgmtTap, host_tap_name

pytestmark = pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap")


def _configure(mock_app, metadata=None, spec=None):
    """Set the metadata / experiment spec that _get_bridge() reads."""
    mock_app.metadata = metadata if metadata is None else Box(metadata)
    mock_app.experiment = Box({"spec": spec or {}})
    return mock_app


# --- Bridge resolution -------------------------------------------------------


def test_metadata_bridge_takes_precedence(mock_app):
    """An explicit bridge in app metadata wins over the experiment default."""
    app = _configure(mock_app, {"bridge": "metabr"}, {"defaultBridge": "expbr"})
    assert app._get_bridge() == "metabr"


def test_falls_back_to_experiment_default_bridge(mock_app):
    """With no metadata bridge, the experiment's defaultBridge is used."""
    app = _configure(mock_app, {}, {"defaultBridge": "expbr"})
    assert app._get_bridge() == "expbr"


def test_falls_back_to_phenix_when_no_default_bridge(mock_app):
    """Neither metadata nor spec set a bridge, so the built-in default applies."""
    app = _configure(mock_app, {}, {})
    assert app._get_bridge() == MgmtTap.DEFAULT_BRIDGE == "phenix"


@pytest.mark.parametrize("empty", ["", None])
def test_empty_metadata_bridge_is_ignored(mock_app, empty):
    """A blank bridge value must not shadow the experiment default."""
    app = _configure(mock_app, {"bridge": empty}, {"defaultBridge": "expbr"})
    assert app._get_bridge() == "expbr"


def test_absent_metadata_is_tolerated(mock_app):
    """metadata may be None/empty; resolution must not raise."""
    app = _configure(mock_app, None, {"defaultBridge": "expbr"})
    assert app._get_bridge() == "expbr"


# --- Bridge is threaded into the minimega command ----------------------------


@pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap", dryrun=False)
def test_post_start_uses_resolved_bridge(mock_app, mocker):
    """The resolved bridge is what actually lands in the `tap create` command."""
    app = _configure(mock_app, {"bridge": "metabr"}, {"defaultBridge": "expbr"})
    app.bridge = app._get_bridge()
    app.vlan = "MGMT"
    app.subnet = None
    app.tap = "testexp_test"
    app.hosts = ["host1"]
    app.experiment.status = Box({"vlans": {"MGMT": 101}})

    mocker.patch.object(MgmtTap, "_get_mm_connection", return_value=mocker.MagicMock())
    compute_cmd = mocker.patch("phenix_apps.apps.mgmt_tap.app.mm_compute_cmd")

    app.post_start()

    command = compute_cmd.call_args.kwargs["command"]
    assert "bridge metabr" in command
    assert "bridge phenix" not in command


# --- Namespace and host tap name ---------------------------------------------

LONG_NAMES = ("e2e-mtlongname1", "e2e-mtlongname2")


def _ready_for_taps(app, mocker, exp_name, vlans=None):
    """Give the app what post_start and cleanup read, and mock minimega."""
    app.exp_name = exp_name
    app.tap = host_tap_name(exp_name)
    app.bridge = "phenix"
    app.vlan = "MGMT"
    app.subnet = "192.168.250.0/24"
    app.hosts = ["host1"]
    app.experiment = Box({"spec": {}, "status": {"vlans": vlans or {"MGMT": 101}}})

    connect = mocker.patch.object(
        MgmtTap, "_get_mm_connection", return_value=mocker.MagicMock()
    )
    compute_cmd = mocker.patch("phenix_apps.apps.mgmt_tap.app.mm_compute_cmd")
    return connect, compute_cmd


def test_host_tap_names_are_short_and_distinct_for_a_shared_prefix():
    names = [host_tap_name(name) for name in LONG_NAMES]

    assert names[0] != names[1]
    assert all(len(name) <= TAP_NAME_MAX for name in names)
    assert host_tap_name(LONG_NAMES[0]) == names[0]


def test_init_keeps_the_full_experiment_name(mocker):
    def base_init(self, name, stage, dryrun=False):
        self.name, self.stage, self.dryrun = name, stage, dryrun
        self.metadata = Box({})
        self.experiment = Box({"spec": {}})
        self.exp_name = LONG_NAMES[0]

    mocker.patch.object(AppBase, "__init__", base_init)
    mocker.patch.object(MgmtTap, "_get_hosts", return_value=["host1"])

    app = MgmtTap("mgmt_tap", "post-start")

    assert app.exp_name == LONG_NAMES[0]
    assert app.tap == host_tap_name(LONG_NAMES[0])


@pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap", dryrun=False)
def test_post_start_creates_the_tap_in_the_experiment_namespace(mock_app, mocker):
    _, compute_cmd = _ready_for_taps(mock_app, mocker, LONG_NAMES[0])

    mock_app.post_start()

    kwargs = compute_cmd.call_args.kwargs
    assert kwargs["experiment"] == LONG_NAMES[0]
    assert kwargs["command"] == (
        f"create 101 bridge phenix ip 192.168.250.1/24 {host_tap_name(LONG_NAMES[0])}"
    )


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (
            [{"Host": "host1", "Error": "tap already on bridge"}],
            "tap already on bridge",
        ),
        # minimega answers nothing for a host its mesh has no route to.
        ([], "minimega got no reply from it"),
        (
            RuntimeError("Command failed: [Errno 111] Connection refused"),
            r"Command failed: \[Errno 111\] Connection refused",
        ),
    ],
    ids=["error", "no-reply", "no-connection"],
)
@pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap", dryrun=False)
def test_a_failed_tap_create_fails_post_start_naming_the_host(
    mock_app, mocker, reply, error
):
    _, compute_cmd = _ready_for_taps(mock_app, mocker, "exp")
    # A mock raises an exception it gets in side_effect and returns the rest.
    compute_cmd.side_effect = [reply]

    with pytest.raises(RuntimeError, match=f"tap {mock_app.tap} on host1: {error}$"):
        mock_app.post_start()


@pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap", dryrun=False)
def test_cleanup_deletes_the_tap_in_the_experiment_namespace(mock_app, mocker):
    _, compute_cmd = _ready_for_taps(mock_app, mocker, LONG_NAMES[0])

    mock_app.cleanup()

    kwargs = compute_cmd.call_args.kwargs
    assert kwargs["experiment"] == LONG_NAMES[0]
    assert kwargs["command"] == f"delete {host_tap_name(LONG_NAMES[0])}"
    assert kwargs["ignore_error"] is True


@pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap", dryrun=False)
def test_post_start_names_a_missing_vlan_alias(mock_app, mocker):
    _, compute_cmd = _ready_for_taps(mock_app, mocker, "exp", vlans={"LAN": 102})
    mock_app.vlan = "NOPE"

    with pytest.raises(RuntimeError, match="Cannot find VLAN ID for alias NOPE"):
        mock_app.post_start()

    compute_cmd.assert_not_called()


# --- Dry runs ----------------------------------------------------------------


@pytest.mark.parametrize("stage", ["post_start", "cleanup"])
def test_dry_run_leaves_the_host_alone(mock_app, mocker, stage):
    """mock_app is a dry run by default; a dry run has VLAN ID 0."""
    connect, compute_cmd = _ready_for_taps(mock_app, mocker, "exp", {"MGMT": 0})

    getattr(mock_app, stage)()

    connect.assert_not_called()
    compute_cmd.assert_not_called()


@pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap", dryrun=False)
def test_cleanup_ignores_only_taps_already_gone(mock_app, mocker):
    _, compute_cmd = _ready_for_taps(mock_app, mocker, "exp")
    mock_app.hosts = ["host1", "host2", "host3", "host4", "host5"]
    compute_cmd.side_effect = [
        [{"Host": "host1", "Error": "unknown tap"}],
        # minimega answers nothing for a host its mesh has no route to.
        [],
        [{"Host": "host3", "Error": ""}],
        RuntimeError("Command failed: [Errno 111] Connection refused"),
        [{"Host": "host5", "Error": "timed out"}],
    ]

    with pytest.raises(RuntimeError) as err:
        mock_app.cleanup()

    assert str(err.value).endswith(
        "host2: minimega got no reply from it; "
        "host4: Command failed: [Errno 111] Connection refused; host5: timed out"
    )
    assert [c.kwargs["computes"] for c in compute_cmd.call_args_list] == [
        "host1",
        "host2",
        "host3",
        "host4",
        "host5",
    ]


@pytest.mark.app_class(cls=MgmtTap, name="mgmt_tap", dryrun=False)
def test_cleanup_of_taps_already_gone_succeeds(mock_app, mocker):
    _, compute_cmd = _ready_for_taps(mock_app, mocker, "exp")
    compute_cmd.return_value = [{"Host": "host1", "Error": "unknown tap"}]

    mock_app.cleanup()
