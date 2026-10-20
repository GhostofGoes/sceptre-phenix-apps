import lxml.etree as ET

from phenix_apps.apps.otsim.protocols.protocol import Protocol, resolve_endpoint

# Registers each OT-sim Modbus data type spans (OT-sim modbus/util/register.go).
# Without a data-type attribute OT-sim reads and writes uint16.
REGISTER_WIDTH = {
    "int16": 1,
    "uint16": 1,
    "int32": 2,
    "uint32": 2,
    "int64": 4,
    "uint64": 4,
    "float": 2,
    "double": 4,
}


class Modbus(Protocol):
    def __init__(self):
        Protocol.__init__(self, "modbus")

        self.addrs = {"coil": 1, "discrete": 10001, "input": 30001, "holding": 40001}

    def init_xml_root(self, mode, node, name="modbus-outstation"):
        self.mode = mode

        self.root = ET.Element("modbus", {"name": name, "mode": mode})
        endpoint = ET.SubElement(self.root, "endpoint")

        ip, port = resolve_endpoint(node, "modbus", 502)
        endpoint.text = f"{ip}:{port}"

    def registers_to_xml(self, registers):
        for reg in registers:
            if reg.type == "binary-read-write":
                typ = "coil"
                coil = ET.SubElement(self.root, "register", {"type": typ})

                addr = ET.SubElement(coil, "address")
                addr.text = str(self.addrs[typ])

                self.addrs[typ] += 1

                tag = ET.SubElement(coil, "tag")
                tag.text = reg.tag
            elif reg.type == "binary-read":
                typ = "discrete"
                discrete = ET.SubElement(self.root, "register", {"type": typ})

                addr = ET.SubElement(discrete, "address")
                addr.text = str(self.addrs[typ])

                self.addrs[typ] += 1

                tag = ET.SubElement(discrete, "tag")
                tag.text = reg.tag
            elif reg.type in ("analog-read", "analog-read-write"):
                typ = "input" if reg.type == "analog-read" else "holding"
                attrs = {"type": typ}

                data_type = reg.md.get("data-type")
                if data_type is not None:
                    if data_type not in REGISTER_WIDTH:
                        raise ValueError(
                            f"Modbus register '{reg.tag}' has data-type "
                            f"'{data_type}'; expected one of "
                            f"{', '.join(REGISTER_WIDTH)}"
                        )
                    attrs["data-type"] = data_type

                register = ET.SubElement(self.root, "register", attrs)

                addr = ET.SubElement(register, "address")
                addr.text = str(self.addrs[typ])

                self.addrs[typ] += REGISTER_WIDTH.get(data_type, 1)

                tag = ET.SubElement(register, "tag")
                tag.text = reg.tag

                # OT-sim ignores scaling for floating-point registers.
                if "scaling" in reg.md and data_type not in ("float", "double"):
                    scale = reg.md["scaling"]

                    scaling = ET.SubElement(register, "scaling")
                    scaling.text = str(
                        int(scale) * -1 if self.mode == "server" else int(scale)
                    )
