import csv
import json
import re
import time
from pathlib import PurePath

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# snort's log_tcpdump output names its packet log <file>.<epoch time>, a new one
# each time snort starts.
PACKET_LOG = re.compile(r"snort\.log\.\d+")

# Seconds stop waits for Snort to exit after SIGINT, while it writes its final
# statistics and flushes its logs, before it copies them anyway.
EXIT_WAIT = 120


class Snort(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "snort")

        self.execute_stage()

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        hostname = self.metadata.get("hostname", "detector")
        scripts = self.metadata.get("scripts", {})
        configs = self.metadata.get("configs", [])

        mm = self.mm_init()

        config_snort = scripts.get("configSnort", None)

        if config_snort:
            script = config_snort["script"]
            executor = config_snort["executor"]
            script_name = PurePath(script).name

            logger.info(f"copying {script_name} to {hostname}")

            # Copies script to root directory of VM. For example, if script is
            # /phenix/topologies/snort-test/scripts/configure-snort.sh, then it
            # will be copied to /configure-snort.sh in the VM.
            utils.mm_send(mm, hostname, script, script_name)

            logger.info(f"running {script_name} on {hostname}")

            with utils.mm_cc_filtered(mm, f"name={hostname}"):
                utils.mm_cc_once(mm, hostname, f"{executor} /{script_name}")

        for config in configs:
            src = config["src"]
            dst = config["dst"]

            logger.info(f"copying {PurePath(src).name} to {hostname}")

            utils.mm_send(mm, hostname, src, dst)

        iface = self.metadata.get("sniffInterface", "eth0")

        logger.info(f"ensuring {iface} is up in {hostname}")

        with utils.mm_cc_filtered(mm, f"name={hostname}"):
            utils.mm_cc_once(mm, hostname, f"ip link set {iface} up")

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        hostname = self.metadata.get("hostname", "detector")
        iface = self.metadata.get("sniffInterface", "eth0")

        mm = self.mm_init()

        with utils.mm_cc_filtered(mm, f"name={hostname}"):
            logger.info(f"clearing existing Snort logs in {hostname}")

            utils.mm_cc_once(mm, hostname, "rm -rf /var/log/snort")
            utils.mm_cc_once(mm, hostname, "mkdir -p /var/log/snort")

            logger.info(f"starting Snort in {hostname}")

            utils.mm_cc_once(
                mm,
                hostname,
                f"snort -i {iface} -c /etc/snort/snort.conf",
                background=True,
            )

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        hostname = self.metadata.get("hostname", "detector")
        wait = self.metadata.get("waitDuration", 30)

        mm = self.mm_init()

        logger.info(f"waiting {wait} seconds before stopping Snort in {hostname}")

        time.sleep(wait)

        logger.info(f"stopping Snort in {hostname} (be patient... it may take a while)")

        with utils.mm_cc_filtered(mm, f"name={hostname}"):
            utils.mm_cc_once(mm, hostname, "pkill -INT snort")
            exited = utils.mm_exec_wait(
                mm,
                hostname,
                f"timeout {EXIT_WAIT} sh -c "
                "'while pgrep -x snort >/dev/null; do sleep 1; done'",
            )
            if exited["exitcode"] != 0:
                logger.warning(
                    f"Snort is still running in {hostname} {EXIT_WAIT} seconds "
                    "after SIGINT; its logs may be incomplete"
                )
            listing = utils.mm_exec_wait(mm, hostname, "ls -1 /var/log/snort")

        if listing["exitcode"] != 0:
            raise RuntimeError(
                f"snort component '{self.name}' could not list /var/log/snort in "
                f"VM {hostname}: {listing['stderr']}"
            )

        packet_logs = sorted(
            name
            for name in (listing["stdout"] or "").split()
            if PACKET_LOG.fullmatch(name)
        )

        if not packet_logs:
            raise RuntimeError(
                f"snort component '{self.name}' found no snort.log.<time> packet "
                f"log in /var/log/snort in VM {hostname}; snort.conf needs "
                "'output log_tcpdump: snort.log'"
            )

        logfiles = ["alert", *packet_logs, "snort.stats"]

        for log in logfiles:
            log_path = self.base_dir / log

            logger.info(f"copying /var/log/snort/{log} from {hostname}")
            utils.mm_recv(mm, hostname, f"/var/log/snort/{log}", str(log_path))

            if log == "snort.stats" and log_path.is_file():
                logger.info("converting snort.stats to JSON")

                lines = []

                with log_path.open() as f:
                    lines = f.readlines()

                # get rid of comment in file
                lines.pop(0)

                # remove comment field from header line
                header = lines.pop(0)
                header = header.replace("#", "")

                lines.insert(0, header)

                data = csv.DictReader(lines)

                with (self.base_dir / "snort-stats.jsonl").open("w") as f:
                    for row in data:
                        json.dump(row, f)
                        f.write("\n")

        logger.info(f"Stopped user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        hostname = self.metadata.get("hostname", "detector")
        logfiles = ["snort.log.*", "snort.err", "snort.stats"]

        mm = self.mm_init()

        with utils.mm_cc_filtered(mm, f"name={hostname}"):
            for log in logfiles:
                logger.info(f"deleting /var/log/snort/{log} from {hostname}")

                # A shell expands the packet logs' glob.
                utils.mm_cc_once(mm, hostname, f"bash -c 'rm -f /var/log/snort/{log}'")

        logger.info(f"Cleaned up user component: {self.name}")


def main():
    Snort()


if __name__ == "__main__":
    main()
