"""opcexport leaves no cc filter in the namespace."""

import pytest

from phenix_apps.apps.scorch.conftest import scorch_experiment
from phenix_apps.apps.scorch.opcexport.opcexport import OPCExport

MODULE = "phenix_apps.apps.scorch.opcexport.opcexport"


@pytest.fixture
def run(component_args, cc_namespace, mocker, tmp_path):
    mocker.patch(f"{MODULE}.time.sleep")
    mocker.patch.object(OPCExport, "create_opc_variables", return_value={})

    def run(stage):
        experiment = scorch_experiment(
            [
                {
                    "name": "opc",
                    "type": "opcexport",
                    "metadata": {"opc_hostname": "opc", "elastic_ip": "10.0.0.9"},
                }
            ],
            [{"configure": ["opc"], "start": ["opc"], "stop": ["opc"]}],
        )
        experiment["spec"]["baseDir"] = str(tmp_path / "exp")
        experiment["spec"]["scenario"]["apps"] += [
            {"name": "sceptre"},
            {"name": "tap", "metadata": {"taps": [{"ip": "10.0.0.1/24"}]}},
        ]
        (tmp_path / "exp").mkdir(exist_ok=True)
        component_args(experiment, stage, "opc")
        OPCExport()

    return run


@pytest.mark.parametrize(
    ("stage", "commands"),
    [
        (
            "configure",
            [
                (
                    "powershell.exe -File C:/opcexport/install-python-opc.ps1",
                    "uuid=opc-uuid",
                ),
                ("route add 10.0.0.0 MASK 255.255.255.0 10.0.0.1", "uuid=opc-uuid"),
                (
                    'powershell.exe -Command "Test-Connection -ComputerName '
                    '10.0.0.9 -Count 1 -Quiet"',
                    "uuid=opc-uuid",
                ),
            ],
        ),
        (
            "start",
            [
                (
                    "C:/Progra~1/Python38/python.exe C:/opcexport/scada_to_elastic.py "
                    "-u opc.tcp://opc:4840 -f /opcexport/opc_variables.json "
                    "-e 10.0.0.9:9200",
                    "name=opc",
                ),
                ("tasklist", "uuid=opc-uuid"),
            ],
        ),
        (
            "stop",
            [
                ("taskkill -f -im python.exe", "name=opc"),
                (r'cmd /c "del /q c:\\opcexport\\scada_to_elastic.log"', "name=opc"),
            ],
        ),
        (
            "cleanup",
            [
                (
                    "C:/Progra~1/Python38/python.exe "
                    "C:/opcexport/delete_scada_to_elastic.py -e 10.0.0.9:9200",
                    "uuid=opc-uuid",
                )
            ],
        ),
    ],
)
def test_stage_clears_the_cc_filters_it_sets(cc_namespace, run, stage, commands):
    cc_namespace.result["stdout"] = "python.exe  1234 Console"

    run(stage)

    assert [(c, f) for _, c, f in cc_namespace.queued] == commands
    assert cc_namespace.filter is None


def test_failed_configure_still_clears_the_cc_filter(cc_namespace, run):
    cc_namespace.result = {"exitcode": 1, "stdout": "False", "stderr": ""}

    with pytest.raises(RuntimeError, match="Test-Connection"):
        run("configure")

    assert cc_namespace.filter is None
