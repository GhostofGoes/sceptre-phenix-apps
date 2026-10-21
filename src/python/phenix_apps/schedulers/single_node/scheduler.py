from phenix_apps.schedulers import SchedulerBase


class SingleNode(SchedulerBase):
    def __init__(self):
        SchedulerBase.__init__(self, "single-node")

        spec = self.experiment.spec
        hosts = self.experiment.get("hosts") or []

        if not hosts:
            raise ValueError("single-node scheduler: phenix passed no cluster hosts")

        for vm in spec.topology.nodes:
            hostname = vm.general.hostname

            # minimega runs no external node, so phenix schedules none.
            if vm.get("external") or hostname in spec.schedules:
                continue

            spec.schedules[hostname] = hosts[0].name

        print(self.experiment.to_json())
