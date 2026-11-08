from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class Ettercap(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "ettercap")

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()

        for vm in vms:
            hostname = vm.get("hostname", None)
            iface = vm.get("iface", None)
            method = vm.get("method", "arp")
            targets = vm.get("targets", None)

            if not hostname:
                continue

            if not iface:
                logger.error(f"missing interface name for VM {hostname}")
                continue

            if not targets:
                logger.error(f"missing targets for VM {hostname}")
                continue

            logger.info(f"ensuring interface {iface} is up in VM {hostname}")

            with utils.mm_cc_filter(mm, f"name={hostname}"):
                mm.cc_exec(f"ip link set {iface} up")

                logger.info(
                    f"starting ettercap using {method} against {targets} in VM {hostname}"
                )

                mm.cc_background(f"ettercap -Tq -i {iface} -M {method} {targets}")

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()

        for vm in vms:
            hostname = vm.get("hostname", None)

            if not hostname:
                continue

            logger.info(f"stopping ettercap in VM {hostname}")

            with utils.mm_cc_filter(mm, f"name={hostname}"):
                mm.cc_exec("pkill ettercap")

        logger.info(f"Stopped user component: {self.name}")


def main():
    Ettercap()


if __name__ == "__main__":
    main()
