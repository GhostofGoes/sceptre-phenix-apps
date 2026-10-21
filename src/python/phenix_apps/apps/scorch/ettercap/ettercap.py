from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import settings, utils
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

            with utils.mm_cc_filtered(mm, f"name={hostname}"):
                logger.info(f"ensuring interface {iface} is up in VM {hostname}")

                utils.mm_cc_once(mm, hostname, f"ip link set {iface} up")

                logger.info(
                    f"starting ettercap using {method} against {targets} in VM {hostname}"
                )

                utils.mm_cc_once(
                    mm,
                    hostname,
                    f"ettercap -Tq -i {iface} -M {method} {targets}",
                    background=True,
                )

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()
        failures = []

        for vm in vms:
            hostname = vm.get("hostname", None)

            if not hostname:
                continue

            logger.info(f"stopping ettercap in VM {hostname}")

            with (
                utils.record_failure(failures, hostname),
                utils.mm_cc_filtered(mm, f"name={hostname}"),
            ):
                utils.mm_cc_once(
                    mm,
                    hostname,
                    "pkill ettercap",
                    grace=settings.CC_TEARDOWN_GRACE,
                )

        if failures:
            raise RuntimeError(f"could not stop ettercap in {'; '.join(failures)}")

        logger.info(f"Stopped user component: {self.name}")


def main():
    Ettercap()


if __name__ == "__main__":
    main()
