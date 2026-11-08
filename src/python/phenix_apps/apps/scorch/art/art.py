import subprocess
import tempfile
import time
import uuid
from typing import Final

from box import Box
from pydantic import TypeAdapter

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import FilePath
from phenix_apps.common import utils
from phenix_apps.common.logger import logger
from phenix_apps.common.settings import SCORCH_HOST_VALIDATORS

# This can be changed here to reflect your directory structure on hosts as a default.
# This is overwritten if a value is provided via goartPath
GOART_BASE: Final[str] = "/phenix/art"

# goartPath and outputPath end up in a command line on the VM.
_FILE_PATH: Final[TypeAdapter[str]] = TypeAdapter(FilePath)


class AtomicRedTeam(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "art")
        self.execute_stage()

    def _path_option(self, option: str) -> str | None:
        value = self.metadata.get(option) if self.metadata else None
        return _FILE_PATH.validate_python(value) if value else None

    def _goart_path(self, os_type):
        if goart_path := self._path_option("goartPath"):
            return goart_path
        if os_type == "windows":
            return "C:/phenix/art/goart.exe"
        return f"{GOART_BASE}/goart"

    def _tmp_path(self, os_type, filename):
        if output_path := self._path_option("outputPath"):
            return f"{output_path.rstrip('/')}/{filename}"
        if os_type == "windows":
            return f"/phenix/art/{filename}"
        return f"/tmp/{filename}"

    def _check_binary(self, mm, hostname, goart_path, os_type):
        if os_type == "windows":
            shell_cmd = f'cmd /c "if not exist {goart_path} exit 1"'
        else:
            shell_cmd = f"test -x {goart_path}"
        missing = (
            f"goart not found or not executable at {goart_path} on {hostname}. "
            "Ensure it is injected via topology."
        )
        try:
            resp = utils.mm_exec_wait(mm, hostname, shell_cmd)
        except Exception as ex:
            raise RuntimeError(missing) from ex
        # mm_exec_wait reports a command that failed by its exit code only
        if resp["exitcode"] != 0:
            raise RuntimeError(missing)

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        technique = self.metadata.get("technique", None)
        test_name = self.metadata.get("testName", None)
        test_index = self.metadata.get("testIndex", None)
        abort_on_error = self.metadata.get("abortOnError", False)
        exec_wait = float(self.metadata.get("execWaitSeconds", 5))

        if not technique:
            raise ValueError("no technique configured")

        if test_name is None and test_index is None:
            raise ValueError("no technique test configured (set testName or testIndex)")

        vms = self.metadata.get("vms", None)
        if not vms:
            raise ValueError("no vms configured")

        mm = self.mm_init()

        for vm in vms:
            hostname = vm.hostname
            os_type = self.extract_node_os_type(hostname)
            goart_path = self._goart_path(os_type)
            out_filename = f"{uuid.uuid4()!s}.json"
            out_file = self._tmp_path(os_type, out_filename)

            logger.info(f"targeting {hostname} (os_type={os_type})")
            logger.info(f"goart path: {goart_path}")
            logger.info(f"output file: {out_file}")
            logger.info(f"base_dir: {self.base_dir}")

            self._check_binary(mm, hostname, goart_path, os_type)

            args = ["-q", "-f", "json", "-t", technique, "-o", out_file]

            if test_index is not None:
                args.extend(["-i", str(test_index)])
            elif test_name is not None:
                args.extend(["-n", test_name])

            for name, value in self.metadata.get("env", {}).items():
                args.extend(["--env", f"{name}={value}"])

            for name, value in vm.get("env", {}).items():
                args.extend(["--env", f"{name}={value}"])

            for name, value in vm.get("inputs", {}).items():
                args.extend(["--input", f"{name}={value}"])

            cmd = f"{goart_path} {' '.join(args)}"

            logger.info(f"executing: {cmd}")
            resp = utils.mm_exec_wait(mm, hostname, cmd)
            if resp["exitcode"] != 0:
                msg = (
                    f"goart exited {resp['exitcode']} on {hostname}: "
                    f"{resp['stderr'] or resp['stdout'] or 'no output'}"
                )
                if abort_on_error:
                    raise RuntimeError(msg)
                logger.error(msg)
            time.sleep(exec_wait)
            logger.info(f"retrieving results: {out_file}")
            results_file = self.base_dir / f"{hostname}.json"

            try:
                utils.mm_recv(mm, hostname, out_file, results_file)
                if not results_file.is_file():
                    raise FileNotFoundError(f"{results_file} not found after transfer")
                logger.info(f"results_file path: {results_file}")
            except Exception as ex:
                raise RuntimeError(
                    f"failed to get results file from {hostname}: {ex}"
                ) from ex

            validator = self.metadata.get("validator", None)
            if validator and not SCORCH_HOST_VALIDATORS:
                logger.warning(
                    f"skipping host-side validator for {hostname}: "
                    "host-side commands are disabled by PHENIX_SCORCH_HOST_VALIDATORS=0"
                )
            elif validator:
                logger.info(f"validating results from {hostname}")

                results = Box.from_json(filename=results_file)

                with tempfile.NamedTemporaryFile("w", suffix=".sh") as tf:
                    tf.write(validator)
                    tf.flush()

                    proc = subprocess.run(
                        ["sh", tf.name, hostname],
                        input=results.Executor.ExecutedCommand.results.encode(),
                        capture_output=True,
                    )

                if proc.returncode != 0:
                    stderr = proc.stderr.decode()
                    logger.error(
                        f"results validation failed: {stderr}"
                        if stderr
                        else "results validation failed"
                    )
                    if abort_on_error:
                        raise RuntimeError("results validation failed")
                else:
                    logger.info("results are valid")

        logger.info(f"Started user component: {self.name}")


def main():
    AtomicRedTeam()


if __name__ == "__main__":
    main()
