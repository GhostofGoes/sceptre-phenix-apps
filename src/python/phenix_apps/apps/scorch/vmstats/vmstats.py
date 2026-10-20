import functools
import json
import time

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class VMStats(ComponentBase):
    """
    Collects resource utilization statistics from VMs in the experiment, using the `vmstats` command.
    """

    def __init__(self):
        ComponentBase.__init__(self, "vmstats")
        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        freq = self.metadata.get("pollPeriod", 1)
        vms = self.__vm_list()

        for vm in vms:
            self.mm.vm_tag(vm, "vmstat", "1")

        self.mm.clear_cc_prefix()

        # Once per VM: minimega resends any other command to a client that
        # reconnects, which would append a second stream to /vmstat.out.
        for vm in vms:
            with utils.mm_cc_filtered(self.mm, f"name={vm} os=linux"):
                utils.mm_cc_once(
                    self.mm,
                    vm,
                    f"bash -c 'vmstat -n -t {freq} >> /vmstat.out'",
                    background=True,
                )

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        vms = self.__vm_list()

        # Each VM's tag is removed even when another VM's removal fails.
        with utils.run_cleanups(
            *(functools.partial(self._clear_tag, vm) for vm in vms)
        ):
            logger.info("killing vmstat processes")
            utils.mm_kill_process(self.mm, "vmstat=1 os=linux", "vmstat")

            time.sleep(5.0)

            for i, vm in enumerate(vms):
                logger.info(
                    f"transferring /vmstat.out from {vm} ({i + 1} of {len(vms)})"
                )
                try:
                    utils.mm_recv(
                        self.mm, vm, "/vmstat.out", str(self.base_dir / f"{vm}.out")
                    )
                except ValueError as ex:
                    raise RuntimeError(
                        f"Failed to get vmstat.out from {vm}: {ex}"
                    ) from ex

            # minimega matches a command's filter when it routes the command to
            # each client, after queuing it returns, and an exec-once command a
            # client missed is never resent. Target each VM by name, so that
            # removing the tag below cannot make the rm miss it.
            logger.info("deleting vmstat.out from VMs")
            for vm in vms:
                utils.mm_delete_file(self.mm, f"name={vm}", "/vmstat.out")

        stats = []

        logger.info("reading vmstat.out files")
        for vm in vms:
            with (self.base_dir / f"{vm}.out").open() as f:
                lines = f.readlines()

                for i, line in enumerate(lines):
                    if i in (0, 1):
                        continue

                    items = []

                    for item in line.split():
                        try:
                            items.append(int(item))
                        except ValueError:
                            items.append(item)

                    items[-2] = f"{items[-2]} {items[-1]}"
                    del items[-1]

                    stat = dict(zip(lines[1].split(), items, strict=False))
                    stat["vm_name"] = vm

                    stats.append(stat)

        stats_path = self.base_dir / "vm_stats.jsonl"
        logger.info(f"writing consolidated vmstats to {stats_path}")
        with stats_path.open("a+") as f:
            for datum in stats:
                json_record = json.dumps(datum)
                f.write(json_record + "\n")

        logger.info(f"Stopped user component: {self.name}")

    def _clear_tag(self, vm: str) -> None:
        logger.info(f"removing the vmstat tag from {vm}")
        self.mm.clear_vm_tag(vm, "vmstat")

    def __vm_list(self) -> list:
        vms = self.metadata.get("vms", None)
        compatible_os = ["linux", "centos", "rhel"]

        if vms:  # if specific vms are configured in metadata
            expanded = []

            for vm in vms:
                expanded.append(utils.expand_shorthand(vm))

            vms = [e for sub in expanded for e in sub]
        else:  # default to all linux VMs
            vms = []
            for vm in self.extract_node_names():
                node = self.extract_node(vm)

                if node.get("hardware", {}).get("os_type", "") in compatible_os:
                    vms.append(vm)
                else:
                    logger.info(
                        f"Skipping VM {vm} with incompatible os_type '{node.get('hardware', {}).get('os_type', '')}' (must be one of {compatible_os})"
                    )

        return vms


def main():
    VMStats()


if __name__ == "__main__":
    main()
