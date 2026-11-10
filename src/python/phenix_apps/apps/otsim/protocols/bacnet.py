"""BACnet/IP server settings of an OT-sim field device.

OT-sim's BACnet module (`ot-sim-bacnet-module`) reads them from the `bacnet`
element of the device's config: the endpoint with its prefix (a BACnet/IP node
hears broadcasts on its subnet's directed broadcast address, so it needs the
prefix, not only the address), the Device object, and one object per
infrastructure variable with the message-bus tag its present-value follows.
"""

from typing import Any, Final

import lxml.etree as ET

from phenix_apps.apps.otsim.protocols.protocol import Protocol, resolve_endpoint
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger

DEFAULT_PORT: Final = 47808
# Object and device instances are 22 bits; 4194303 is the wildcard.
MAX_INSTANCE: Final = 4194302
DEFAULT_MODULE: Final = "ot-sim-bacnet-module {{config_file}}"

# The object a variable is served as unless its `bacnet.object-type` says otherwise.
DEFAULT_OBJECT_TYPE: Final = {
    "analog-read": "analog-input",
    "analog-read-write": "analog-output",
    "binary-read": "binary-input",
    "binary-read-write": "binary-output",
}
ANALOG_OBJECTS: Final = ("analog-input", "analog-output", "analog-value")
BINARY_OBJECTS: Final = ("binary-input", "binary-output", "binary-value")
MULTI_STATE: Final = "multi-state-value"
INPUT_OBJECTS: Final = ("analog-input", "binary-input")
OUTPUT_OBJECTS: Final = ("analog-output", "binary-output")

HOST_KEYS: Final = ("interface", "instance", "name", "stale-after", "module", "devices")
OBJECT_KEYS: Final = (
    "object-type",
    "instance",
    "name",
    "description",
    "units",
    "cov-increment",
    "commandable",
    "min",
    "max",
    "states",
)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _instance(value: Any, what: str) -> int:
    if not _is_int(value) or not 0 <= value <= MAX_INSTANCE:
        raise AppError(f"ot-sim: {what} must be an integer from 0 to {MAX_INSTANCE}")
    return value


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppError(f"ot-sim: {what} must be a non-empty string")
    return value


def host_settings(hostname: str, md: Any) -> dict[str, Any]:
    """The `bacnet` section of an fd-server's metadata, checked.

    Unlike `modbus` and `dnp3` it has no list form: the Device object needs an
    `instance` that is unique on the BACnet network.
    """
    where = f"fd-server '{hostname}'"

    if not isinstance(md, dict):
        raise AppError(
            f"ot-sim: {where} bacnet must be a map with `instance` and `devices`; "
            "it has no list form"
        )

    for key in md:
        if key not in HOST_KEYS:
            logger.warning(f"ot-sim: {where} sets unknown bacnet key '{key}'")

    if "instance" not in md:
        raise AppError(
            f"ot-sim: {where} sets bacnet without `instance`, the instance of its "
            "BACnet Device object"
        )

    devices = md.get("devices")
    if not isinstance(devices, list) or not devices:
        raise AppError(f"ot-sim: {where} bacnet.devices must be a non-empty list")

    settings: dict[str, Any] = {
        "instance": _instance(md["instance"], f"{where} bacnet.instance"),
        "name": _text(md.get("name", hostname), f"{where} bacnet.name"),
        "module": _text(md.get("module", DEFAULT_MODULE), f"{where} bacnet.module"),
        "devices": devices,
    }

    if "stale-after" in md:
        stale = md["stale-after"]
        if not _is_number(stale) or stale < 0:
            raise AppError(
                f"ot-sim: {where} bacnet.stale-after must be a number of seconds, "
                "0 or more"
            )
        settings["stale-after"] = stale

    return settings


def object_settings(hostname: str, reg: Any) -> dict[str, Any]:
    """The BACnet object that serves a register, from the register's `bacnet`
    settings (its infrastructure variable's, with the host's per-device
    `objects` overrides applied). Raises `AppError` naming the host and tag."""
    where = f"fd-server '{hostname}' BACnet object for '{reg.tag}'"
    md = reg.md

    for key in md:
        if key not in OBJECT_KEYS:
            logger.warning(f"ot-sim: {where} sets unknown bacnet key '{key}'")

    if reg.type not in DEFAULT_OBJECT_TYPE:
        raise AppError(
            f"ot-sim: {where}: variable type '{reg.type}' has no BACnet object; "
            f"expected one of {', '.join(DEFAULT_OBJECT_TYPE)}"
        )

    analog = reg.type.startswith("analog")
    writable = reg.type.endswith("read-write")
    kind = md.get("object-type", DEFAULT_OBJECT_TYPE[reg.type])
    allowed = (*ANALOG_OBJECTS, MULTI_STATE) if analog else BINARY_OBJECTS

    if kind not in allowed:
        raise AppError(
            f"ot-sim: {where} sets object-type '{kind}'; a variable of type "
            f"'{reg.type}' is served as one of {', '.join(allowed)}"
        )
    if kind in OUTPUT_OBJECTS and not writable:
        raise AppError(
            f"ot-sim: {where} is an output object, but the variable is "
            f"'{reg.type}': nothing would receive a command to it"
        )
    if kind in INPUT_OBJECTS and writable:
        raise AppError(
            f"ot-sim: {where} is an input object, which cannot be written, but the "
            f"variable is '{reg.type}'; use an output or value object"
        )

    # An output is always commandable; a value object is when its variable is
    # writable, unless it says otherwise.
    commandable = md.get("commandable", writable)
    if not isinstance(commandable, bool):
        raise AppError(f"ot-sim: {where} commandable must be true or false")
    if commandable and not writable:
        raise AppError(
            f"ot-sim: {where} is commandable, but the variable is '{reg.type}': "
            "nothing would receive a command to it"
        )
    if kind in OUTPUT_OBJECTS and not commandable:
        raise AppError(f"ot-sim: {where} is an output object, so it is commandable")

    obj: dict[str, Any] = {
        "type": kind,
        "tag": reg.tag,
        "name": _text(md.get("name", reg.tag), f"{where} name"),
        "commandable": commandable,
    }

    if "instance" in md:
        obj["instance"] = _instance(md["instance"], f"{where} instance")
    if "description" in md:
        obj["description"] = _text(md["description"], f"{where} description")

    if "units" in md:
        if kind not in ANALOG_OBJECTS:
            raise AppError(
                f"ot-sim: {where} sets units, which only analog objects have"
            )
        obj["units"] = _text(md["units"], f"{where} units")

    for key in ("min", "max"):
        if key in md:
            if kind not in ANALOG_OBJECTS:
                raise AppError(
                    f"ot-sim: {where} sets {key}, which only analog objects have"
                )
            if not _is_number(md[key]):
                raise AppError(f"ot-sim: {where} {key} must be a number")
            obj[key] = md[key]
    if "min" in obj and "max" in obj and obj["min"] > obj["max"]:
        raise AppError(f"ot-sim: {where} min is greater than max")

    if "cov-increment" in md:
        if kind not in ANALOG_OBJECTS:
            raise AppError(
                f"ot-sim: {where} sets cov-increment, which only analog objects have"
            )
        if not _is_number(md["cov-increment"]) or md["cov-increment"] < 0:
            raise AppError(f"ot-sim: {where} cov-increment must be a number, 0 or more")
        obj["cov-increment"] = md["cov-increment"]

    states = md.get("states")
    if kind == MULTI_STATE:
        if (
            not isinstance(states, list)
            or not states
            or not all(isinstance(state, str) and state.strip() for state in states)
        ):
            raise AppError(
                f"ot-sim: {where} is a multi-state object, so it needs `states`, a "
                "list of state texts (state 1 first)"
            )
        obj["states"] = list(states)
    elif states is not None:
        raise AppError(
            f"ot-sim: {where} sets states, which only a multi-state-value has"
        )

    return obj


def assign_instances(hostname: str, objects: list[dict[str, Any]]) -> None:
    """Give every object its instance: the one it sets, else the lowest free one
    of its object type from 1, in register order. Object identifiers and object
    names are unique within a device, so a clash fails."""
    taken: dict[str, set[int]] = {}
    names: dict[str, str] = {}

    for obj in objects:
        if obj["name"] in names:
            raise AppError(
                f"ot-sim: fd-server '{hostname}' names two BACnet objects "
                f"'{obj['name']}' ('{names[obj['name']]}' and '{obj['tag']}')"
            )
        names[obj["name"]] = obj["tag"]

        if "instance" in obj:
            used = taken.setdefault(obj["type"], set())
            if obj["instance"] in used:
                raise AppError(
                    f"ot-sim: fd-server '{hostname}' has two {obj['type']} objects "
                    f"with instance {obj['instance']} (second: '{obj['tag']}')"
                )
            used.add(obj["instance"])

    for obj in objects:
        if "instance" not in obj:
            used = taken.setdefault(obj["type"], set())
            instance = 1
            while instance in used:
                instance += 1
            used.add(instance)
            obj["instance"] = instance


def interface_prefix(node: Any, ip: str) -> int:
    """The prefix length of the topology interface that has address `ip`."""
    for iface in node.topology.network.interfaces:
        if iface.get("address") == ip:
            mask = iface.get("mask")
            if _is_int(mask) and 1 <= mask <= 30:
                return mask
            raise AppError(
                f"ot-sim: fd-server '{node.hostname}' interface '{iface.get('name')}' "
                f"has mask {mask!r}; its BACnet endpoint needs a prefix from 1 to 30"
            )
    raise AppError(
        f"ot-sim: fd-server '{node.hostname}' has no topology interface with address "
        f"{ip}; its BACnet endpoint needs that interface's prefix to hear broadcasts, "
        "so set bacnet.interface to an interface name or to one of the node's addresses"
    )


class BACnet(Protocol):
    def __init__(self):
        Protocol.__init__(self, "bacnet")

    def init_xml_root(self, mode, node, name="bacnet-server"):
        if mode != "server":
            raise AppError(
                f"ot-sim: '{node.hostname}' asks for a BACnet {mode}; only a BACnet "
                "server can be configured"
            )

        self.mode = mode
        self.hostname = node.hostname
        self.settings = host_settings(node.hostname, node.metadata.get("bacnet"))

        self.root = ET.Element("bacnet", {"name": name, "mode": mode})

        ip, port = resolve_endpoint(node, "bacnet", DEFAULT_PORT)
        prefix = interface_prefix(node, ip)
        ET.SubElement(self.root, "endpoint").text = f"{ip}/{prefix}:{port}"

        device = ET.SubElement(self.root, "device")
        ET.SubElement(device, "instance").text = str(self.settings["instance"])
        ET.SubElement(device, "name").text = self.settings["name"]

        if "stale-after" in self.settings:
            stale = ET.SubElement(self.root, "stale-after")
            stale.text = f"{self.settings['stale-after']:g}"

    def registers_to_xml(self, registers):
        objects = [object_settings(self.hostname, reg) for reg in registers]
        assign_instances(self.hostname, objects)

        for obj in objects:
            element = ET.SubElement(self.root, "object", {"type": obj["type"]})
            ET.SubElement(element, "instance").text = str(obj["instance"])
            ET.SubElement(element, "tag").text = obj["tag"]
            ET.SubElement(element, "name").text = obj["name"]

            for key in ("description", "units"):
                if key in obj:
                    ET.SubElement(element, key).text = obj[key]
            if "cov-increment" in obj:
                ET.SubElement(
                    element, "cov-increment"
                ).text = f"{obj['cov-increment']:g}"
            # The module gives every output a priority array and no input one, so
            # only a value object has to say.
            if obj["commandable"] and obj["type"] not in OUTPUT_OBJECTS:
                ET.SubElement(element, "commandable").text = "true"
            for key in ("min", "max"):
                if key in obj:
                    ET.SubElement(element, key).text = f"{obj[key]:g}"
            for state in obj.get("states", []):
                ET.SubElement(element, "state").text = state
