"""Every XML file the sceptre app renders must be well-formed."""

from pathlib import Path

import lxml.etree as ET
from box import Box

from phenix_apps.apps.sceptre.tests.conftest import host, run_both_stages

INPUT_FILE = Path(__file__).parent / "test_sceptre_input.yaml"


def test_fd_client_polling_every_protocol_renders_valid_xml(monkeypatch, tmp_path):
    base_dir = tmp_path / "exp"
    exp = Box.from_yaml(INPUT_FILE.read_text())
    exp.spec.baseDir = str(base_dir)
    # rtu-1 and rtu-3 serve dnp3, rtu-2 serves modbus.
    host(exp, "client-1").metadata.connected_rtus = ["rtu-1", "rtu-2", "rtu-3"]

    run_both_stages(monkeypatch, exp)

    rendered = sorted(base_dir.rglob("*.xml"))
    assert rendered
    for path in rendered:
        ET.parse(str(path))  # raises XMLSyntaxError on a malformed file

    client = ET.parse(str(base_dir / "sceptre" / "client-1" / "config.xml"))
    comms = client.find("field-device/comms")
    assert comms.findtext("modbus-client/command-interface") == "tcp://10.1.0.31:1331"
    assert comms.findtext("dnp3-client/command-interface") == "tcp://10.1.0.31:1330"
    assert len(comms.findall("modbus-client/modbus-connection")) == 1
    assert len(comms.findall("dnp3-client/dnp3-connection")) == 2
