# hoststats Component

Collects statistics on minimega host(s). Runs in the background during Scorch execution. Results are written to `host_stats.jsonl` and ingested into Elasticsearch with Filebeat (if `filebeat.inputs` is configured for the component).

```
type:   hoststats
exe:    phenix-scorch-component-hoststats
stages: start, stop
```

The component must set `background: true` (next to `name` and `type`, not in
`metadata`). Its start stage polls until phenix stops it at the stop stage, which
phenix only does for background components; without it, start fails at once
rather than blocking the pipeline.

phenix stops the start stage with SIGTERM and kills it 10 seconds later. On
SIGTERM, start stops polling at once, however long `pollPeriod` is, writes what
it has buffered to `host_stats.jsonl`, and ends. A poll that fails, for example
because minimega is unreachable, ends start with that error.

## Metadata Options

```yaml
metadata:
  pollPeriod: <int>  # (Optional) How often to read statistics, in seconds. Defaults to 5 (statistics will be measured every 5 seconds).
  flushPeriod: <int>  # (Optional) How often buffer is flushed. Defaults to the value of 'pollPeriod'.
  filebeat.inputs:
    - type: filestream
      id: hoststats-input
      enabled: true
      paths:
        - host_stats.jsonl
      parsers:
        - ndjson:
            target: "hoststats"
            add_error_key: true
      processors:
        - timestamp:
            field: hoststats.timestamp
            layouts:
              - 'UNIX_MS'
            test:
              - 1709228988101
        - drop_fields:
            fields:
              - hoststats.timestamp  # this gets parsed and copied to @timestamp, no reason to keep around
              - input.type  # drop 'input.type', since it will always be 'filestream'
```

The `filebeat.inputs` section above can be blindly copied into user's own config
and used as-is, or users can choose to change target field names if the ones
used above aren't suitable.

## Example Configuration

```yaml
components:
  - name: hoststats-example
    type: hoststats
    background: true
    metadata:
      pollPeriod: 5
      flushPeriod: 5
      filebeat.inputs:
        - type: filestream
          id: hoststats-input
          enabled: true
          paths:
            - host_stats.jsonl
          parsers:
            - ndjson:
                target: "hoststats"
                add_error_key: true
          processors:
            - timestamp:
                field: hoststats.timestamp
                layouts:
                  - 'UNIX_MS'
                test:
                  - 1709228988101
            - drop_fields:
                fields:
                  - hoststats.timestamp
                  - input.type  # this will always be 'filestream'
```
