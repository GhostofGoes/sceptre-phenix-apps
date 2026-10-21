from pathlib import Path

import lxml.etree as ET

from phenix_apps.common.error import AppError

# The CPU API endpoint when the metadata sets none.
DEFAULT_API_ENDPOINT = "0.0.0.0:9101"

# CPU API TLS metadata fields, which are also the config elements, and where
# each file is injected.
API_TLS_FILES = {
    "tls-key": "/etc/ot-sim/certs/api.key",
    "tls-certificate": "/etc/ot-sim/certs/api.crt",
    "ca-certificate": "/etc/ot-sim/certs/api.ca.crt",
}


def add_api_tls(api, md, injects, where):
    """Point the CPU API at the TLS files `md` sets and inject them.

    OT-sim serves TLS only with both a key and a certificate, and uses a CA
    certificate only then, so either alone, or a CA certificate without both,
    fails, naming `where` the API is configured; an unset field gets neither an
    element nor an injection.
    """
    fields = []

    key, certificate = md.get("tls-key"), md.get("tls-certificate")
    if bool(key) != bool(certificate):
        have, missing = (
            ("tls-key", "tls-certificate") if key else ("tls-certificate", "tls-key")
        )
        raise AppError(
            f"ot-sim: {where} cpu-module.api sets {have} without {missing}; "
            "OT-sim serves the API over TLS only with both"
        )

    if key and certificate:
        fields += ["tls-key", "tls-certificate"]

    if md.get("ca-certificate"):
        if not fields:
            raise AppError(
                f"ot-sim: {where} cpu-module.api sets ca-certificate without "
                "tls-key and tls-certificate; OT-sim checks client certificates "
                "only on an API it serves over TLS"
            )

        fields.append("ca-certificate")

    for field in fields:
        ET.SubElement(api, field).text = API_TLS_FILES[field]
        injects.append({"src": md[field], "dst": API_TLS_FILES[field]})


class Config:
    def __init__(self, md=None):
        if md is None:
            md = {}
        if "message-bus" in md:
            self.default_pull = md["message-bus"].get(
                "pull-endpoint", "tcp://127.0.0.1:1234"
            )
            self.default_pub = md["message-bus"].get(
                "pub-endpoint", "tcp://127.0.0.1:5678"
            )
        else:
            self.default_pull = "tcp://127.0.0.1:1234"
            self.default_pub = "tcp://127.0.0.1:5678"

        # None when the app-level `api-endpoint` is null, which turns the CPU
        # API off for every host that does not set its own.
        self.default_api = {}
        self.default_api_tls = {}

        # A null `cpu-module` or `api`, every key of it commented out, is unset.
        cpu_module = md.get("cpu-module") or {}

        if cpu_module.get("api") is not None:
            self.default_api["endpoint"] = cpu_module["api"].get(
                "endpoint", DEFAULT_API_ENDPOINT
            )
            self.default_api_tls = cpu_module["api"]
        else:
            endpoint = cpu_module.get("api-endpoint", DEFAULT_API_ENDPOINT)

            if endpoint:
                self.default_api["endpoint"] = endpoint
            else:  # allow disablement of API endpoint if `api-endpoint` is null
                self.default_api = None

        if "logs" in md:
            self.logs = {}

            if "elastic" in md["logs"]:
                if "endpoint" in md["logs"]["elastic"]:
                    self.logs["elastic"] = {
                        "default_endpoint": md["logs"]["elastic"].get(
                            "endpoint", "http://localhost:9200"
                        ),
                        "default_index": md["logs"]["elastic"].get(
                            "index", "ot-sim-logs"
                        ),
                    }
            elif "loki" in md["logs"]:
                self.logs["loki"] = {"default_endpoint": md["logs"]["loki"]}
            else:
                self.logs = None
        else:
            self.logs = None

        if "ground-truth-module" in md:
            self.ground_truth = {}

            if "elastic" in md["ground-truth-module"]:
                self.ground_truth["elastic"] = {
                    "default_endpoint": md["ground-truth-module"]["elastic"].get(
                        "endpoint", "http://localhost:9200"
                    ),
                    "default_index_base_name": md["ground-truth-module"]["elastic"].get(
                        "index-base-name", "ot-sim"
                    ),
                }
            else:
                self.ground_truth = None
        else:
            self.ground_truth = None

    def _check_host_keeps_api_tls(self, cpu_module, hostname):
        """Refuse a host `cpu-module` that would serve the CPU API over plain
        HTTP while the app-level `cpu-module.api` sets TLS files.

        A host's `cpu-module` replaces the app's, TLS files included, so the
        host must name its own `tls-key` and `tls-certificate`, null for plain
        HTTP, unless it turns its API off.
        """
        app_tls = self.default_api_tls.get("tls-key") and self.default_api_tls.get(
            "tls-certificate"
        )
        if not app_tls:
            return

        host_api = cpu_module.get("api")

        if host_api is None:
            default = self.default_api["endpoint"] if self.default_api else None
            if not cpu_module.get("api-endpoint", default):
                return
        elif "tls-key" in host_api and "tls-certificate" in host_api:
            return

        raise AppError(
            f"ot-sim: host '{hostname}' sets its own cpu-module without "
            "cpu-module.api tls-key and tls-certificate, so it would serve the "
            "API over plain HTTP although the app-level cpu-module.api sets "
            "them; set them for the host, or set both to null for plain HTTP"
        )

    def init_xml_root(self, md=None, hostname=None):
        """Start the config for a host with metadata `md`, named `hostname` in
        errors, and return the files the host needs injected."""
        if md is None:
            md = {}
        self.root = ET.Element("ot-sim")

        injects = []

        msgbus = ET.SubElement(self.root, "message-bus")
        pull = ET.SubElement(msgbus, "pull-endpoint")
        pub = ET.SubElement(msgbus, "pub-endpoint")

        if "message-bus" in md:
            pull.text = md["message-bus"].get("pull-endpoint", self.default_pull)
            pub.text = md["message-bus"].get("pub-endpoint", self.default_pub)
        else:
            pull.text = self.default_pull
            pub.text = self.default_pub

        self.cpu = ET.SubElement(self.root, "cpu")

        # A host without its own endpoint takes the app's, none when the app
        # turned the API off.
        default_endpoint = self.default_api["endpoint"] if self.default_api else None

        # A null `cpu-module` or `api`, every key of it commented out, is unset.
        if md.get("cpu-module") is not None:
            host_api = md["cpu-module"].get("api")

            self._check_host_keeps_api_tls(md["cpu-module"], hostname)

            if host_api is not None:
                api = ET.SubElement(self.cpu, "api")

                endpoint = ET.SubElement(api, "endpoint")
                endpoint.text = host_api.get(
                    "endpoint", default_endpoint or DEFAULT_API_ENDPOINT
                )

                add_api_tls(api, host_api, injects, f"host '{hostname}'")
            else:
                endpoint = md["cpu-module"].get("api-endpoint", default_endpoint)

                if (
                    endpoint
                ):  # allow disablement of API endpoint if `api-endpoint` is null
                    api = ET.SubElement(self.cpu, "api")

                    apiendpoint = ET.SubElement(api, "endpoint")
                    apiendpoint.text = endpoint
        elif self.default_api:
            api = ET.SubElement(self.cpu, "api")

            apiendpoint = ET.SubElement(api, "endpoint")
            apiendpoint.text = self.default_api["endpoint"]

            add_api_tls(api, self.default_api_tls, injects, "the app-level")

        if "logs" in md:
            logs = None

            def logs_element():
                # One <logs> for whichever of the host's and the app's
                # settings apply.
                nonlocal logs
                if logs is None:
                    logs = ET.SubElement(self.cpu, "logs")
                return logs

            if "elastic" in md["logs"]:
                if "endpoint" in md["logs"]["elastic"]:
                    index = md["logs"]["elastic"].get("index")

                    if not index:
                        try:
                            index = self.logs["elastic"]["default_index"]
                        except (KeyError, TypeError):
                            index = None

                    if index:
                        es = ET.SubElement(logs_element(), "elastic", {"index": index})
                    else:
                        es = ET.SubElement(logs_element(), "elastic")

                    es.text = md["logs"]["elastic"]["endpoint"]
            elif self.logs and "elastic" in self.logs:
                es = ET.SubElement(
                    logs_element(),
                    "elastic",
                    {"index": self.logs["elastic"]["default_index"]},
                )
                es.text = self.logs["elastic"]["default_endpoint"]

            if "loki" in md["logs"]:
                loki = ET.SubElement(logs_element(), "loki")

                loki.text = md["logs"]["loki"]
            elif self.logs and "loki" in self.logs:
                loki = ET.SubElement(logs_element(), "loki")
                loki.text = self.logs["loki"]["default_endpoint"]
        elif self.logs:
            logs = ET.SubElement(self.cpu, "logs")

            if "elastic" in self.logs:
                es = ET.SubElement(
                    logs, "elastic", {"index": self.logs["elastic"]["default_index"]}
                )
                es.text = self.logs["elastic"]["default_endpoint"]

            if "loki" in self.logs:
                loki = ET.SubElement(logs, "loki")
                loki.text = self.logs["loki"]["default_endpoint"]

        backplane = ET.SubElement(self.cpu, "module", {"name": "backplane"})
        backplane.text = "ot-sim-message-bus {{config_file}}"

        # Might be null in config, which means disable it for this particular device
        # even though it's enabled globally.
        if (
            "ground-truth-module" in md
            and md["ground-truth-module"]
            and "elastic" in md["ground-truth-module"]
        ):
            gt = ET.SubElement(self.root, "ground-truth")
            es = ET.SubElement(gt, "elastic")
            ep = ET.SubElement(es, "endpoint")
            idx = ET.SubElement(es, "index-base-name")

            ep.text = md["ground-truth-module"]["elastic"].get(
                "endpoint", self.ground_truth["elastic"]["default_endpoint"]
            )
            idx.text = md["ground-truth-module"]["elastic"].get(
                "index-base-name",
                self.ground_truth["elastic"]["default_index_base_name"],
            )

            for name, value in (
                md["ground-truth-module"]["elastic"].get("labels", {}).items()
            ):
                ET.SubElement(es, "label", {"name": name}).text = value

            ET.SubElement(
                self.cpu, "module", {"name": "ground-truth"}
            ).text = "ot-sim-ground-truth-module {{config_file}}"
        elif self.ground_truth and "elastic" in self.ground_truth:
            gt = ET.SubElement(self.root, "ground-truth")
            es = ET.SubElement(gt, "elastic")
            ep = ET.SubElement(es, "endpoint")
            idx = ET.SubElement(es, "index-base-name")

            ep.text = self.ground_truth["elastic"]["default_endpoint"]
            idx.text = self.ground_truth["elastic"]["default_index_base_name"]

            ET.SubElement(
                self.cpu, "module", {"name": "ground-truth"}
            ).text = "ot-sim-ground-truth-module {{config_file}}"

        return injects

    def append_to_root(self, child):
        self.root.append(child)

    def append_to_cpu(self, child):
        self.cpu.append(child)

    def to_file(self, path):
        with Path(path).open("w") as f:
            f.write(ET.tostring(self.root, pretty_print=True).decode())
