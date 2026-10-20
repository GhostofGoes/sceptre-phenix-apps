"""Which components the collector collects from in a run."""

import pytest

from phenix_apps.apps.scorch.collector.collector import Collector
from phenix_apps.apps.scorch.conftest import scorch_experiment

COMPONENTS = [
    {"name": "collector", "type": "collector", "metadata": {}},
    {"name": "vmstats", "type": "vmstats", "metadata": {}},
    {"name": "unused-qos", "type": "qos", "metadata": {}},
]


def test_run_without_a_loop(component_args):
    """phenix stores an absent loop as null."""
    runs = [{"start": ["vmstats"], "stop": ["vmstats", "collector"]}]
    component_args(scorch_experiment(COMPONENTS, runs), "configure", "collector")

    collector = Collector()

    assert sorted(collector.enabled_components) == ["collector", "vmstats"]


@pytest.mark.parametrize(
    ("loop", "enabled"), [(0, ["collector"]), (1, ["collector", "vmstats"])]
)
def test_components_in_nested_loops(component_args, loop, enabled):
    """The collector collects from the components of the loop it runs in."""
    runs = [
        {
            "stop": ["collector"],
            "loop": {
                "start": ["vmstats"],
                "stop": ["vmstats", "collector"],
                "loop": {"start": ["unused-qos"], "loop": None, "count": 2},
                "count": 1,
            },
        }
    ]
    component_args(
        scorch_experiment(COMPONENTS, runs), "configure", "collector", loop=loop
    )

    collector = Collector()

    assert sorted(collector.enabled_components) == enabled


@pytest.fixture
def no_phenix(mocker):
    """Run stop by hand, without the phenix CLI."""
    mocker.patch.object(Collector, "execute_stage")
    mocker.patch(
        "phenix_apps.apps.scorch.collector.collector.utils.run_command",
        return_value="spec: {}",
    )


def _nest(inner, depth):
    """A run's loop whose loop `depth` levels into the run is `inner`."""
    loop = inner
    for _ in range(depth - 1):
        loop = {"loop": loop, "count": 1}
    return loop


def _vm_stats(files_dir, loop, count):
    """Write vmstats' output where phenix has it write in that loop."""
    vm_dir = files_dir / f"scorch/run-0/vmstats/loop-{loop}-count-{count}"
    vm_dir.mkdir(parents=True)
    (vm_dir / "vm_stats.jsonl").write_text(f'{{"loop": {loop}}}\n')


@pytest.mark.usefixtures("no_phenix")
@pytest.mark.parametrize("depth", [1, 2])
def test_a_component_only_in_a_nested_loop_is_skipped(
    component_args, log_messages, depth
):
    """phenix names a component's output directory by its loop depth and count
    only, so the collector cannot find what a nested loop's components wrote."""
    inner = {"start": ["vmstats"], "stop": ["vmstats"], "count": 1}
    runs = [{"stop": ["collector"], "loop": _nest(inner, depth)}]
    files_dir = component_args(scorch_experiment(COMPONENTS, runs), "stop", "collector")
    _vm_stats(files_dir, depth, 0)

    collector = Collector()

    # stop gets past vmstats to the disruption component it needs.
    with pytest.raises(ValueError, match="'disruption' component isn't enabled"):
        collector.stop()
    assert "vmstats" not in collector.enabled_components
    assert (
        "not collecting from 'vmstats': it does not run in loop 0 of run 0, "
        "where collector 'collector' runs"
    ) in log_messages


@pytest.mark.usefixtures("no_phenix")
def test_a_collector_in_a_nested_loop_collects_from_that_loop(component_args):
    inner = {"start": ["vmstats"], "stop": ["vmstats", "collector"], "count": 2}
    runs = [{"loop": _nest(inner, 2)}]
    files_dir = component_args(
        scorch_experiment(COMPONENTS, runs), "stop", "collector", loop=2, count=1
    )
    _vm_stats(files_dir, 2, 1)

    collector = Collector()

    with pytest.raises(ValueError, match="'disruption' component isn't enabled"):
        collector.stop()
    assert (collector.meta_dir / "vm_stats.jsonl").read_text() == '{"loop": 2}\n'


def test_a_component_without_a_type_counts_as_its_name(component_args):
    """phenix core defaults an omitted or empty type to the name."""
    components = [
        {"name": "collector", "metadata": {}},
        {"name": "vmstats", "type": "", "metadata": {}},
    ]
    runs = [{"start": ["vmstats"], "stop": ["vmstats", "collector"]}]
    component_args(scorch_experiment(components, runs), "configure", "collector")

    collector = Collector()

    assert sorted(collector.enabled_components) == ["collector", "vmstats"]


PCAPS = [
    {"name": "collector", "type": "collector", "metadata": {}},
    {"name": "pcap-a", "type": "pcap", "metadata": {}},
    {"name": "pcap-b", "type": "pcap", "metadata": {}},
]


def test_component_type_defined_twice_in_the_scenario(component_args):
    """Each run collects from the pcap component it actually uses."""
    runs = [
        {"start": ["pcap-a"], "stop": ["pcap-a", "collector"]},
        {"start": ["pcap-b"], "stop": ["pcap-b", "collector"]},
    ]
    files_dir = component_args(scorch_experiment(PCAPS, runs), "configure", "collector")

    collector = Collector()

    assert collector.enabled_components["pcap"].name == "pcap-a"
    (files_dir / "scorch/run-0/pcap-a/loop-0-count-0").mkdir(parents=True)
    assert collector._comp_dir("pcap").parts[-2] == "pcap-a"


def test_component_type_used_twice_in_one_run(component_args, log_messages):
    runs = [{"start": ["pcap-b", "pcap-a"], "stop": ["pcap-b", "pcap-a", "collector"]}]
    component_args(scorch_experiment(PCAPS, runs), "configure", "collector")

    collector = Collector()

    assert collector.enabled_components["pcap"].name == "pcap-a"
    assert any(
        "collecting from 'pcap-a' and ignoring 'pcap-b'" in m for m in log_messages
    )


def _linux(hostname, typ="VirtualMachine"):
    return {
        "type": typ,
        "general": {"hostname": hostname},
        "hardware": {"os_type": "linux"},
        "network": {"interfaces": []},
    }


def test_miniccc_logs_come_from_where_phenix_images_write_them(component_args, mocker):
    components = [
        {
            "name": "collector",
            "type": "collector",
            "metadata": {"collect_miniccc": True},
        }
    ]
    runs = [{"stop": ["collector"]}]
    nodes = [_linux("new-image"), _linux("old-image"), _linux("rtr", "Router")]
    component_args(scorch_experiment(components, runs, nodes), "configure", "collector")
    collector = Collector()

    mocker.patch(
        "phenix_apps.apps.scorch.collector.collector.utils.run_command",
        return_value="spec: {}",
    )
    found = {"new-image": "/var/log/miniccc.log", "old-image": "/miniccc.log"}

    def recv_file(vm, src, dst):
        if found[vm] != src:
            raise RuntimeError(f"error receiving file '{src}' from VM {vm}")

    recv = mocker.patch.object(collector, "recv_file", side_effect=recv_file)

    # The collector needs a disruption component once the logs are in.
    with pytest.raises(ValueError, match="disruption"):
        collector.stop()

    received = [c.args[:2] for c in recv.call_args_list]
    assert received == [
        ("new-image", "/var/log/miniccc.log"),
        ("old-image", "/var/log/miniccc.log"),
        ("old-image", "/miniccc.log"),
    ]
    dst = recv.call_args_list[0].args[2]
    assert dst.endswith("miniccc/new-image_miniccc.log")


def test_missing_miniccc_log_names_every_path(component_args, mocker):
    components = [
        {
            "name": "collector",
            "type": "collector",
            "metadata": {"collect_miniccc": True},
        }
    ]
    component_args(
        scorch_experiment(components, [{"stop": ["collector"]}], [_linux("vm-1")]),
        "configure",
        "collector",
    )
    collector = Collector()
    mocker.patch(
        "phenix_apps.apps.scorch.collector.collector.utils.run_command",
        return_value="spec: {}",
    )
    mocker.patch.object(collector, "recv_file", side_effect=RuntimeError("not found"))

    with pytest.raises(
        RuntimeError, match=r"vm-1.*/var/log/miniccc\.log.*/miniccc\.log"
    ):
        collector.stop()
