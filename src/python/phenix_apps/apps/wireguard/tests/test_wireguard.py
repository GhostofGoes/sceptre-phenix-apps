"""The wireguard config holds a private key, so nobody else may read it."""

import os
import stat

import pytest
from box import Box

from phenix_apps.apps.wireguard.app import Wireguard
from phenix_apps.common import utils

pytestmark = pytest.mark.app_class(cls=Wireguard, name="wireguard", stage="pre-start")

NODE = Box(
    {
        "hostname": "vpn-1",
        "metadata": {
            "interface": {"address": "10.0.0.1/24", "private_key": "c2VjcmV0"},
            "peers": [{"public_key": "cHVibGlj", "allowed_ips": "10.0.0.2/32"}],
        },
    }
)


@pytest.fixture
def startup(mock_app, tmp_path):
    mock_app.startup_dir = tmp_path / "startup"
    mock_app.startup_dir.mkdir()
    mock_app.extract_all_nodes.return_value = [NODE]
    return mock_app.startup_dir


def _mode(path_or_fd) -> int:
    st = os.fstat(path_or_fd) if isinstance(path_or_fd, int) else os.stat(path_or_fd)
    return stat.S_IMODE(st.st_mode)


@pytest.mark.parametrize("existing", [False, True])
def test_config_is_never_readable_by_others(mock_app, startup, mocker, existing):
    conf = startup / "vpn-1-wireguard.conf"
    if existing:
        conf.write_text("stale\n")
        conf.chmod(0o644)

    render = utils.mako_serve_template
    modes = []

    def spy(name, templates, f, **kwargs):
        modes.append(_mode(f.fileno()))
        render(name, templates, f, **kwargs)
        modes.append(_mode(f.fileno()))

    mocker.patch.object(utils, "mako_serve_template", side_effect=spy)
    old_umask = os.umask(0o022)
    try:
        mock_app.pre_start()
    finally:
        os.umask(old_umask)

    assert modes == [0o600, 0o600]
    assert _mode(conf) == 0o600
    assert "PrivateKey = c2VjcmV0" in conf.read_text()
    assert [p.name for p in startup.iterdir()] == [conf.name]
    mock_app.add_inject.assert_called_once_with(
        hostname="vpn-1",
        inject={"src": str(conf), "dst": "/etc/wireguard/wg0.conf"},
    )


def test_a_failed_render_leaves_no_temporary_file(mock_app, startup, mocker):
    mocker.patch.object(utils, "mako_serve_template", side_effect=RuntimeError("bad"))

    with pytest.raises(RuntimeError, match="bad"):
        mock_app.pre_start()

    assert list(startup.iterdir()) == []
