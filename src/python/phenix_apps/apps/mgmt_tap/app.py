import hashlib
import ipaddress

import minimega

from phenix_apps.apps import AppBase
from phenix_apps.common.logger import logger
from phenix_apps.common.utils import _mm_init, mm_compute_cmd, mm_host_info

TAP_PREFIX = "mgmt_"
# minimega does not create host taps with names longer than 14 characters.
TAP_NAME_MAX = 14
# minimega's `tap delete` error for a tap that no longer exists.
TAP_GONE = "unknown tap"


def host_tap_name(exp_name: str) -> str:
    """Return the host tap name for an experiment.

    The name is derived from a hash of the full experiment name, so experiments
    whose names share a prefix still get distinct taps on the host.
    """
    digest = hashlib.sha256(exp_name.encode("utf-8")).hexdigest()
    return TAP_PREFIX + digest[: TAP_NAME_MAX - len(TAP_PREFIX)]


class MgmtTap(AppBase):
    """Management tap user application

    This user application will create a tap on the management network of the
    experiment it is assigned to, allowing a user to copy files to and from
    machines in the network as long as the vm has a connection to the
    management network.

    E.g.
        - name: mgmt_tap
          metadata:
            subnet: 172.16.0.0/16
            vlan: MGMT_1
            bridge: phenix
    """

    DEFAULT_BRIDGE = "phenix"

    def __init__(self, name: str, stage: str, dryrun: bool = False) -> None:
        super().__init__(name, stage, dryrun)
        # Check if subnet and namespace is specified in app metadata
        self.subnet = self.metadata.get("subnet", None) if self.metadata else None
        self.vlan = self.metadata.get("vlan", "MGMT") if self.metadata else "MGMT"
        # Bridge from app metadata, falling back to the experiment default bridge
        self.bridge = self._get_bridge()
        # The full experiment name is the minimega namespace; only the host tap
        # name has a length limit.
        self.tap = host_tap_name(self.exp_name)
        self._mm = None  # minimega connection
        # Get list of mesh hosts
        self.hosts = self._get_hosts()
        if not self.hosts:
            logger.error("No hosts found in 'mgmt_tap' application!")
            raise RuntimeError("No hosts found in mgmt_tap application")

    def _get_bridge(self) -> str:
        """Determine which OVS bridge the tap should be created on.

        Priority:
            1. ``bridge`` key in the app metadata
            2. The experiment's ``spec.defaultBridge``
            3. ``phenix`` (the phenix built-in default)
        """
        bridge = self.metadata.get("bridge", None) if self.metadata else None
        if bridge:
            logger.debug(f"Using bridge '{bridge}' from app metadata")
            return bridge

        bridge = self.experiment.spec.get("defaultBridge", None)
        if bridge:
            logger.debug(f"Using experiment default bridge '{bridge}'")
            return bridge

        logger.debug(f"Falling back to bridge '{self.DEFAULT_BRIDGE}'")
        return self.DEFAULT_BRIDGE

    def _get_mm_connection(self) -> minimega.minimega:
        """Get or create minimega connection."""
        if self._mm is None:
            try:
                self._mm = _mm_init()
            except Exception as e:
                logger.error(f"Failed to connect to minimega: {e}")
                raise RuntimeError(f"Failed to connect to minimega: {e}") from e
        return self._mm

    def _get_hosts(self) -> list[str]:
        """Get list of host names from minimega."""
        try:
            mm_obj = self._get_mm_connection()
            hosts = mm_host_info(mm_obj)
            return [x["name"] for x in hosts]
        except Exception as e:
            logger.error(f"Failed to get host information: {e}")
            raise RuntimeError(f"Failed to get host information: {e}") from e

    def _tap(self, host: str, command: str) -> str:
        """Run ``tap <command>`` in the experiment's namespace on ``host``;
        return minimega's error for it, empty when it succeeded."""
        resps = mm_compute_cmd(
            self._get_mm_connection(),
            experiment=self.exp_name,
            computes=host,
            command_type="tap",
            command=command,
            ignore_error=True,
        )
        # minimega answers nothing for a host its mesh has no route to.
        if not resps:
            return "minimega got no reply from it"
        return "; ".join(resp["Error"] for resp in resps if resp.get("Error"))

    def post_start(self):
        logger.info(f"Running post_start for user application: {self.name}")
        # Create tap
        vlan = self.experiment.status.vlans.get(self.vlan, None)
        if vlan is None:
            logger.error(f"Cannot find VLAN ID for alias {self.vlan}")
            raise RuntimeError(f"Cannot find VLAN ID for alias {self.vlan}")
        if self.subnet:
            network = ipaddress.ip_network(self.subnet, strict=False)
        else:
            network = ipaddress.ip_network("172.16.0.0/16", strict=False)
        hosts = network.hosts()

        # A dry run has no real VLANs, so a tap would land untagged on the bridge.
        if self.dryrun:
            logger.info(f"Dry run: not creating host tap {self.tap} for {self.name}")
            return

        for _idx, host in enumerate(self.hosts, start=1):
            try:
                ip_addr = next(hosts)
            except StopIteration as err:
                logger.error("Ran out of IP addresses on host")
                raise RuntimeError("Ran out of IP addresses on host") from err

            ip_ = f"{ip_addr}/{network.prefixlen}"
            logger.debug(f"Creating host tap {ip_} on {host} (bridge: {self.bridge})")
            failed = f"mgmt_tap could not create host tap {self.tap} on {host}"
            try:
                error = self._tap(
                    host, f"create {vlan} bridge {self.bridge} ip {ip_} {self.tap}"
                )
            except RuntimeError as ex:
                raise RuntimeError(f"{failed}: {ex}") from ex
            if error:
                raise RuntimeError(f"{failed}: {error}")
        logger.info(f"Completed post_start for user application: {self.name}")

    def cleanup(self):
        logger.info(f"Running cleanup for user application: {self.name}")
        if self.dryrun:
            logger.info(f"Dry run: not removing host tap {self.tap} for {self.name}")
            return
        # Remove the management network tap from every host, then report the
        # hosts where that failed for any reason but the tap being gone.
        failures = []
        for host in self.hosts:
            try:
                error = self._tap(host, f"delete {self.tap}")
            except RuntimeError as ex:
                error = str(ex)
            if error and TAP_GONE not in error:
                failures.append(f"{host}: {error}")
        if failures:
            raise RuntimeError(
                f"mgmt_tap could not delete host tap {self.tap}: {'; '.join(failures)}"
            )
        logger.info(f"Completed cleanup for user application: {self.name}")
