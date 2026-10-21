# pcap Component

Collects PCAPs from VMs via minimega's `capture pcap` API.

```
type:   pcap
exe:    phenix-scorch-component-pcap
stages: start, stop
```

The stop stage stops each capture by VM interface (`capture pcap delete vm
<name> <interface index>`), which needs minimega 3.3.0 or later, for both the
minimega server and its Python module. It tries every capture before it fails
on the ones minimega could not stop.

## Metadata Options

```yaml
metadata:
  convertToJSON: <bool>  # (Optional) Create .jsonl (JSON Lines) files from PCAPs using tshark. Default: false
  create_merged_pcap: <bool>  # (Optional) Merge all PCAP files into a single file using 'mergecap'. Default: false
  dedupe: <bool>  # (Optional) Remove duplicate packets from merged PCAP. Only applicable if 'create_merged_pcap' is 'true'. Default: true
  filter: <string>  # (Optional) bpf filter expression, as you'd use with tcpdump
  snaplen: <integer>  # (Optional) Maximum size of packets in capture
  vms:
    - hostname: <string>  # (REQUIRED) Hostname of VM from topology to capture traffic from
      interface: <integer or string>  # (Optional) Name or index of interface on VM to capture traffic on. Default: 0 (the first non-management interface)
  filebeat.inputs:  # NOTE: if filebeat is configured, ensure convertToJSON is true
    - type: log
      enabled: true
      paths:
      - *.pcap.jsonl
      processors:
      - decode_json_fields:
          fields:
            - message
          target: scorch.pcap
      - drop_event:
        when:
          has_fields:
            - scorch.pcap.index._type
      - drop_fields:
          fields: ['message']
      - timestamp:
          field: scorch.pcap.timestamp
          layouts:
            - 'UNIX_MS'
```

The `filter` and `snaplen` options are optional. Each applies to every VM this component captures; per-VM values are not supported. minimega keeps one filter and one snaplen per namespace for every capture started while they are set, so the component sets its `filter` and `snaplen` (or clears ones another component left) before starting its captures and clears both once they have started. It clears the filter by setting a blank one, `' '`, which matches every packet, because minimega ignores an empty filter sent in a namespace; `capture pcap filter` then reports `" "`. It clears the snaplen by setting 0, minimega's default. The component refuses, before it sets anything, a `filter` with a non-printable character other than a tab or line break, or with a backslash, a quote or `#` but no space, which minimega cannot relay intact.

The `convertToJSON` creates `.jsonl` (JSON Lines format) files from the PCAP files. This option is important if Filebeat is going to be used to process the results of the traffic capture to send to Elastic. By default it is disabled since it can take a while to complete. If `convertToJSON` is `true`, then it is assumed that the `tshark` executable is present on the host running this component.

The `create_merged_pcap` option will merge all of the PCAP files into a single file using [mergecap(1)](https://www.wireshark.org/docs/man-pages/mergecap.html). This simplifies analysis when a large number of hosts are being captured and the capture duration is low, or vice-versa. If `create_merged_pcap` is `true`, then it is assumed that the `mergecap` executable is present on the host running this component (this is typically included when installing tshark or Wireshark). By default, this is set to `false`, since the resulting file can be quite large for long-running captures. The `dedupe` option utilizes [editcap(1)](https://www.wireshark.org/docs/man-pages/editcap.html) to remove duplicates. This works comparing the length and MD5 hash of a packet against the previous 5 packets, and if it matches, then dropping the packet (so basically the first packet chronologically is kept, any future dupes in a 5-packet sliding window are dropped).

The `filebeat.inputs` section above can be blindly copied into user's own config and used as-is, or users can choose to change target field names if the ones used above aren't suitable.

## Example Configuration

```yaml
components:
  - name: pcap-example
    type: pcap
    metadata:
      convertToJSON: true
      create_merged_pcap: true
      dedupe: true
      filter: "not localhost"
      snaplen: 1500
      vms:
        - hostname: rtu-1  # defaults to interface 0
        - hostname: rtu-2
          interface: eth0
        - hostname: scada
          interface: 1
      filebeat.inputs:  # NOTE: if filebeat is configured, ensure convertToJSON is true
        - type: log
          enabled: true
          paths:
          - *.pcap.jsonl
          processors:
          - decode_json_fields:
              fields:
                - message
              target: scorch.pcap
          - drop_event:
            when:
              has_fields:
                - scorch.pcap.index._type
          - drop_fields:
              fields: ['message']
          - timestamp:
              field: scorch.pcap.timestamp
              layouts:
                - 'UNIX_MS'
```
