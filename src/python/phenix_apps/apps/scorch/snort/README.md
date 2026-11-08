# Snort

## Metadata Options

```yaml
metadata:
  hostname: detector
  sniffInterface: eth0
  waitDuration: 30
  startupWait: 5
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

`start` checks that `sniffInterface` exists on the VM before starting Snort,
then waits `startupWait` seconds (default 5) and fails if Snort is no longer
running. Snort's startup output goes to `/var/log/snort/snort.err` on the VM.

`stop` waits `waitDuration` seconds (default 30), stops Snort with SIGINT and
waits up to 120 seconds for it to exit, then copies `alert`, every
`snort.log.<time>` packet log and `snort.stats` from `/var/log/snort`, and
writes `snort-stats.jsonl` from the statistics. The packet logs need
`output log_tcpdump: snort.log` in `snort.conf`. `cleanup` deletes them from
the VM.

## Troubleshooting

| Error | Fix |
|---|---|
| `sniffInterface <iface> not found on <host>` | Use the guest's interface name (`ip -br link` on the VM). Snort cannot sniff `any`. |
| `String should match pattern` for `sniffInterface` | Interface names are letters, digits, `_`, `.` and `-`, up to 15 characters. |
| `snort exited right after starting on <host>:` followed by Snort's output | Snort's own error is in the output, usually a bad config line, rule, or unsupported link type. |
| `no snort.log.<time> packet log in /var/log/snort on <host>` | Add `output log_tcpdump: snort.log` to `snort.conf`. |
| warning `Snort is still running in <host> 120 seconds after SIGINT` | Snort took too long to write its final statistics; the copied logs may be incomplete. |
