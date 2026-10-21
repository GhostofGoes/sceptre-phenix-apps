# collector Component

Collects and processes data from cyber-physical experiments and Scorch components.

```
type:   collector
exe:    phenix-scorch-component-collector
stages: stop
```

## Notes
- Supported components: `rtds`, `providerdata`, `vmstats`, `hoststats`, `iperf`, `disruption`, `qos`, `pcap`
- When its loop uses more than one component of a type, it collects from the one listed first in `components` and logs a warning naming the one it ignores.

### Known issues
- This component is currently highly dependent on the `rtds` and `disruption` components. It assumes that the `rtds` component is configured to use Elasticsearch, and will use the Elasticsearch configuration from the `rtds` component's metadata.
- This component currently has a lot of assumptions baked in for the HARMONIE environment and should be used with caution.
- It collects only from the components in the stages of the loop it runs in: the run's own stages, or those of the nested loop it is listed in. phenix names a component's output directory by its loop depth and count only, so the collector cannot find what another loop wrote. It skips each supported component that runs only in another loop, and logs `not collecting from '<name>': it does not run in loop <loop> of run <run>, where collector '<collector>' runs`. To collect from it, list it in a stage of the collector's loop.

### Features
The role of the collector should be to:
- Gather all relevant files together into a defined structure
- Collect any additional data from running environment
    - Copying files from VMs (miniccc logs)
    - Running VM metadata
    - phenix configs (scenario, topology, experiment)
    - phenix metadata, including version
    - minimega version
    - scorch metadata
- Validate all expected data sources exist
- Check data validity
- Check data integrity (files parsable, etc.)

## Metadata Options

```yaml
metadata:
  collect_iperf: <bool>  # (Optional) If iperf data should be collected and processed. Default: false
  collect_miniccc: <bool>  # (Optional) If miniccc log files from VMs should be collected, if available. Default: false
                           # Linux VMs: /var/log/miniccc.log, else /miniccc.log. Windows VMs: /minimega/miniccc.log. Routers are skipped.
  generate_csv: <bool>  # (Optional) Enable generation of the consolidated CSV with experiment results. Default: true
```

## Example Configuration

```yaml
components:
  - name: collector-example
    type: collector
    metadata:
      collect_iperf: false
      collect_miniccc: false
      generate_csv: false
```
