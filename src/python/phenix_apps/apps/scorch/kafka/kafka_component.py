import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common.logger import logger

# Seconds to wait before checking that the listener did not exit at once, e.g.
# on a missing module or an unreachable broker.
LISTENER_STARTUP_GRACE = 2.0


class Kafka(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "kafka")

        # generate a universal uid so that multiple kafka components can run simultaneously
        config_str = json.dumps(self.metadata, sort_keys=True)
        component_uuid = uuid.uuid5(
            uuid.NAMESPACE_DNS, f"{self.exp_name}-{self.name}-{config_str}"
        )

        self.pid_file = (
            f"/tmp/phenix-scorch-kafka-{self.exp_name}-{component_uuid.hex}.pid"
        )
        self.execute_stage()

    def configure(self):
        # if the deterministic PID file already exists, don't configure the component again
        if os.path.exists(self.pid_file):
            logger.info(f"User component {self.name} already configured, skipping")
            return

        logger.info(f"Configuring user component: {self.name}")

        # get kafka ip addresses and concatenate them into a list of
        # strings in format ip:port
        kafka_ips = []
        kafka_endpoints = self.metadata.get(
            "kafka_endpoints", [{"ip": "127.0.0.1", "port": "9092"}]
        )
        wait_duration_seconds = self.metadata.get("wait_duration_seconds", 305)

        for item in kafka_endpoints:
            kafka_ips.append(item["ip"] + ":" + item["port"])

        logger.info(f"Kafka_ips list: {kafka_ips}")

        topics = self.metadata.get("topics", [])
        csv_bool = self.metadata.get("csv", True)  # if false output a JSON

        # get and output the output directory to the logger
        output_dir = self.base_dir
        logger.info(f"Output Directory: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)
        if csv_bool:
            self.path = os.path.join(output_dir, f"{self.name}_output.csv")
        else:
            self.path = os.path.join(output_dir, f"{self.name}_output.ndjson")

        kafka_ips_str = ",".join(kafka_ips)
        topics_str = json.dumps(topics)

        # pass the inputs to the python file (which we execute as a
        # separate process). It needs this interpreter's kafka-python, which
        # the python3 on PATH may lack, e.g. when phenix-apps is in a venv.
        executable = str(Path(Path(__file__).parent, "kafka_listener.py"))
        command = [
            sys.executable,
            executable,
            str(csv_bool),
            self.path,
            kafka_ips_str,
            topics_str,
            self.exp_name,
            str(wait_duration_seconds),
        ]

        # The listener outlives this process, so it logs to a file.
        log_path = Path(output_dir, "kafka_listener.log")
        logger.info(f"Kafka listener log: {log_path}")

        try:
            with log_path.open("ab") as log:
                response = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
        except Exception as e:
            raise RuntimeError(f"Error running listener executable. See: {e}") from e

        try:
            time.sleep(LISTENER_STARTUP_GRACE)
        except BaseException:
            # A canceled stage has written no PID file for cleanup to find the
            # listener by, so it must not leave one running.
            response.kill()
            raise

        status = response.poll()
        if status is not None:
            raise RuntimeError(
                f"kafka listener exited with status {status} right after starting; "
                f"see {log_path}"
            )

        # write PID to a file so that it can be found
        # and killed later
        self._create_pid_file(response.pid)

    def _create_pid_file(self, pid):
        # writes PID to unique .pid file under /tmp directory
        try:
            with open(self.pid_file, "w+") as f:
                f.write(str(pid))
        except Exception as e:
            logger.error(
                f"Could not create PID file. Listener process at PID {pid} "
                f"will not terminate automatically when experiment ends. "
                f"See: {e}"
            )

    def _consume_pid_file(self):
        # reads and deletes PID file, returns PID
        pid = 0
        try:
            with open(self.pid_file) as f:
                pid = int(f.readline().rstrip())
            os.remove(self.pid_file)
            return pid
        except Exception as e:
            logger.error(
                f"Error consuming PID file.Listener process at PID {pid} will not be terminated. See: {e}"
            )
            return pid

    def cleanup(self):
        # stops listener executable
        pid = self._consume_pid_file()

        if not pid:
            logger.info("No PID, component already cleaned up")
            exit()

        try:
            os.kill(pid, 9)
            logger.info(f"Cleaned up user component: {self.name}")
        except Exception as e:
            logger.error(f"Error terminating listener at PID {pid}. See: {e}")


def main():
    Kafka()


if __name__ == "__main__":
    main()
