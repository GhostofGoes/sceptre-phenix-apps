# minimega (mm) Component

```
type: mm
exe:  phenix-scorch-component-mm
```

## Metadata Options

```yaml
metadata:
  # Commands (types) to run for a particular stage (configure, start, stop, cleanup)
  configure:
    - type: start_capture
      capture:
        bridge: phenix
        filename: capture.pcap # will be auto generated as <bridge>-<ts>.pcap if not provided
        filter: port 80 # typical BPF filter expression
        snaplen: null
    - type: stop_capture
      capture:
        bridge: phenix
        convert: true # convert to JSON (for parsing into Elastic, for example) (default is false)
  start: [] # same array of keys as above
  stop: [] # same array of keys as above
  cleanup: [] # same array of keys as above

  # Commands (types) to run for specific VMs, for a particular stage
  vms:
    - hostname: <string>
      configure:
      - type: start # can be start, stop, connect, disconnect, start_capture, stop_capture
      - type: stop
      - type: connect # can also be used to move an already connected interface
        connect:
          interface: 0 # index of interface
          vlan: FOO
          bridge: phenix # will use the same bridge previously connected to (if moving) if not provided
      - type: disconnect
        disconnect:
          interface: 0 # index of interface
      - type: start_capture
        capture:
          interface: 0
          filename: capture.pcap # will be auto generated as <host>-<iface>-<ts>.pcap if not provided
          filter: port 80 # typical BPF filter expression
          snaplen: null
      - type: stop_capture
        capture:
          interface: 0 # without it, stops every capture on the VM, other components' included
          convert: true # convert to JSON (for parsing into Elastic, for example) (default is false)
      start: [] # same array of keys as above
      stop: [] # same array of keys as above
      cleanup: [] # same array of keys as above
```

minimega keeps one capture filter and snaplen per namespace for every capture started while they are set. `start_capture` sets the capture's `filter` and `snaplen`, or clears ones another component left when the capture has none, and clears both once the capture has started or failed to start. It clears the filter by setting a blank one, `' '`, which matches every packet, because minimega ignores an empty filter sent in a namespace; `capture pcap filter` then reports `" "`. A `filter` with a non-printable character other than a tab or line break, or with a backslash, a quote or `#` but no space, fails `start_capture` before it is set, as minimega cannot relay it intact.

Stopping one VM interface's capture needs minimega 3.3.0 or later, for both the minimega server and its Python module.

When a `stop_capture` in a stage sets `convert`, the component converts, with tshark on the phenix host, once the stage has run all its commands and minimega's file transfers have finished: every capture in the run directory that minimega no longer writes and whose `.pcap.jsonl` is missing or older than it. A capture still running, such as one the stage does not stop, is left for a later stage. If tshark is missing or fails, the stage fails naming each capture, and no partial `.pcap.jsonl` is left.
