# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
- **Ignition App**: New app that configures an Inductive Automation Ignition Gateway 8.3 SCADA master

### Added
- **OT-sim App**: `fd-client` DNP3 masters use `helics.scan-rate` when it is set explicitly.
- **Ignition App**: Add linux support.
- **Ignition App**: Tags pick up the ot-sim devices and variables behind each DNP3 point (ex: `rtu/cap1/voltage`).
- **Ignition App**: DNP3 poll rate is configurable per class and outstation.
- **Ignition App**: Add support for sending DNP3 Analog Output setpoint control commands.
- **OT-sim App**: `points.Outstations` exposes the DNP3 points and listen endpoint of any outstation host for other apps; `Register` records its device, type, variable and protocol section.
- **Wind Turbine Scale Plugin**: Artifact-generation regression tests and documentation linking to the companion [complete example in sceptre-phenix-topologies](https://github.com/sandialabs/sceptre-phenix-topologies/tree/main/renewables/wind/wind-scale) (sandialabs/sceptre-phenix-apps#95).
- **SCEPTRE App**: Pre-flight scenario validation: one pydantic model, run before either stage, reporting every problem at once with the host and field.
- **SCEPTRE App**: Stage accounting in the logs: a scenario inventory by device type, and what each handler produced.
- **SCEPTRE App**: Files in `<assetDir>/injects/override/` that match no injection are reported as probable typos.
- **SCEPTRE App**: Test suite (128 tests), two of them characterization tests over both stages and all 310 infrastructure/device-type/protocol combinations, plus `apps/sceptre/README.md`.
- **SCORCH**: Pydantic metadata models for components (#160).
- **SCORCH**: `phenix-scorch-validate` checks component metadata.

### Changed
- **OT-sim App**: DNP3 address assignment is a module function (`protocols.dnp3.assign_addresses`)
- **Build System**: `Mako>=1.3.10`, `requests>=2.32.4` (security advisories).
- **Build System**: Require `minimega>=3.3.0` for per-interface capture stops.
- **OT-sim App**: Rename client `.connected` tags to `<protocol>-client-<host>.connected` (breaking).
- **OT-sim/Wind Turbine Apps**: Fail on half-configured CPU API TLS (breaking).
- **OT-sim/Wind Turbine Apps**: Host `cpu-module` must keep app-level TLS (breaking).
- **OT-sim App**: Analog Modbus points default to two-register `int32` (breaking).
- **mgmt_tap App**: Name host taps `mgmt_<hash>`; failed creates fail (breaking).
- **mgmt_tap App**: Fail a cleanup that leaves a tap (breaking).
- **Mirror App**: Exit 1 on failure or unknown stages (breaking).
- **OT-sim App**: Reject unknown `fep` `downstream` protocols (breaking).
- **SCORCH mm/tcpdump**: Fail on tshark errors, after every stop (breaking).
- **SCORCH ettercap/trafficgen/tcpdump**: Teardown waits `PHENIX_CC_TEARDOWN_GRACE`, 20 s, per client (breaking).
- **SCEPTRE App**: Register numbering state is per `FieldDeviceConfig` instead of class-level mutable state on `Register`; numbering is no longer order-dependent across configs and the test suite runs safely in parallel. Output is unchanged.
- **SCEPTRE App**: `configure()` and `pre_start()` are stage classes, `ConfigureStage` and `PreStart`, sharing pre-start state through `PreStartState`.
- **SCEPTRE App**: The device-type table is `configs/infrastructures.yaml`; adding a device type needs no code change.
- **SCEPTRE App**: Injections are declared with `Sceptre.inject()`, and all of them in the configure stage.
- **Common**: `utils.abs_path()` always returns a `Path`.
- **Common**: `mm_compute_cmd` raises on socket failures, even with `ignore_error` (breaking).
- **SCEPTRE App**: Type annotations on every app function, `Final` on module constants.
- **SCEPTRE App**: Validation failures raise `error.AppError` instead of calling `sys.exit(1)`, matching the app contract.
- **SCEPTRE App**: `metadata.simulator` matches case-insensitively in both stages, as validation already did; a miscased name used to silently get the default config.
- **Build System**: `package-data` ships the `mydesigner` SCADA tree and infrastructure table.

### Removed
- **SCEPTRE App**: The `reg_config` manual register-map path. It was dead code: the app never populated it, so every device always took the automatic numbering branch. Output is unchanged.
- **SCEPTRE App**: SunSpec has been burned away by the SCORCHing heat of 3000 Suns and thus no longer exists in this repo.

### Fixed
- **Common Utils**: fix cc commands parsing to be resilient to header changes.
- **OT-sim App**: `fd-server` hosts ignored the app-level `infrastructure` setting, so their protocol registers didn't match the tags the I/O module published.
- **Common Utils**: `mm_exec_wait` and `mm_get_cc_responses` split `cc responses` output on whole header lines; stderr no longer swallows stdout, and output containing `/` is no longer truncated.
- **OT-sim App**: A DNP3 master without a configured `scan-rate` (FEPs without app-level `helics` metadata, and every `fd-client`) raised `AttributeError`. The `<scan-rate>` element is now omitted, so ot-sim uses its own default ([#72](https://github.com/sandialabs/sceptre-phenix-apps/issues/72)).
- **Wind Turbine Scale Plugin**: Stage an optional `container_template.rootfs_source` on each generated VM outside the containers' shared weather volume; mount Node-RED flows at their configured container path. Reject densities that split a turbine's private network across VMs.
- **SCEPTRE App**: With more than one PowerWorld provider, only the last one's `hil_tags` reached the object list, and only the last one's `objects.txt` was written. Tags now aggregate across providers and every PowerWorld provider gets the combined `objects.txt`.
- **SCEPTRE App**: `fep` hosts raised `TypeError`, built without the required `device_subtype`.
- **SCEPTRE App**: Per-device register overrides raised `RuntimeError` in `SceptreMetadataParser`, which popped keys while iterating a live dict view.
- **SCEPTRE App**: A `power-transmission` inverter raised `TypeError`, passing `infrastructure` twice into `Device()`.
- **SCEPTRE App**: A `fep` without a mgmt interface raised `UnboundLocalError`, or reused the previous fep's endpoints.
- **SCEPTRE App**: A historian on a subnet with no OPC server was configured with an unrelated OPC's tag list and no address to collect from. It now gets no tags and a warning naming the subnet.
- **HELICS App**: Track sub-brokers by resolved `ip:port`, fixing pre-start `KeyError`.
- **OT-sim App**: Fail pre-start on broker script clash with helics.
- **SCEPTRE App**: Close Modbus RTU client blocks as `</modbus-client>`.
- **SCEPTRE App**: Detect Ignition hosts by label or type everywhere.
- **Caldera App**: Allow server interfaces without a `gateway`.
- **OT-sim App**: Serve `fep` points with their served protocol's settings.
- **OT-sim App**: Clients poll exactly what a `fep` serves.
- **OT-sim App**: Inject only configured CPU API TLS files.
- **OT-sim App**: Raise `AppError`, naming the host, for missing `helics.broker`.
- **OT-sim App**: Name `fep` Modbus clients uniquely, as `modbus-client-<upstream host>`.
- **SCORCH collector**: Tolerate a null `loop`.
- **SCORCH collector**: Collect per type from its own loop's components.
- **SCORCH collector**: Read Linux miniccc logs from `/var/log/miniccc.log`, then `/miniccc.log`.
- **SCORCH collector**: Accept components that omit `type`.
- **SCORCH pcap**: Stop only its own captures; needs minimega 3.3.0.
- **SCORCH pcap**: Set or clear the filter before capturing.
- **SCORCH mm**: Quote multi-word filters; reset filter and `snaplen` afterwards.
- **SCORCH art**: Fail before running when a VM lacks `goart`.
- **SCORCH art**: Honor `goartPath`, `outputPath` and `execWaitSeconds` options.
- **SCORCH disruption**: Wait for the `dos` `start_delay`, attack and results.
- **SCORCH trafficgen**: Read malware `rate` and `probability` from `malwareClient`.
- **SCORCH ssh**: Fail the stage on failed commands or fetches.
- **SCORCH erspan**: Fail configure at the first failing `ovs-vsctl` command.
- **SCORCH erspan**: Add and remove only its `m0` OVS mirror.
- **SCORCH hoststats**: Fail start without `background: true` instead of hanging.
- **SCORCH kafka**: Run listener with component's Python; detect failed starts.
- **Apps**: Dry runs log JSON to stderr when `PHENIX_LOG_FILE=stderr`.
- **Mirror App**: `cleanup` tolerates missing status.
- **Mirror App**: Pass unknown top-level experiment fields through unchanged.
- **single-node Scheduler**: Schedule unscheduled VMs on the first cluster host.
- **mgmt_tap App**: Give experiments sharing a name prefix separate taps.
- **SCORCH tcpdump**: Clear the cc filter after start and stop.
- **SCORCH iperf**: Servers write the JSON results that stop collects.
- **SCORCH iperf**: Redirect stderr with `2>&1`, not `2>1`.
- **SCORCH vmstats**: Remove the `vmstat=1` VM tag at stop.
- **SCORCH vmstats**: Clear the cc filter even when `pkill` fails.
- **SCORCH cc**: Clear `exec` cc filters after each command.
- **SCORCH hoststats**: Flush promptly on SIGTERM; fail on poll errors.
- **SCORCH snort**: Collect and delete every `snort.log.<time>` packet log.
- **SCORCH disruption**: Round start times across hour boundaries without `ValueError`.
- **SCORCH**: `mm_kill_process`, `mm_delete_file` and `ComponentBase` checks clear cc filters.
- **SCORCH snort**: Clear the cc filter after each stage's commands.
- **SCORCH ettercap**: Clear each VM's cc filter after its commands.
- **SCORCH trafficgen**: Clear the cc filter after each script command.
- **SCORCH iperf**: Clear the cc filter after each queued command.
- **SCORCH disruption**: Clear the attacker's cc filter after each command.
- **SCORCH opcexport**: Clear the OPC host's cc filter after commands.
- **SCORCH rtds/providerdata**: Clear the provider's cc filter after each check.
- **SCORCH art**: Clear the cc filter after each goart command.
- **SCORCH caldera**: Clear the server's cc filter after each stage.
- **Scale App**: Clear the cc filter after each post-start send.
- **OT-sim App**: Treat a null app-level `cpu-module.api-endpoint` as no default.
- **OT-sim App**: A null `fep` `downstream` means `dnp3`.
- **OT-sim App**: Serve each point a `fep` polls once.
- **OT-sim App**: Accept a null `modbus` setting on analog variables.
- **OT-sim App**: Combine host and app-level `logs` without crashing.
- **OT-sim App**: Treat a null `cpu-module` or `cpu-module.api` as unset.
- **Wind Turbine App**: Inject the CPU API TLS files.
- **mgmt_tap App**: Create taps on hosts sharing the headnode's prefix.
- **mgmt_tap App**: Recognize the headnode under custom hostname suffixes.
- **mgmt_tap App**: Leave host taps alone in dry runs.
- **SCORCH mm**: Reset capture settings after a rejected `snaplen`.
- **SCORCH mm**: `stop_capture` stops only the named VM interface.
- **SCORCH pcap**: Reset `snaplen` after starting captures.
- **SCORCH pcap**: Stop every capture before reporting a failed one.
- **Common**: Escape backslashes and quotes in capture filters.
- **SCORCH opcexport**: Delete the Windows log with `del`, not `rm`.
- **Common**: Windows file deletes no longer hang multi-host namespaces.
- **SCORCH disruption**: Shorten, never lengthen, a `dos` attack to fit.
- **SCORCH art**: Pass each `testName`, `env` and `inputs` value whole.
- **SCORCH art**: Report goart failures; `abortOnError` fails the stage.
- **SCORCH vmstats**: Delete `/vmstat.out` by name; always remove the tag.
- **SCORCH**: Queue snort, ettercap, trafficgen, tcpdump and iperf commands once.
- **SCORCH snort**: Wait for Snort to exit before copying logs.
- **SCORCH iperf**: Clear the cc prefix right after queuing.
- **SCORCH**: Canceled foreground stages run `finally` blocks on fresh connections.
- **SCORCH pcap**: Find a `disruption` component that omits its `type`.
- **single-node Scheduler**: Skip external nodes; fail without cluster hosts.
- **SCORCH erspan**: Clean up its mirror by output port.
- **SCORCH mm**: Convert captures only once minimega stops writing them.
- **SCORCH ettercap/trafficgen/tcpdump**: Teardown reaches every VM when one fails.
- **SCORCH pcap/mm/vmstats**: Run every reset; keep the original error.
- **SCORCH disruption/vmstats**: Launch the DoS and vmstat once.
- **SCORCH hoststats**: Honor a SIGTERM that arrives before start runs.
- **SCORCH kafka**: A canceled configure kills its just-started listener.

### Security
- **Common**: New `validate_hostname()` (phenix v2026.10.02 rules) and `safe_join()` guard hostnames and paths built from metadata; `mm_send()`/`mm_recv()` stay inside the miniccc mount. **Breaking:** rejects `_`, 1-char, all-digit, `all` and `phenix` hostnames.
- **Apps**: Scale, wind turbine and Ignition names are restricted; protonuke and wireguard reject embedded newlines; wireguard configs are `0600`, sceptre startup scripts `0755`.
- **SCORCH**: `cc`, `ssh` and `providerdata` transfers stay inside the run directory.
- **SCORCH mm/tcpdump**: Run tshark without a shell for capture names.
- **Wireguard App**: Write the private-key config `0600` from creation.
- **SCORCH pcap/collector**: Run Wireshark tools and phenix without a shell.
- **SCORCH art/mm/pcap**: Refuse arguments that crash or hang minimega.

## [2.0.0] - 2026-03-04

### Changed
- **Logging**: Updated `AppBase` to enforce the new App Contract, emitting structured JSON logs to `stderr` for aggregation by the Core daemon.
- **Error Handling**: `AppBase` now captures full tracebacks in a structured `traceback` field using `logger.exception` instead of printing raw text to stderr.
- **Scale App**: Disabled `rich` progress bars on stderr during production runs to prevent JSON log corruption.
- **Helics App**: Replaced `sys.exit(1)` with exceptions to ensure proper JSON error logging.
- **Scorch App**: Replaced `sys.exit(1)` with exceptions to ensure JSON status files are written on failure.
- **Scorch App**: Removed raw stdout/stderr printing. All logs now go to `stderr` as structured JSON.
- **Scorch App**: Fixed internal log capturing for status files by using a custom log sink instead of monkey-patching `logger.log`.
- **Build System**: Standardized Makefiles with consistent targets (`help`, `all`, `test`, `lint`, `format`, `clean`) and improved help output.
- **Mirror App**: Refactored `main.go` to reduce complexity and improve testability.
- **Mirror App**: Fixed linting errors and updated to use `log/slog` for structured logging.
- **Go**: Updated Go version requirement to 1.24.

## [1.0.0]

### Added
- **New `scale` Application**: A new Phenix app (`phenix-app-scale`) designed for high-volume, large-scale simulations using a plugin architecture.
- **`scale` App Plugins**:
  - **`builtin` Plugin**: For generic infrastructure scaling. Supports direct VM counts (`count`) and calculated VM counts based on container density (`containers` and `containers_per_node`).
  - **`wind_turbine` Plugin**: A domain-specific plugin to simulate wind farms using OT-Sim. It automatically generates the 6-container architecture for each turbine and handles all internal configuration (Modbus, DNP3, Logic).
- **Comprehensive Documentation**:
  - Added `README.md` files for the `scale` app and each of its plugins (`builtin`, `wind_turbine`).
  - Included diagrams to visualize application and plugin architectures.
  - Added detailed instructions for testing and performing dry-runs.
- **Unit and Integration Tests**:
  - Added extensive `pytest` tests for the new `scale` app and its plugins.
  - Added tests for the refactored `AppBase` class.
- **Makefile `dry-run` Target**: Added a new `make dry-run` target to easily test the `scale` app's configuration and post-start stages with sample input files.
- **Dev Dependencies**: Added `pytest-mock` to support advanced unit testing patterns.
- **Migration Guide**: Created `docs/app_migration_guide.md` to assist developers in updating existing apps to the new `AppBase` structure.

### Changed
- **`AppBase` Refactoring (Breaking Change)**:
  - The `AppBase.__init__` constructor now handles argument parsing and reading experiment data from `stdin`, simplifying app initialization.
  - A new `AppBase.main()` class method is now the standard entry point for all Phenix apps, reducing boilerplate code in `__main__.py` files.
  - All existing apps (`sceptre`, `wind_turbine`, etc.) have been updated to conform to this new pattern.

### Deprecated
- The standalone `phenix-app-wind-turbine` is now deprecated. All of its functionality has been migrated to the `scale` app's `wind_turbine` plugin, which offers superior scalability and configuration management.

## [0.2.0]

- Initial release with various applications including `sceptre`, `helics`, and `ot-sim`.
