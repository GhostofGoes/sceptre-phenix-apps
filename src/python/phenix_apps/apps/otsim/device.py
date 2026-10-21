import lxml.etree as ET

from phenix_apps.apps.otsim.infrastructure import merge_infrastructure_with_default
from phenix_apps.apps.otsim.protocols.dnp3 import DNP3
from phenix_apps.apps.otsim.protocols.modbus import Modbus
from phenix_apps.common.error import AppError

# Modbus data type for analog points whose infrastructure mapping sets none.
DEFAULT_ANALOG_DATA_TYPE = "int32"

# The protocols a FEP can serve its polled points over.
DOWNSTREAM_PROTOCOLS = ("dnp3", "modbus")


def protocol_md(variable, proto):
    """The settings `proto` uses for an infrastructure variable."""
    # YAML `modbus:` with every setting commented out is null.
    md = variable.get(proto) or {}

    if proto == "modbus" and variable["type"] in ("analog-read", "analog-read-write"):
        # OT-sim's uint16 default corrupts negative values and anything above
        # 655.35 at scaling 2.
        md = {"data-type": DEFAULT_ANALOG_DATA_TYPE, **md}

    return md


class Register:
    """One protocol register. `device`, `device_type`, `variable` and
    `protocol` record where an infrastructure register came from so other
    apps can give its point a meaningful name; `var_type` is that variable's
    infrastructure mapping, so a FEP can serve the point over another protocol
    with that protocol's settings."""

    def __init__(
        self,
        typ,
        tag,
        md=None,
        device=None,
        device_type=None,
        variable=None,
        protocol=None,
        var_type=None,
    ):
        if md is None:
            md = {}
        self.type = typ
        self.tag = tag
        self.md = md
        self.device = device
        self.device_type = device_type
        self.variable = variable
        self.protocol = protocol
        self.var_type = var_type if var_type is not None else {"type": typ}

    def for_protocol(self, proto):
        """This point with the settings `proto` uses for it."""
        return Register(
            self.type,
            self.tag,
            protocol_md(self.var_type, proto),
            device=self.device,
            device_type=self.device_type,
            variable=self.variable,
            protocol=self.protocol,
            var_type=self.var_type,
        )


class Device:
    def __init__(self, node, configs=None, default_infra="power-distribution"):
        if configs is None:
            configs = {}
        self.node = node
        self.md = node.get("metadata", {})
        self.infra = self.md.get("infrastructure", default_infra)

        # The points the device serves, by protocol: what its clients poll.
        self.registers = {}
        self.processed = False
        self.configs = configs


class FEP(Device):
    def __init__(self, node, configs=None):
        if configs is None:
            configs = {}
        Device.__init__(self, node, configs)

        downstream = self.md.get("downstream") or []

        if not isinstance(downstream, list):
            downstream = [downstream]

        unknown = [proto for proto in downstream if proto not in DOWNSTREAM_PROTOCOLS]
        if unknown:
            raise AppError(
                f"ot-sim: fep '{node['hostname']}' sets downstream "
                f"{', '.join(repr(proto) for proto in unknown)}, but a fep serves "
                f"only {' and '.join(DOWNSTREAM_PROTOCOLS)}"
            )

        # Default to using DNP3 for downstream side.
        self.downstream = downstream or ["dnp3"]

    def process(self, devices):
        if self.processed:
            return

        # TODO: track upstream device registers by device name (which should be
        # unique across device types) so downstream server doesn't include a
        # register twice if an upstream server provides access to the same device
        # across multiple protocols. Would need to figure out how to handle what
        # client to default to using if multiple protocols provide access upstream.

        # TODO: support configuring which registers are available downstream. Right
        # now, all registers available upstream are made available downstream. Users
        # may want to only make a subset of registers available downstream.

        polled = {}

        # Support legacy `connected_rtus` key if `upstream` key is not present.
        for name in self.md.get("upstream", self.md.get("connected_rtus", [])):
            device = devices[name]
            assert device

            device.process(devices)

            for proto, regs in device.registers.items():
                polled.setdefault(proto, []).extend(regs)

        # Serve each tag once: an upstream fep serves every point over each of
        # its downstream protocols, and a device may list a point under more
        # than one.
        registers = []
        tags = set()
        for reg in (reg for regs in polled.values() for reg in regs):
            if reg.tag not in tags:
                tags.add(reg.tag)
                registers.append(reg)

        for proto in DOWNSTREAM_PROTOCOLS:
            if proto in self.downstream:
                self.registers[proto] = [reg.for_protocol(proto) for reg in registers]

        self.processed = True

    def configure(self, config, known):
        protos = {}

        # Support legacy `connected_rtus` key if `upstream` key is not present.
        for upstream in self.md.get("upstream", self.md.get("connected_rtus", [])):
            device = known[upstream]

            if "modbus" in device.registers:
                client = Modbus()
                # OT-sim's Modbus server ignores statuses, and its client
                # updates, from a sender with its own name, so a client sharing
                # the server's default name would neither feed the server nor get
                # the writes it receives.
                client.init_xml_root(
                    "client", device.node, name=f"modbus-client-{upstream}"
                )
                client.registers_to_xml(device.registers["modbus"])

                config.append_to_root(client.root)
                protos["modbus"] = True

            if "dnp3" in device.registers:
                client = DNP3()
                # Each client publishes `<name>.connected`.
                client.init_xml_root(
                    "client", device.node, name=f"dnp3-client-{upstream}"
                )
                client.init_master_xml(self.configs.get("scan-rate"))
                client.registers_to_xml(device.registers["dnp3"])

                config.append_to_root(client.root)
                protos["dnp3"] = True

        if "dnp3" in self.registers:
            server = DNP3()
            server.init_xml_root("server", self.node)
            server.init_outstation_xml()
            server.registers_to_xml(self.registers["dnp3"])

            config.append_to_root(server.root)
            protos["dnp3"] = True

        if "modbus" in self.registers:
            server = Modbus()
            server.init_xml_root("server", self.node)
            server.registers_to_xml(self.registers["modbus"])

            config.append_to_root(server.root)
            protos["modbus"] = True

        if "dnp3" in protos:
            module = ET.Element("module", {"name": "dnp3"})
            module.text = "ot-sim-dnp3-module {{config_file}}"

            config.append_to_cpu(module)

        if "modbus" in protos:
            module = ET.Element("module", {"name": "modbus"})
            module.text = "ot-sim-modbus-module {{config_file}}"

            config.append_to_cpu(module)


class FieldDeviceServer(Device):
    def __init__(self, node, default_infra="power-distribution"):
        Device.__init__(self, node, default_infra=default_infra)

    def process(self, mappings):
        if self.processed:
            return

        # merge provided mappings (if any) with default mappings (if any)
        mapping = merge_infrastructure_with_default(
            self.infra, mappings.get(self.infra, {})
        )

        if "dnp3" in self.md:
            if "dnp3" not in self.registers:
                self.registers["dnp3"] = []

            # md['dnp3'] can either be a list of infrastructure devices configured to
            # be monitored using the DNP3 protocol or a dictionary that contains a
            # `devices` key that holds the list. Each entry includes a name that's
            # used for tags and a type that references an infrastructure type.
            if isinstance(self.md["dnp3"], dict):
                devices = self.md["dnp3"]["devices"]
            else:
                devices = self.md["dnp3"]

            for fd in devices:
                assert fd["type"] in mapping
                device = mapping[fd["type"]]

                # device name might be prefixed with HELICS federate name
                parts = fd["name"].split("/")
                name = parts[1] if len(parts) > 1 else parts[0]

                for var, var_type in device.items():
                    # We care about static and event variable types in the DNP3 protocol
                    # module, so if the variable type is a string convert it to a
                    # dictionary so the rest of the code can be the same when checking to
                    # see if variable types were provided.
                    if isinstance(var_type, str):
                        var_type = {"type": var_type}

                    reg = Register(
                        var_type["type"],
                        f"{name}.{var}",
                        protocol_md(var_type, "dnp3"),
                        device=name,
                        device_type=fd["type"],
                        variable=var,
                        protocol="dnp3",
                        var_type=var_type,
                    )
                    self.registers["dnp3"].append(reg)

        if "modbus" in self.md:
            if "modbus" not in self.registers:
                self.registers["modbus"] = []

            # md['modbus'] can either be a list of infrastructure devices configured
            # to be monitored using the DNP3 protocol or a dictionary that contains a
            # `devices` key that holds the list. Each entry includes a name that's
            # used for tags and a type that references an infrastructure type.
            if isinstance(self.md["modbus"], dict):
                devices = self.md["modbus"]["devices"]
            else:
                devices = self.md["modbus"]

            for fd in devices:
                assert fd["type"] in mapping
                device = mapping[fd["type"]]

                # device name might be prefixed with HELICS federate name
                parts = fd["name"].split("/")
                name = parts[1] if len(parts) > 1 else parts[0]

                for var, var_type in device.items():
                    # We care about scaling in the Modbus protocol module, so if the
                    # variable type is a string convert it to a dictionary so the rest of
                    # the code can be the same when checking to see if a scaling factor
                    # was provided.
                    if isinstance(var_type, str):
                        var_type = {"type": var_type}

                    reg = Register(
                        var_type["type"],
                        f"{name}.{var}",
                        protocol_md(var_type, "modbus"),
                        device=name,
                        device_type=fd["type"],
                        variable=var,
                        protocol="modbus",
                        var_type=var_type,
                    )
                    self.registers["modbus"].append(reg)

        self.processed = True

    def configure(self, config):
        if "dnp3" in self.registers:
            server = DNP3()
            server.init_xml_root("server", self.node)
            server.init_outstation_xml()
            server.registers_to_xml(self.registers["dnp3"])

            module = ET.Element("module", {"name": "dnp3"})
            module.text = "ot-sim-dnp3-module {{config_file}}"

            config.append_to_root(server.root)
            config.append_to_cpu(module)

        if "modbus" in self.registers:
            server = Modbus()
            server.init_xml_root("server", self.node)
            server.registers_to_xml(self.registers["modbus"])

            module = ET.Element("module", {"name": "modbus"})
            module.text = "ot-sim-modbus-module {{config_file}}"

            config.append_to_root(server.root)
            config.append_to_cpu(module)


class FieldDeviceClient(Device):
    def __init__(self, node, configs=None):
        if configs is None:
            configs = {}
        Device.__init__(self, node, configs)

    def process(self, devices):
        if self.processed:
            return

        for name in self.md.get("connected_rtus", []):
            device = devices[name]
            assert device

            device.process(devices)

        self.processed = True

    def configure(self, config, known):
        protos = {}

        for downstream in self.md.get("connected_rtus", []):
            device = known[downstream]

            # Each client publishes `<name>.connected`, so each polled device
            # gets clients of its own name.
            if "modbus" in device.registers:
                client = Modbus()
                client.init_xml_root(
                    "client", device.node, name=f"modbus-client-{downstream}"
                )
                client.registers_to_xml(device.registers["modbus"])

                config.append_to_root(client.root)
                protos["modbus"] = True

            if "dnp3" in device.registers:
                client = DNP3()
                client.init_xml_root(
                    "client", device.node, name=f"dnp3-client-{downstream}"
                )
                client.init_master_xml(self.configs.get("scan-rate"))
                client.registers_to_xml(device.registers["dnp3"])

                config.append_to_root(client.root)
                protos["dnp3"] = True

        if "modbus" in protos:
            module = ET.Element("module", {"name": "modbus"})
            module.text = "ot-sim-modbus-module {{config_file}}"

            config.append_to_cpu(module)

        if "dnp3" in protos:
            module = ET.Element("module", {"name": "dnp3"})
            module.text = "ot-sim-dnp3-module {{config_file}}"

            config.append_to_cpu(module)
