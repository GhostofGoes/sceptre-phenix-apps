"""The art component's goart checks and options, and the cc filter it leaves."""

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.art.art import AtomicRedTeam
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.testing.minicli import namespaced_rebuild

NODES = [
    {
        "type": "VirtualMachine",
        "general": {"hostname": "vm-1"},
        "hardware": {"os_type": "linux"},
        "network": {"interfaces": []},
    }
]


@pytest.fixture
def cc(mocker):
    """mm_exec_wait and mm_recv as the art module calls them."""
    mocker.patch.object(ComponentBase, "mm_init", return_value=mocker.MagicMock())
    exec_wait = mocker.patch("phenix_apps.apps.scorch.art.art.utils.mm_exec_wait")
    recv = mocker.patch("phenix_apps.apps.scorch.art.art.utils.mm_recv")
    mocker.patch("phenix_apps.apps.scorch.art.art.time.sleep")
    return exec_wait, recv


def _start(component_args, metadata):
    md = {"technique": "T1006", "testIndex": 0, "vms": [{"hostname": "vm-1"}]}
    md.update(metadata)
    component_args(
        scorch_experiment(
            [{"name": "art", "type": "art", "metadata": md}],
            [{"start": ["art"]}],
            NODES,
        ),
        "start",
        "art",
    )
    AtomicRedTeam()


def test_missing_goart_fails_before_running_anything(component_args, cc):
    exec_wait, recv = cc
    exec_wait.return_value = {"exitcode": 1, "stdout": "", "stderr": ""}

    with pytest.raises(
        RuntimeError, match="goart not found or not executable at /phenix/art/goart"
    ):
        _start(component_args, {})

    assert [c.args[2] for c in exec_wait.call_args_list] == [
        "test -x /phenix/art/goart"
    ]
    recv.assert_not_called()


def test_present_goart_runs_the_test(component_args, cc):
    exec_wait, recv = cc
    exec_wait.return_value = {"exitcode": 0, "stdout": "", "stderr": ""}

    _start(component_args, {})

    commands = [c.args[2] for c in exec_wait.call_args_list]
    assert commands[0] == "test -x /phenix/art/goart"
    assert commands[1].startswith("/phenix/art/goart -q -f json -t T1006 -o /tmp/")
    assert commands[1].endswith(" -i 0")
    assert recv.call_args.args[3].endswith("/vm-1.json")


def test_documented_path_and_wait_options(component_args, cc, mocker):
    exec_wait, recv = cc
    exec_wait.return_value = {"exitcode": 0, "stdout": "", "stderr": ""}
    sleep = mocker.patch("phenix_apps.apps.scorch.art.art.time.sleep")

    _start(
        component_args,
        {
            "goartPath": "/opt/goart",
            "outputPath": "/var/tmp/art/",
            "execWaitSeconds": 12,
        },
    )

    commands = [c.args[2] for c in exec_wait.call_args_list]
    assert commands[0] == "test -x /opt/goart"
    assert commands[1].startswith("/opt/goart -q -f json -t T1006 -o /var/tmp/art/")
    assert recv.call_args.args[2].startswith("/var/tmp/art/")
    sleep.assert_called_once_with(12.0)


@pytest.mark.parametrize(
    ("option", "value"),
    [("goartPath", "/opt/goart; reboot"), ("outputPath", "/tmp/$(id)")],
)
def test_path_options_are_validated(component_args, cc, option, value):
    with pytest.raises(RuntimeError, match=option):
        _start(component_args, {option: value})

    cc[0].assert_not_called()


@pytest.mark.parametrize("exitcode", [0, 1], ids=["runs", "goart-missing"])
def test_start_clears_the_cc_filter(component_args, cc_namespace, mocker, exitcode):
    mocker.patch("phenix_apps.apps.scorch.art.art.time.sleep")
    cc_namespace.result["exitcode"] = exitcode

    if exitcode:
        with pytest.raises(RuntimeError, match="goart not found"):
            _start(component_args, {})
    else:
        _start(component_args, {})

    assert {f for _, _, f in cc_namespace.queued} == {"uuid=vm-1-uuid"}
    assert cc_namespace.filter is None


@pytest.mark.parametrize("remote", [False, True], ids=["local", "mesh-peer"])
def test_values_with_spaces_reach_goart_as_one_argument(component_args, cc, remote):
    exec_wait, _ = cc
    exec_wait.return_value = {"exitcode": 0, "stdout": "", "stderr": ""}

    _start(
        component_args,
        {
            "testIndex": None,
            "testName": "Create a new user in a command prompt",
            "env": {"GREETING": 'say "hi"'},
            "vms": [{"hostname": "vm-1", "inputs": {"path": "C:\\Program Files\\art"}}],
        },
    )

    cmd = exec_wait.call_args_list[1].args[2]
    argv = namespaced_rebuild(f"cc exec {cmd}", remote=remote)[2:]
    assert argv[0] == "/phenix/art/goart"
    assert argv[8:] == [
        "-n",
        "Create a new user in a command prompt",
        "--env",
        'GREETING=say "hi"',
        "--input",
        "path=C:\\Program Files\\art",
    ]


@pytest.mark.parametrize(
    ("metadata", "what"),
    [
        ({"testName": "add\u00a0user"}, "testName"),
        ({"env": {"X": "a\u200bb c"}}, "env X"),
        ({"vms": [{"hostname": "vm-1", "inputs": {"p": "C:\\Users"}}]}, "vm-1 input p"),
        (
            {"vms": [{"hostname": "vm-1"}, {"hostname": "vm-2", "env": {"Y": "a#b"}}]},
            "vm-2 env Y",
        ),
    ],
    ids=["nbsp", "zero-width-space", "unspaced-backslash", "unspaced-hash"],
)
def test_values_minimega_cannot_relay_fail_before_running_anything(
    component_args, cc, metadata, what
):
    """minimega exits on a non-printable character in a quoted word, and a mesh
    peer drops an unspaced word with a backslash, quote or '#'."""
    exec_wait, recv = cc

    with pytest.raises(RuntimeError, match=f"art component 'art': {what} holds"):
        _start(component_args, {"testIndex": None, "testName": "t", **metadata})

    exec_wait.assert_not_called()
    recv.assert_not_called()


@pytest.mark.parametrize("abort", [False, True])
def test_a_failing_goart_is_reported(component_args, cc, mocker, abort):
    exec_wait, recv = cc
    log = mocker.patch("phenix_apps.apps.scorch.art.art.logger")
    exec_wait.side_effect = [
        {"exitcode": 0, "stdout": "", "stderr": ""},
        {"exitcode": 3, "stdout": "", "stderr": "unknown test"},
    ]

    if abort:
        with pytest.raises(RuntimeError, match="goart exited 3 on vm-1: unknown test"):
            _start(component_args, {"abortOnError": True})
        recv.assert_not_called()
    else:
        _start(component_args, {})
        log.error.assert_called_once_with("goart exited 3 on vm-1: unknown test")
        recv.assert_called_once()
