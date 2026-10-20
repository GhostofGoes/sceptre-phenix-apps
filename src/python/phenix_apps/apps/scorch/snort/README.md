# Snort

## Metadata Options

```yaml
metadata:
  hostname: detector
  sniffInterface: eth0
  waitDuration: 30
  configs:
  - name: snort
    src: /phenix/topologies/snort-test/configs/snort.conf
    dst: /etc/snort/snort.conf
  - name: emotet
    src: /phenix/topologies/snort-test/configs/emotet.rules
    dst: /etc/snort/rules/emotet.rules
  scripts:
    configSnort:
      executor: bash
      script: /phenix/topologies/snort-test/scripts/configure-snort.sh
```

## Collected Files

The `stop` stage stops Snort with SIGINT after `waitDuration` seconds, waits up
to 120 seconds for it to exit, and copies these files from `/var/log/snort` in
the VM:

- `alert`: the alerts, from `output alert_fast: alert` or another alert output
  writing that file.
- `snort.log.<time>`: every packet log from `output log_tcpdump: snort.log`,
  which Snort names with the epoch time it started. At least one must exist.
- `snort.stats`: the `perfmonitor` statistics, from
  `preprocessor perfmonitor: ... file /var/log/snort/snort.stats`, also
  converted to `snort-stats.jsonl`.

The `snort.conf` in `configs` must write all three, with
`config logdir: /var/log/snort`. The `cleanup` stage deletes the packet logs and
`snort.stats` from the VM.
