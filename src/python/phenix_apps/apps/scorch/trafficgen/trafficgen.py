import time
from pathlib import PurePath

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import settings, utils
from phenix_apps.common.logger import logger


class TrafficGen(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "trafficgen")

        self.execute_stage()

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        scripts = self.metadata.get("scripts", {})
        targets = self.metadata.get("targets", None)

        mm = self.mm_init()

        for target in targets:
            hostname = target.get("hostname", "traffic-server")
            script = scripts["trafficServer"]
            script_name = PurePath(script).name

            logger.info(f"copying {script_name} to {hostname}")

            # Copies script to root directory of VM. For example, if script is
            # /phenix/topologies/trafficgen-test/scripts/traffic-server.py, then
            # it will be copied to /traffic-server.py in the VM.
            utils.mm_send(mm, hostname, script, script_name)

            background = target.get("backgroundClient", None)

            if background:
                hostname = background.get("hostname", "background-gen")
                script = scripts["backgroundGen"]
                script_name = PurePath(script).name

                logger.info(f"copying {script_name} to {hostname}")

                utils.mm_send(mm, hostname, script, script_name)
            else:
                logger.info("no background client configured for target {hostname}")

            malware = target.get("malwareClient", None)

            if malware:
                hostname = malware.get("hostname", "malware-gen")
                script = scripts["malwareGen"]
                script_name = PurePath(script).name

                logger.info(f"copying {script_name} to {hostname}")

                utils.mm_send(mm, hostname, script, script_name)
            else:
                logger.info("no malware client configured for target {hostname}")

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        scripts = self.metadata.get("scripts", {})
        targets = self.metadata.get("targets", None)

        mm = self.mm_init()

        for target in targets:
            target_host = target.get("hostname", "traffic-server")
            target_iface = target.get("interface", "IF0")
            target_script_name = PurePath(scripts["trafficServer"]).name
            target_ip = self.extract_node_ip(target_host, target_iface)
            duration = target.get("duration", 5)

            background = target.get("backgroundClient", None)

            if background:
                hostname = background.get("hostname", "background-gen")
                rate = background.get("rate", 10000)
                prob = background.get("probability", 0.01)
                script_name = PurePath(scripts["backgroundGen"]).name

                logger.info(f"running {target_script_name} on {target_host}")

                with utils.mm_cc_filtered(mm, f"name={target_host}"):
                    utils.mm_cc_once(
                        mm,
                        target_host,
                        f"python3 /{target_script_name}",
                        background=True,
                    )

                logger.info(f"running {script_name} on {hostname}")

                with utils.mm_cc_filtered(mm, f"name={hostname}"):
                    utils.mm_cc_once(
                        mm,
                        hostname,
                        f"python3 /{script_name} --ip {target_ip} "
                        f"--rate {rate} --duration {duration} --probability {prob}",
                        background=True,
                    )
            else:
                logger.info("no background client configured for target {target_host}")

            malware = target.get("malwareClient", None)

            if malware:
                hostname = malware.get("hostname", "malware-gen")
                rate = malware.get("rate", 20)
                prob = malware.get("probability", 1.25)
                script_name = PurePath(scripts["malwareGen"]).name

                logger.info(f"running {script_name} on {hostname}")

                with utils.mm_cc_filtered(mm, f"name={hostname}"):
                    utils.mm_cc_once(
                        mm,
                        hostname,
                        f"python3 /{script_name} --ip {target_ip} "
                        f"--rate {rate} --duration {duration} --probability {prob}",
                        background=True,
                    )
            else:
                logger.info("no malware client configured for target {target_host}")

            logger.info(
                f"pausing for {int(duration) + 5}s while traffic is generated for {target_host}"
            )

            time.sleep(int(duration) + 5)

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        scripts = self.metadata.get("scripts", {})
        targets = self.metadata.get("targets", None)

        mm = self.mm_init()
        failures = []

        for target in targets:
            target_host = target.get("hostname", "traffic-server")
            target_script_name = PurePath(scripts["trafficServer"]).name

            background = target.get("backgroundClient", None)

            if background:
                hostname = background.get("hostname", "background-gen")
                script_name = PurePath(scripts["backgroundGen"]).name

                logger.info(f"killing {target_script_name} on {target_host}")

                self._teardown(
                    mm, failures, target_host, f"pkill -f {target_script_name}"
                )

                logger.info(f"killing {script_name} on {hostname}")

                self._teardown(mm, failures, hostname, f"pkill -f {script_name}")
            else:
                logger.info("no background client configured for target {target_host}")

            malware = target.get("malwareClient", None)

            if malware:
                hostname = malware.get("hostname", "malware-gen")
                script_name = PurePath(scripts["malwareGen"]).name

                logger.info(f"killing {script_name} on {hostname}")

                self._teardown(mm, failures, hostname, f"pkill -f {script_name}")
            else:
                logger.info("no malware client configured for target {target_host}")

        if failures:
            raise RuntimeError(f"could not stop traffic in {'; '.join(failures)}")

        logger.info(f"Stopped user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        scripts = self.metadata.get("scripts", {})
        targets = self.metadata.get("targets", None)

        mm = self.mm_init()
        failures = []

        for target in targets:
            target_host = target.get("hostname", "traffic-server")
            target_script_name = PurePath(scripts["trafficServer"]).name

            background = target.get("backgroundClient", None)

            if background:
                hostname = background.get("hostname", "background-gen")
                script_name = PurePath(scripts["backgroundGen"]).name

                logger.info(f"deleting /{target_script_name} on {target_host}")

                self._teardown(mm, failures, target_host, f"rm /{target_script_name}")

                logger.info(f"deleting /{script_name} on {hostname}")

                self._teardown(mm, failures, hostname, f"rm /{script_name}")
            else:
                logger.info("no background client configured for target {target_host}")

            malware = target.get("malwareClient", None)

            if malware:
                hostname = malware.get("hostname", "malware-gen")
                script_name = PurePath(scripts["malwareGen"]).name

                logger.info(f"deleting /{script_name} on {hostname}")

                self._teardown(mm, failures, hostname, f"rm /{script_name}")
            else:
                logger.info("no malware client configured for target {target_host}")

        if failures:
            raise RuntimeError(
                f"could not delete traffic scripts in {'; '.join(failures)}"
            )

        logger.info(f"Cleaned up user component: {self.name}")

    @staticmethod
    def _teardown(mm, failures, hostname, cmd):
        """Queue ``cmd`` once in ``hostname``, recording a failure in
        ``failures`` instead of raising, so that every VM is reached."""
        with (
            utils.record_failure(failures, hostname),
            utils.mm_cc_filtered(mm, f"name={hostname}"),
        ):
            utils.mm_cc_once(mm, hostname, cmd, grace=settings.CC_TEARDOWN_GRACE)


def main():
    TrafficGen()


if __name__ == "__main__":
    main()
