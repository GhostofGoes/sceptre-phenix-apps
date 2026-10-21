"""Local OVS commands the erspan component runs through minimega."""

import pytest

from phenix_apps.apps.scorch.app import ComponentBase
from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.erspan.erspan import ERSPAN

METADATA = {"local_bridge": "phenix", "local_ip": "10.9.0.1", "remote_ip": "10.9.0.2"}


@pytest.fixture
def mm(mocker):
    """minimega whose shell fails for commands containing `mm.fail_on`."""
    fake = mocker.MagicMock(name="mm")
    fake.fail_on = None
    fake.stdout = {}

    def shell(command):
        if fake.fail_on and fake.fail_on in command:
            raise RuntimeError("ovs-vsctl: no bridge named phenix")
        response = next((v for k, v in fake.stdout.items() if k in command), "")
        return [{"Host": "head", "Response": response, "Error": ""}]

    fake.shell.side_effect = shell
    mocker.patch.object(ComponentBase, "mm_init", return_value=fake)
    return fake


def _run(component_args, stage, metadata=None):
    experiment = scorch_experiment(
        [{"name": "ers", "type": "erspan", "metadata": metadata or METADATA}],
        [{"configure": ["ers"], "cleanup": ["ers"]}],
    )
    experiment["status"] = {"vlans": {"EXP": 101, "MGMT": 100}}
    component_args(experiment, stage, "ers")
    ERSPAN()


def _shell_commands(mm):
    return [c.args[0] for c in mm.shell.call_args_list]


def test_failing_local_command_fails_configure(component_args, mm):
    mm.fail_on = "add-port"

    with pytest.raises(RuntimeError, match=r"add-port phenix erspan1.*no bridge"):
        _run(component_args, "configure")

    # Nothing runs after the failure.
    assert len(_shell_commands(mm)) == 1


def test_failing_cleanup_command_still_runs_the_rest(component_args, mm):
    mm.fail_on = "find Port"

    with pytest.raises(RuntimeError, match="no bridge"):
        _run(component_args, "cleanup")

    assert any("del-port phenix erspan1" in c for c in _shell_commands(mm))


def test_configure_adds_its_mirror_beside_others(component_args, mm):
    """phenix-app-mirror's mirrors on the same bridge must survive."""
    _run(component_args, "configure")

    (mirror_cmd,) = [c for c in _shell_commands(mm) if "create Mirror" in c]
    assert "name=m0" in mirror_cmd
    assert "select_vlan=100,101" in mirror_cmd
    assert mirror_cmd.endswith("-- add Bridge phenix mirrors @m")
    assert "mirrors=@m" not in mirror_cmd


PORT = "0c5f6c8e-3b7a-4d2e-9f1a-2b3c4d5e6f70"
MIRROR = "5d3c0f5e-0b4e-4c43-9a89-1f0b3e7e6f21"


def test_cleanup_removes_only_its_mirror(component_args, mm):
    """Another erspan component's mirror is named m0 too, but outputs to
    another port."""
    mm.stdout = {
        "find Port name=erspan1": f"{PORT}\n",
        f"find Mirror name=m0 output_port={PORT}": f"{MIRROR}\n",
    }

    _run(component_args, "cleanup")

    commands = _shell_commands(mm)
    assert not [c for c in commands if "clear" in c]
    assert commands == [
        "ovs-vsctl --bare --columns=_uuid find Port name=erspan1",
        f"ovs-vsctl --bare --columns=_uuid find Mirror name=m0 output_port={PORT}",
        f"ovs-vsctl remove Bridge phenix mirrors {MIRROR}",
        "ovs-vsctl --if-exists del-port phenix erspan1",
    ]


@pytest.mark.parametrize(
    "stdout",
    [{}, {"find Port name=erspan1": f"{PORT}\n"}],
    ids=["no-port", "no-mirror"],
)
def test_cleanup_without_its_mirror(component_args, mm, stdout):
    """Cleanup also runs after a configure that failed before the mirror."""
    mm.stdout = stdout

    _run(component_args, "cleanup")

    commands = _shell_commands(mm)
    assert not [c for c in commands if "remove Bridge" in c or "clear" in c]
    assert commands[-1] == "ovs-vsctl --if-exists del-port phenix erspan1"


def test_failing_remote_cleanup_keeps_the_local_failures(
    component_args, mm, mocker, tmp_path
):
    """A remote failure joins the local ones, and the metadata is still saved."""
    ssh = mocker.patch(
        "phenix_apps.apps.scorch.erspan.erspan.paramiko.SSHClient"
    ).return_value
    stdout, stderr = mocker.MagicMock(), mocker.MagicMock()
    stdout.read.return_value = b""
    stdout.channel.recv_exit_status.return_value = 1
    stderr.read.return_value = b"Cannot find device erspan1"
    ssh.exec_command.return_value = (mocker.MagicMock(), stdout, stderr)
    mm.fail_on = "find Port"
    metadata = {
        **METADATA,
        "remote_config": {
            "ssh_ip": "10.9.0.3",
            "user": "root",
            "remote_bridge": "br0",
        },
    }

    with pytest.raises(RuntimeError) as exc:
        _run(component_args, "cleanup", metadata)

    assert "no bridge" in str(exc.value)
    assert "10.9.0.3" in str(exc.value)
    assert "Cannot find device erspan1" in str(exc.value)
    record = tmp_path / "files/scorch/run-0/ers/loop-0-count-0"
    assert (record / "erspan_metadata_cleanup.json").is_file()
