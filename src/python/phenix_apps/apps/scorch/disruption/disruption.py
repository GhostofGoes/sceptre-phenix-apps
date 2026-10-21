import timeit
from datetime import timedelta
from pathlib import Path
from time import sleep

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# Seconds the DoS script gets after its attack to write results. A dos attack
# that would end less than this (plus a second) before run_duration is
# shortened.
DOS_WRAP_UP = 60.0

# TODO: user-configurable script path + script arguments for dos
# TODO: allow dos attacks to be executed on Windows


class Disruption(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "disruption")
        self.execute_stage()

    def _kill_dos_processes(self):
        a_host = self.metadata.dos.attacker.hostname  # type: str
        logger.info(f"ensuring dos processes are killed on attacker (vm={a_host})")
        script_name = Path(self.metadata.dos.attacker.script_path).name
        utils.mm_kill_process(self.mm, f"name={a_host}", script_name)
        utils.mm_kill_process(self.mm, f"name={a_host}", "hping3")

    def _kill_phys_process(self):
        opc_host = self.metadata.physical.opc_hostname
        logger.info(
            f"killing python.exe process on {opc_host} (for physical disruption)"
        )
        utils.mm_kill_process(
            self.mm, f"name={opc_host}", "python.exe", os_type="windows"
        )

    def _dos_run_for(
        self, run_duration: float, start_delay: float, attack_duration: float
    ) -> float:
        """The DoS script's --run-for: attack_duration, shortened so that the
        start delay, the attack and DOS_WRAP_UP end a second before
        run_duration."""
        fits = run_duration - DOS_WRAP_UP - start_delay - 1.0
        if fits <= 0:
            raise ValueError(
                f"disruption component '{self.name}': run_duration {run_duration} "
                f"leaves no time for a dos attack after its start_delay {start_delay} "
                f"and the script's {DOS_WRAP_UP} s wrap-up"
            )

        if attack_duration > fits:
            logger.warning(
                f"shortening the dos attack_duration {attack_duration} to {fits} "
                f"to fit run_duration {run_duration}"
            )
            return fits

        return attack_duration

    def _build_dos_cmd(self, start_delay: float, dos_run_duration: float) -> str:
        t_ips = []
        for target in self.metadata.dos.targets:
            t_iface = target.get("interface", "eth0")
            t_ips.append(self.extract_node_ip(target.hostname, t_iface))

        return (
            f"{self.metadata.dos.attacker.script_path} "
            f"--wait-for {start_delay} "
            f"--run-for {dos_run_duration} "
            f"--target-ips {' '.join(t_ips)} "
            f"--interface {self.metadata.dos.attacker.get('interface', 'eth0')} "
            f"--results-file {self.metadata.dos.attacker.results_path}"
        )

    def _run_physical_disruption(self) -> float:
        timer_start = timeit.default_timer()

        opc_host = self.metadata.physical.opc_hostname
        opc_port = int(self.metadata.physical.get("opc_port", 4840))

        # TODO: specify --endpoint tcp://{power_provider_ip}:5555
        # Unfortunately, simply running the script path directly results in exit code -1 when running via miniccc
        # So, we're forced to use the absolute path to the python binary
        python_path = self.metadata.physical.get(
            "python_path",
            "/users/wwuser/appdata/local/programs/python/python38/python.exe",
        )
        scn_cmd = (
            f"{python_path} {self.metadata.physical.script_path} "
            f"--url opc.tcp://{opc_host}:{opc_port} "
            f"--scenario-file {self.metadata.physical.scenario_path}"
        )

        scn_timeout = float(self.metadata.physical.start_delay) + 15.0
        run_duration = float(self.metadata.run_duration)
        # ensure timeout doesn't exceed experiment duration
        if scn_timeout > run_duration:
            scn_timeout = run_duration - 1.0

        # Run physical disruption
        logger.info(
            f"Running disruption command on {opc_host}: {scn_cmd} (timeout={scn_timeout})"
        )
        scn_output = self.run_and_check_command(
            opc_host, scn_cmd, timeout=scn_timeout, debug=False
        )
        if not scn_output["stdout"]:
            raise RuntimeError(
                f"Failed to run 'cyber_physical' disruption: no stdout from command (output={scn_output})"
            )

        elapsed = timeit.default_timer() - timer_start
        logger.info(f"Finished running physical disruption in {elapsed:.2f} seconds")
        logger.info(
            f"=== Physical command output ===\n{scn_output['stdout']}\n=== End physical command output ==="
        )

        return elapsed

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        if self.metadata.current_disruption in ["dos", "cyber_physical"]:
            logger.info(
                f"Running checks for '{self.metadata.current_disruption}' disruption"
            )

            a_host = self.metadata.dos.attacker.hostname
            self.ensure_vm_running(a_host)

            for target in self.metadata.dos.targets:
                self.ensure_vm_running(target.hostname)

            self._kill_dos_processes()

            # verify hping3 and dos script are installed
            # NOTE: cannot use bash builtins like "command -v" here
            if self.loop < 2 and self.count < 2:
                logger.info(f"Checking if hping3 is installed on '{a_host}'")
                self.run_and_check_command(a_host, "hping3 --version")

                script_path = self.metadata.dos.attacker.script_path
                logger.info(f"Checking if {script_path} is installed on '{a_host}'")
                self.run_and_check_command(a_host, f"{script_path} --help")
            else:
                logger.info(
                    f"skipping tool checks since loop {self.loop} < 2 and count {self.count} < 2"
                )

            # disable all interfaces not in use by attacker
            a_iface = self.metadata.dos.attacker.get("interface", "eth0")
            a_node = self.extract_node(a_host)
            for interface in a_node.network.interfaces:
                if interface.name not in [a_iface, "MGMT", "mgmt"]:
                    logger.info(f"disabling interface {interface.name} on {a_host}")
                    with utils.mm_cc_filtered(self.mm):
                        utils.mm_exec_wait(
                            self.mm,
                            a_host,
                            f"ip link set {interface.name} down",
                            timeout=10.0,
                            poll_rate=0.5,
                        )

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        # NOTE: Because we have to wait on the dos process, or do a sleep (for baseline),
        # it doesn't make sense to split functionality across start/stop stages
        # (really, it belongs more in an "execution" stage).
        # The "art" scorch component does this as well, with everything in "start" stage.

        # record disruption start time
        base_start = utils.utc_now()

        # Round up to the next whole second.
        rounded_start = base_start.replace(microsecond=0) + timedelta(seconds=1)

        # wait until we've reached the rounded up time
        sleep((rounded_start - base_start).total_seconds())
        start_fmt = rounded_start.isoformat()
        logger.info(f"disruption start time: {start_fmt}")
        Path(self.base_dir, "disruption_start_time.txt").write_text(start_fmt)

        run_duration = float(self.metadata.run_duration)

        logger.info(
            f"Running '{self.metadata.current_disruption}' disruption (loop={self.loop}, run_duration={run_duration})"
        )

        if self.metadata.current_disruption == "baseline":
            logger.info(f"baseline: sleeping for {run_duration} seconds...")
            sleep(run_duration)

        elif self.metadata.current_disruption == "dos":
            start_delay = float(self.metadata.dos.start_delay)
            attack_duration = float(self.metadata.dos.attack_duration)

            run_for = self._dos_run_for(run_duration, start_delay, attack_duration)

            cmd = self._build_dos_cmd(start_delay, run_for)

            # The script sleeps --wait-for, attacks for --run-for, then writes
            # its results, so wait for all three.
            timeout = start_delay + run_for + DOS_WRAP_UP

            a_host = self.metadata.dos.attacker.hostname
            logger.info(f"Running DoS command on {a_host}: {cmd} (timeout={timeout})")
            timer_start = timeit.default_timer()
            output = self.run_and_check_command(
                a_host, cmd, timeout=timeout, debug=False
            )
            if not output["stdout"]:
                raise RuntimeError(
                    f"Failed to run 'dos' disruption: no stdout from command (output={output})"
                )

            elapsed = timeit.default_timer() - timer_start
            logger.info(f"Finished running DoS command in {elapsed} seconds")
            logger.info(
                f"=== Command output ===\n{output['stdout']}\n=== End command output ==="
            )

            remaining = run_duration - elapsed
            if remaining > 0.1:
                logger.info(
                    f"{remaining:.2f} seconds remaining out of configured run_duration {run_duration}, sleeping for that many seconds..."
                )
                sleep(remaining)

        elif self.metadata.current_disruption == "physical":
            # run physical attack with start delay
            physical_start_delay = float(self.metadata.physical.start_delay)

            # start delay
            logger.info(f"sleeping for {physical_start_delay} seconds")
            sleep(physical_start_delay)

            # physical duration
            elapsed = self._run_physical_disruption()

            # sleep until experiment run_duration time is up, physical ended early
            remaining = run_duration - elapsed - physical_start_delay
            if remaining > 0.1:
                logger.info(
                    f"{remaining:.2f} seconds remaining out of configured run_duration {run_duration}, sleeping for that many seconds..."
                )
                sleep(remaining)

        elif self.metadata.current_disruption == "cyber_physical":
            # get config data
            physical_start_delay = float(self.metadata.physical.start_delay)
            dos_start_delay = float(self.metadata.dos.start_delay)
            dos_attack_duration = float(self.metadata.dos.attack_duration)

            dos_run_duration = self._dos_run_for(
                run_duration, dos_start_delay, dos_attack_duration
            )

            # Kick off DoS process, have it sleep for number of seconds that puts it between line outage and load shedding
            # delay: 6.0 = 2.0 + 4.0 + 60.0 = 66.0
            # using config data dos_start_delay instead

            # run dos attack with start delay as a background process
            logger.info(
                f"Kicking off DoS script in background with start delay of {dos_start_delay}"
            )
            dos_cmd = self._build_dos_cmd(dos_start_delay, dos_run_duration)
            attacker = self.metadata.dos.attacker.hostname
            # Once: minimega resends any other command to a client that
            # reconnects, which would rerun the attack outside its window.
            with utils.mm_cc_filtered(self.mm, f"name={attacker}"):
                utils.mm_cc_once(self.mm, attacker, dos_cmd, background=True)

            # Run physical disruption
            # open breaker for generator 1
            # ... wait 2 seconds
            # open transmission line T4 (T4SE and T4RE)
            # ... wait 7 seconds
            # apply 60% load shedding to loads 5 and 6

            # physical start delay sleep
            logger.info(f"sleeping for {physical_start_delay} seconds")
            sleep(physical_start_delay)

            # run physical attack not as a background process
            physical_elapsed_time = self._run_physical_disruption()

            # calculate how early everything finished and how much sleep time is needed
            remaining_time = run_duration - physical_elapsed_time - physical_start_delay

            # sleep until experiment run_duration time is up, physical or dos ended early
            if remaining_time > 0.1:
                logger.info(
                    f"{remaining_time:.2f} seconds remaining out of configured run_duration {run_duration}, sleeping for that many seconds..."
                )
                sleep(remaining_time)
        else:
            raise ValueError(f"Invalid disruption: {self.metadata.current_disruption}")

        logger.info(f"'{self.metadata.current_disruption}' disruption complete!")

        # record disruption stop time
        stop_time = utils.utc_now().isoformat()
        logger.info(f"disruption stop time: {stop_time}")
        Path(self.base_dir, "disruption_stop_time.txt").write_text(stop_time)

        if self.metadata.current_disruption in ["dos", "cyber_physical"]:
            self._kill_dos_processes()

            logger.info("saving attacker results")
            self.recv_file(
                vm=self.metadata.dos.attacker.hostname,
                src=[
                    self.metadata.dos.attacker.results_path,
                    self.metadata.dos.attacker.script_path,
                ],
            )

        if self.metadata.current_disruption in ["physical", "cyber_physical"]:
            self._kill_phys_process()

            logger.info("saving physical disruption results")
            self.recv_file(
                vm=self.metadata.physical.opc_hostname,
                src=[
                    self.metadata.physical.script_path,
                    self.metadata.physical.results_path,
                    self.metadata.physical.scenario_path,
                    self.metadata.physical.log_path,
                ],
            )

            # verify disruption executed correctly
            logger.info("verifying disruption results")
            fname = Path(self.metadata.physical.results_path).name
            scn_path = Path(self.base_dir, fname)
            logger.info(f"disruption results path: {scn_path}")
            results = utils.read_json(scn_path)
            assert results["scenario_duration"] > 1.0
            logger.info(f"{type(results['stages'])}")
            for stage in results["stages"].values():
                if stage.get("method", "") != "opc" and not stage["successful"]:
                    raise RuntimeError(
                        f"failed disruption stage '{stage['name']}': {stage['status']}"
                    )

        logger.info(f"Started user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        if self.metadata.current_disruption in ["dos", "cyber_physical"]:
            # ensure processes are killed for an aborted run
            self._kill_dos_processes()

            # delete result file
            a_host = self.metadata.dos.attacker.hostname
            a_iface = self.metadata.dos.attacker.get("interface", "eth0")
            a_node = self.extract_node(a_host)

            with utils.mm_cc_filtered(self.mm, f"name={a_host}"):
                logger.info(f"deleting attacker results (vm={a_host})")
                self.mm.cc_exec_once(f"rm -f {self.metadata.dos.attacker.results_path}")

                # reset attacker interfaces
                for interface in a_node.network.interfaces:
                    if interface.name not in [a_iface, "MGMT", "mgmt"]:
                        logger.info(
                            f"bringing up interface {interface.name} on {a_host}"
                        )
                        self.mm.cc_exec_once(f"ip link set {interface.name} up")

            sleep(1.0)

        if self.metadata.current_disruption in ["physical", "cyber_physical"]:
            self._kill_phys_process()

            opc_host = self.metadata.physical.opc_hostname
            logger.info(f"deleting physical disruption results on {opc_host})")
            utils.mm_delete_file(
                self.mm,
                f"name={opc_host}",
                self.metadata.physical.results_path,
                os_type="windows",
            )
            utils.mm_delete_file(
                self.mm,
                f"name={opc_host}",
                self.metadata.physical.log_path,
                os_type="windows",
            )

            sleep(1.0)

        logger.info(f"Cleaned up user component: {self.name}")


def main():
    Disruption()


if __name__ == "__main__":
    main()
