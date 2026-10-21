import contextlib
import os
import time
from collections.abc import Iterator
from datetime import datetime

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


@contextlib.contextmanager
def _capture_settings(mm, cap) -> Iterator[None]:
    """Set the namespace's capture filter and snaplen for the capture the
    block starts, then clear both however the block exits.

    minimega applies both to every capture started while they are set, so a
    capture without its own values clears whatever was left: a blank filter is
    no filter and 0 is minimega's default snaplen.
    """
    with utils.run_cleanups(
        lambda: mm.capture_pcap_filter(utils.MM_NO_CAPTURE_FILTER),
        lambda: mm.capture_pcap_snaplen(0),
    ):
        try:
            filter_arg = utils.mm_capture_filter_arg(cap.get("filter"))
        except ValueError as ex:
            raise ValueError(f"capture filter {ex}") from None

        mm.capture_pcap_filter(filter_arg)
        mm.capture_pcap_snaplen(cap.get("snaplen") or 0)
        yield


class MM(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "mm")

        self.execute_stage()

    def configure(self):
        self.__run("configure")

    def start(self):
        self.__run("start")

    def stop(self):
        self.__run("stop")

    def cleanup(self):
        self.__run("cleanup")

    def _convert_pcaps(self, mm) -> None:
        """Convert each capture in the run directory that minimega no longer
        writes and whose ``.jsonl`` is missing or older than it.

        Raises:
            RuntimeError: naming every capture tshark failed to convert.
        """
        logger.info("Waiting for pcap transfers to head node to complete.")

        while True:
            time.sleep(2)

            if all(len(host["Tabular"]) == 0 for host in mm.file_status()):
                break

        # Every host's captures still running, those this stage left included.
        active = set()
        for resp in mm.capture():
            header = resp.get("Header") or []
            if "path" in header:
                idx = header.index("path")
                active.update(os.path.normpath(r[idx]) for r in resp["Tabular"] or [])

        failures = []

        for file in sorted(os.listdir(self.base_dir)):
            pcap_in = os.path.join(self.base_dir, file)
            json_out = f"{pcap_in}.jsonl"

            if not file.endswith(".pcap"):
                continue

            if os.path.normpath(pcap_in) in active:
                logger.info(f"not converting {file}, which is still being captured")
                continue

            if os.path.exists(json_out):
                if os.path.getmtime(json_out) >= os.path.getmtime(pcap_in):
                    continue

            logger.info(f"starting PCAP --> JSON conversion of {file}")

            try:
                code = utils.pcap_to_jsonl(pcap_in, json_out)
            except OSError as ex:
                # Such as a missing tshark: each capture gets named.
                failures.append(f"cannot convert {file} to JSON: {ex}")
                continue

            if code:
                failures.append(f"tshark exited {code} converting {file}")
            else:
                logger.info(f"PCAP --> JSON conversion of {file} complete")

        if failures:
            raise RuntimeError(
                f"PCAP --> JSON conversion failed: {'; '.join(failures)}"
            )

    def __run(self, stage: str) -> None:
        mm = self.mm_init()

        commands = self.metadata.get(stage, [])
        # Captures are converted once the stage has stopped every one it stops.
        convert = False

        for cmd in commands:
            # TODO: ensure bridge capture gets run on each namespace host

            if cmd.type == "start_capture":
                cap = cmd.get("capture", None)

                if not cap:
                    raise ValueError("no bridge capture details provided")

                bridge = cap.get("bridge", None)

                if not bridge:
                    raise ValueError("bridge to capture traffic on not provided")

                now = datetime.utcnow()
                filename = os.path.basename(
                    cap.get("filename", f"{bridge}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap")
                )

                if not filename.lower().endswith(".pcap"):
                    filename += ".pcap"

                try:
                    with _capture_settings(mm, cap):
                        logger.info(f"starting pcap capture for bridge {bridge}")
                        mm.mesh_send("all", f"shell mkdir -p {self.base_dir}")
                        mm.capture_pcap_bridge(
                            bridge, os.path.join(self.base_dir, filename)
                        )
                        logger.info(f"started pcap capture for bridge {bridge}")
                except Exception as ex:
                    raise RuntimeError(
                        f"unable to start pcap capture for bridge {bridge}: {ex}"
                    ) from ex
            elif cmd.type == "stop_capture":
                cap = cmd.get("capture", None)

                if not cap:
                    raise ValueError("no bridge capture details provided")

                bridge = cap.get("bridge", None)

                if not bridge:
                    raise ValueError("bridge to stop capture traffic on not provided")
                try:
                    logger.info(f"stopping pcap capture on bridge {bridge}")
                    mm.capture_pcap_delete_bridge(bridge)
                    logger.info(f"stopped pcap capture on bridge {bridge}")

                    mm.file_get(os.path.relpath(self.base_dir, self.root_dir))
                except Exception as ex:
                    raise RuntimeError(
                        f"unable to stop pcap capture on bridge {bridge}: {ex}"
                    ) from ex

                convert |= bool(cap.get("convert", False))
            else:
                raise ValueError(f"Unknown command type '{cmd.type}'")

        vms = self.metadata.get("vms", [])

        for vm in vms:
            commands = vm.get(stage, [])

            for cmd in commands:
                if cmd.type == "start":
                    try:
                        logger.info(f"starting VM {vm.hostname}")
                        mm.vm_start(vm.hostname)
                        logger.info(f"started VM {vm.hostname}")
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to start vm {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "stop":
                    try:
                        logger.info(f"stopping VM {vm.hostname}")
                        mm.vm_stop(vm.hostname)
                        logger.info(f"stopped VM {vm.hostname}")
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to stop vm {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "connect":
                    conn = cmd.get(cmd.type, None)

                    if not conn:
                        raise ValueError(
                            f"no connect details provided for vm {vm.hostname}"
                        )

                    iface = conn.get("interface", None)

                    if iface is None:
                        raise ValueError(
                            f"interface to connect not provided for vm {vm.hostname}"
                        )

                    vlan = conn.get("vlan", None)

                    if not vlan:
                        raise ValueError(
                            f"VLAN to connect interface {iface} to not provided for vm {vm.hostname}"
                        )

                    bridge = conn.get("bridge", None)

                    try:
                        logger.info(
                            f"connecting interface {iface} on {vm.hostname} to VLAN {vlan}"
                        )
                        mm.vm_net_connect(vm.hostname, iface, vlan, bridge)
                        logger.info(
                            f"connected interface {iface} on {vm.hostname} to VLAN {vlan}"
                        )
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to connect interface {iface} on {vm.hostname} to VLAN {vlan}: {ex}"
                        ) from ex
                elif cmd.type == "disconnect":
                    conn = cmd.get(cmd.type, None)

                    if not conn:
                        raise ValueError(
                            f"no disconnect details provided for vm {vm.hostname}"
                        )

                    iface = conn.get("interface", None)

                    if iface is None:
                        raise ValueError(
                            f"interface to disconnect not provided for vm {vm.hostname}"
                        )

                    try:
                        logger.info(f"disconnecting interface {iface} on {vm.hostname}")
                        mm.vm_net_disconnect(vm.hostname, iface)
                        logger.info(f"disconnected interface {iface} on {vm.hostname}")
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to disconnect interface {iface} on {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "start_capture":
                    cap = cmd.get("capture", None)

                    if not cap:
                        raise ValueError(
                            f"no capture details provided for vm {vm.hostname}"
                        )

                    iface = cap.get("interface", None)

                    if iface is None:
                        raise ValueError(
                            f"interface to capture traffic on not provided for vm {vm.hostname}"
                        )

                    now = utils.utc_now()
                    filename = os.path.basename(
                        cap.get(
                            "filename",
                            f"{vm.hostname}-{iface}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap",
                        )
                    )

                    if not filename.lower().endswith(".pcap"):
                        filename += ".pcap"

                    try:
                        with _capture_settings(mm, cap):
                            logger.info(
                                f"starting pcap capture for interface {iface} on {vm.hostname}"
                            )
                            mm.mesh_send("all", f"shell mkdir -p {self.base_dir}")
                            mm.capture_pcap_vm(
                                vm.hostname,
                                iface,
                                os.path.join(self.base_dir, filename),
                            )
                            logger.info(
                                f"started pcap capture for interface {iface} on {vm.hostname}"
                            )
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to start pcap capture for interface {iface} on {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "stop_capture":
                    cap = cmd.get("capture", None)
                    # Without an interface, minimega stops every capture on
                    # the VM, other components' included.
                    iface = cap.get("interface", None) if cap else None

                    try:
                        logger.info(f"stopping pcap capture(s) on VM {vm.hostname}")
                        mm.capture_pcap_delete_vm(vm.hostname, iface)
                        logger.info(f"stopped pcap capture(s) on VM {vm.hostname}")

                        mm.file_get(os.path.relpath(self.base_dir, self.root_dir))
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to stop pcap capture(s) on vm {vm.hostname}: {ex}"
                        ) from ex

                    convert |= bool(cap and cap.get("convert", False))
                else:
                    raise ValueError(
                        f"Unknown command type for VM '{vm.hostname}': {cmd.type}"
                    )

        if convert:
            logger.info("converting stopped captures to JSON")
            self._convert_pcaps(mm)


def main():
    MM()


if __name__ == "__main__":
    main()
