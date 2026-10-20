from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import settings, utils
from phenix_apps.common.logger import logger

# TODO: merge tcpdump's functionality into the 'pcap' component


class TCPDump(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "tcpdump")

        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()

        with utils.mm_cc_filtered(mm):
            for vm in vms:
                hostname = vm.get("hostname", None)
                iface = vm.get("iface", None)
                options = vm.get("options", "")
                bpf_filter = vm.get("filter", "")

                if not hostname:
                    raise ValueError("no hostname provided for VM config")

                if not iface:
                    raise ValueError("no interface name provided for VM config")

                res = utils.mm_exec_wait(mm, hostname, "which tcpdump")
                if not res["stdout"]:
                    raise RuntimeError(f"tcpdump is not installed in VM {hostname}")

                logger.info(f"starting tcpdump on interface {iface} in VM {hostname}")

                if bpf_filter:
                    logger.info(
                        f"using filter {bpf_filter} for tcpdump in VM {hostname}"
                    )

                mm.cc_filter(f"name={hostname}")
                mm.cc_exec_once(f"ip link set {iface} up")
                mm.cc_background_once(
                    f"tcpdump {options} -i {iface} -U -w /dump-{iface}.pcap {bpf_filter}"
                )

        logger.info(f"Started user component: {self.name}")

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        vms = self.metadata.get("vms", None)

        mm = self.mm_init()

        convert = self.metadata.get("convertToJSON", False)

        if convert:
            logger.info("PCAP --> JSON conversion enabled... please be patient")
        else:
            logger.info("PCAP --> JSON conversion disabled")

        pcaps = []
        failures = []

        with utils.mm_cc_filtered(mm):
            for vm in vms:
                hostname = vm.get("hostname", None)
                iface = vm.get("iface", None)

                if not hostname:
                    raise ValueError("no hostname provided for VM config")

                if not iface:
                    raise ValueError("no interface name provided for VM config")

                pcap_out = f"{self.base_dir}/{hostname}-{iface}.pcap"

                # One VM without a client must not keep the others capturing.
                with utils.record_failure(failures, hostname):
                    # Leaves the cc filter on this VM's UUID for the rm below.
                    utils.mm_exec_wait(
                        mm,
                        hostname,
                        "pkill tcpdump",
                        client_grace=settings.CC_TEARDOWN_GRACE,
                    )

                    logger.info(f"copying PCAP file from node {hostname}...")

                    utils.mm_recv(
                        mm,
                        hostname,
                        f"/dump-{iface}.pcap",
                        pcap_out,
                        grace=settings.CC_TEARDOWN_GRACE,
                    )
                    mm.cc_exec_once(f"rm /dump-{iface}.pcap")

                    logger.info(f"done copying PCAP file from node {hostname}")
                    pcaps.append((hostname, pcap_out))

        if convert:
            # Once every VM's capture has stopped.
            failures += self._convert(pcaps)

        if failures:
            raise RuntimeError(f"tcpdump stop failed: {'; '.join(failures)}")

        logger.info(f"Stopped user component: {self.name}")

    def _convert(self, pcaps: list[tuple[str, str]]) -> list[str]:
        """Convert each ``(hostname, pcap)`` to JSON lines; return a failure
        for each capture that could not be converted."""
        failures = []

        for hostname, pcap_out in pcaps:
            logger.info(f"starting PCAP --> JSON conversion for node {hostname}...")

            try:
                code = utils.pcap_to_jsonl(pcap_out, f"{pcap_out}.jsonl")
            except OSError as ex:
                # Such as a missing tshark: each capture gets named.
                failures.append(f"cannot convert {pcap_out} to JSON: {ex}")
                continue

            if code:
                failures.append(f"tshark exited {code} converting {pcap_out}")
            else:
                logger.info(f"PCAP --> JSON conversion for node {hostname} complete")

        return failures


def main():
    TCPDump()


if __name__ == "__main__":
    main()
