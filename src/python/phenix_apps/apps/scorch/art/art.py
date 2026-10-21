import os
import re
import subprocess
import time
import uuid

from box import Box

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# This can be changed here to reflect your directory structure on hosts as a default.
# This is overwritten if a value is provided via goartPath
GOART_BASE = "/phenix/art"

SAFE_PATH = re.compile(r"[A-Za-z0-9_./:-]+")


class AtomicRedTeam(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "art")
        self.execute_stage()

    def _get_os_type(self, hostname):
        node = self.extract_node(hostname)
        return node.get("hardware", {}).get("os_type", "linux").lower()

    def _path_option(self, option):
        """A path option from metadata, which ends up in a guest command line."""
        value = self.metadata.get(option)
        if value and not SAFE_PATH.fullmatch(str(value)):
            raise ValueError(
                f"art component '{self.name}': {option} '{value}' may only contain "
                "letters, digits, '_', '.', '-', ':' and '/'"
            )
        return value

    def _goart_path(self, os_type):
        goart_path = self._path_option("goartPath")
        if goart_path:
            return goart_path
        if os_type == "windows":
            return "C:/phenix/art/goart.exe"
        return f"{GOART_BASE}/goart"

    def _tmp_path(self, os_type, filename):
        output_path = self._path_option("outputPath")
        if output_path:
            return f"{output_path.rstrip('/')}/{filename}"
        if os_type == "windows":
            return f"/phenix/art/{filename}"
        return f"/tmp/{filename}"

    def _goart_word(self, what, value):
        """``value`` as one word of the goart command line, which minimega
        relays as a namespaced cc command."""
        try:
            return utils.mm_cc_arg(str(value))
        except ValueError as ex:
            raise ValueError(f"art component '{self.name}': {what} {ex}") from None

    def _goart_args(self, vm, test_name, test_index):
        """The goart arguments for ``vm`` that follow its output file."""
        word = self._goart_word
        args = []

        if test_index is not None:
            args += ["-i", word("testIndex", test_index)]
        elif test_name is not None:
            args += ["-n", word("testName", test_name)]

        for name, value in self.metadata.get("env", {}).items():
            args += ["--env", word(f"env {name}", f"{name}={value}")]

        for name, value in vm.get("env", {}).items():
            args += ["--env", word(f"{vm.hostname} env {name}", f"{name}={value}")]

        for name, value in vm.get("inputs", {}).items():
            what = f"{vm.hostname} input {name}"
            args += ["--input", word(what, f"{name}={value}")]

        return args

    def _check_binary(self, mm, hostname, goart_path, os_type):
        if os_type == "windows":
            shell_cmd = f'cmd /c "if not exist {goart_path} exit 1"'
        else:
            shell_cmd = f"test -x {goart_path}"
        try:
            # mm_exec_wait reports a failing command by its exit code only.
            with utils.mm_cc_filtered(mm):
                resp = utils.mm_exec_wait(mm, hostname, shell_cmd)
        except Exception as ex:
            raise RuntimeError(
                f"could not check for goart at {goart_path} on {hostname}: {ex}"
            ) from ex

        if resp["exitcode"] != 0:
            raise RuntimeError(
                f"goart not found or not executable at {goart_path} on {hostname}. "
                f"Ensure it is injected via topology."
            )

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

        # Every argument is checked before goart runs anywhere.
        technique_arg = self._goart_word("technique", technique)
        vm_args = [self._goart_args(vm, test_name, test_index) for vm in vms]

        mm = self.mm_init()

        for vm, args in zip(vms, vm_args, strict=True):
            hostname = vm.hostname
            os_type = self._get_os_type(hostname)
            goart_path = self._goart_path(os_type)
            out_filename = f"{uuid.uuid4()!s}.json"
            out_file = self._tmp_path(os_type, out_filename)

            logger.info(f"targeting {hostname} (os_type={os_type})")
            logger.info(f"goart path: {goart_path}")
            logger.info(f"output file: {out_file}")
            logger.info(f"base_dir: {self.base_dir}")

            self._check_binary(mm, hostname, goart_path, os_type)

            # goart_path and out_file are SAFE_PATH words, which need no quoting.
            fixed = ["-q", "-f", "json", "-t", technique_arg, "-o", out_file]
            cmd = " ".join([goart_path, *fixed, *args])

            logger.info(f"executing: {cmd}")
            with utils.mm_cc_filtered(mm):
                resp = utils.mm_exec_wait(mm, hostname, cmd)
            if resp["exitcode"] != 0:
                msg = (
                    f"goart exited {resp['exitcode']} on {hostname}: "
                    f"{resp.get('stderr') or resp.get('stdout') or 'no output'}"
                )
                if abort_on_error:
                    raise RuntimeError(msg)
                logger.error(msg)
            time.sleep(exec_wait)
            logger.info(f"retrieving results: {out_file}")
            results_file = os.path.join(self.base_dir, f"{hostname}.json")

            try:
                utils.mm_recv(mm, hostname, out_file, results_file)
                logger.info(f"results_file path: {results_file}")
                logger.info(f"results_file exists: {os.path.exists(results_file)}")
            except Exception as ex:
                raise RuntimeError(
                    f"failed to get results file from {hostname}: {ex}"
                ) from ex

            validator = self.metadata.get("validator", None)
            if validator:
                logger.info(f"validating results from {hostname}")

                tempfile = f"/tmp/{uuid.uuid4()!s}.sh"
                with open(tempfile, "w") as tf:
                    tf.write(validator)

                results = Box.from_json(filename=results_file)

                proc = subprocess.run(
                    ["sh", tempfile, hostname],
                    input=results.Executor.ExecutedCommand.results.encode(),
                    capture_output=True,
                )

                os.remove(tempfile)

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
