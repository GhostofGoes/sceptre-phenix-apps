# OT-sim App

This app, named `ot-sim` aids in the generation of config files for
[OT-sim](https://ot-sim.patsec.dev). It currently supports generating
configuration files for three different types of devices: a field device
(`fd-server`), a front-end processor (`fep`), and a client (`fd-client`). It
also supports generating a start script for a HELICS broker if needed.

Below is an example of all the options available in the app, with documentation
for each.

```
spec:
  scenario:
    apps:
    - name: ot-sim
      metadata:
        infrastructure: power-distribution # this is the default
        helics:
          # The broker setting has the following options:
          #   * address
          #   * hostname
          #   * base-fed-count
          # If both `hostname` and `address` are provided, `hostname`
          # takes precedence and the address for the broker will be pulled
          # from the topology. If `hostname` is provided it should include
          # the name of an interface in the topology to pull an IP from.
          # Otherwise, the first interface from the topology will be used.
          # If both `hostname` and `base-fed-count` are provided, an
          # inject will be generated and added to the topology for the
          # host to start the broker with the given number of federates
          # plus however many devices with I/O modules are configured. The
          # optional `log-level` and `log-file` options for the broker are
          # only used if a broker inject is created. When the scenario also
          # runs the `helics` app, that app writes the broker start scripts,
          # so `base-fed-count` and `dynamic` are rejected.
          broker:
            hostname: helics-broker|IF0
            base-fed-count: 2
            log-level: SUMMARY                   # this is the default
            log-file: /var/log/helics-broker.log # this is the default
          federate: OpenDSS # default federate to subscribe to; this is the default
          endpoint: updates # default endpoint to send updates to on default federate
                            # this is the default; set it to false to disable using
                            # endpoints for updates
          scan-rate: 5      # DNP3 master scan rate in seconds; FEPs default to 5 when
                            # `helics` is set, fd-clients only use it if set explicitly,
                            # otherwise the ot-sim default (30) applies
        message-bus:
          pull-endpoint: tcp://127.0.0.1:1234 # this is the default
          pub-endpoint: tcp://127.0.0.1:5678  # this is the default
        cpu-module:
          api-endpoint: 0.0.0.0:9101 # this is the default; can be set to null to disable globally
                                     # can also be set per device via host metadata; with
                                     # null here, only hosts that set their own `api-endpoint`
                                     # or `api` get an API
          api:                                # can also be set per device via host metadata
            endpoint: 0.0.0.0:9101            # this is the default if not provided
            tls-key: /path/to/tls.key         # both or neither must be provided; neither starts
            tls-certificate: /path/to/tls.crt # the API without TLS, either alone fails pre-start
            ca-certificate: /path/to/ca.crt   # optional, for mTLS; fails pre-start without both above
                                              # Each file that is set is injected below
                                              # /etc/ot-sim/certs; unset or null fields add
                                              # nothing to the config or the VM.
        ground-truth-module:
          elastic:
            endpoint: http://localhost:9200 # endpoint for ElasticSearch cluster
            index-base-name: ot-sim         # base name for index ground truth data is written to;
                                            # will be appended with current date stamp in the form
                                            # of "-YYYY.mm.dd"
        infrastructures:
          power-distribution:
            node:
              voltage:
                type: analog-read
                modbus:      # Device type variables support per-protocol configurations. Right now,
                  scaling: 2 # the Modbus protocol looks for two configs: `scaling` and `data-type`.
                             # If not provided, the scaling defaults to 0. The DNP3 protocol looks for
                             # four configs: `sgvar`, `egvar`, `class`, and `sbo`.
                  data-type: int32 # OT-sim register type for analog variables; this is the
                                   # default. int32, uint32, float use two registers each,
                                   # int64, uint64, double four; int16 and uint16 use one, but
                                   # uint16 cannot hold negative values or values above
                                   # 655.35 at scaling 2. Each point's address follows the
                                   # previous point's registers, on fd-servers and feps alike,
                                   # so set `data-type: uint16` to keep the one-register
                                   # layout of earlier releases.
            bus:
              voltage:
                type: analog-read
                modbus:
                  scaling: 2
            breaker:
              voltage: analog-read # will assume Modbus scaling of 0 if not specified
              current: analog-read
              freq: analog-read
              power: analog-read
              status: binary-read
              control: binary-read-write
            capacitor:
              voltage: analog-read
              current: analog-read
              freq: analog-read
              power: analog-read
              setpt: analog-read-write
              on_off_status: binary-read
            regulator:
              voltage: analog-read
              current: analog-read
              freq: analog-read
              power: analog-read
              setpt: analog-read-write
              on_off_status: binary-read
            load:
              voltage: analog-read
              current: analog-read
              active_power: analog-read
              reactive_power: analog-read
            line:
              from_voltage: analog-read
              from_current: analog-read
              from_active_power: analog-read
              from_reactive_power: analog-read
              to_voltage: analog-read
              to_current: analog-read
              to_active_power: analog-read
              to_reactive_power: analog-read
            transformer:
              from_voltage: analog-read
              from_current: analog-read
              from_active_power: analog-read
              from_reactive_power: analog-read
              to_voltage: analog-read
              to_current: analog-read
              to_active_power: analog-read
              to_reactive_power: analog-read
      hosts:
      - hostname: outstation
        metadata:
          type: fd-server
          infrastructure: power-distribution # will default to infrastructure in app metadata if not provided

          # The `message-bus`, `helics`, `cpu-module`, and `ground-truth-module`
          # keys available in the app metadata can be overridden on a per host
          # basis here. The only difference is for the `helics.federate`
          # setting, which when defined in the host metadata specifies the name
          # to use for the federate the device will be providing. If enabled
          # globally, the `ground-truth-module` can be disabled on a per host
          # basis by explicitly setting the value to null or false.
          # A host's `cpu-module` replaces the app's: it keeps only the
          # app-level API endpoint when it sets none, never the app-level
          # TLS files. When the app-level `cpu-module.api` sets TLS files,
          # pre-start fails naming a host whose own `cpu-module` would serve
          # the API over plain HTTP: its `cpu-module.api` must set
          # `tls-key` and `tls-certificate`, both null for plain HTTP, or
          # its `api-endpoint` must be null.

          helics:
            # Defaults to helics.broker in app metadata if not provided.
            # An fd-server with modbus, dnp3, or bacnet devices needs a
            # `hostname` or `address` from one of the two; pre-start fails
            # naming the host otherwise.
            # If provided for a host, and both `hostname` and
            # `base-fed-count` are provided, a separate inject is tracked
            # and generated for the given host in the topology file. Similar
            # to the app metadata, `log-level` and `log-file` can also be
            # specified.
            broker:
              address: helics-broker.other.network.test
            federate: # value can be a string or map; string value used directly as name for federate
              name: outstation-fed # name to use for this federate; defaults to hostname if not provided
              log-level: SUMMARY   # log level to pass to I/O module's init string; this is the default

          # The `modbus` and `dnp3` sections can take two forms. The first
          # is an array of device name/type configs, in which case the app
          # will assume the host running the device should listen on the
          # first interface defined in the topology file for the protocol.
          # The second is a map containing the `interface` key and the
          # `devices` key. In this form, the `devices` value will be an
          # array of name/type configs like before and the `interface` value
          # will specify the interface the device should listen on for the
          # protocol. The interface can be specified as an actual IP:port
          # to listen on or it can be an interface name:port to listen on,
          # in which case the IP is pulled from the topology file. For
          # either, if no port is specified, the default port for the
          # protocol will be used. The `bacnet` section has only the map
          # form; see BACnet below.

          modbus:
          # Will default to listening on port 502 of the IP configured for
          # the first interface defined in the topology file.
          - name: OpenDSS/bus-01 # name of topic key from another federate to subscribe to
                                 # defaults to helics.federate in app metadata if 'OpenDSS/' (federate name) is left off
            type: bus            # type of device for topic key -- this determines values to publish and subscribe to based on infrastructure
            endpoint: updates    # endpoint to send updates to at federate being used for this topic
                                 # defaults to helics.endpoint in app metadata if not set here
                                 # set to false to disable using endpoints for this topic
          dnp3:
            interface: IF1:20000
            devices:
            - name: line-01-03
              type: branch
              endpoint: updates

          logic:
            period: 1s
            processUpdates: true
            program: |
              foo = bar
            variables:
              foo:
                tag: foo.bar
                value: 0
      - hostname: gateway
        metadata:
          type: fep
          upstream:     # devices to poll over every protocol they serve; the legacy
          - outstation  # `connected_rtus` key is used if `upstream` is not present.
                        # Each client is named `modbus-client-<upstream host>` or
                        # `dnp3-client-<upstream host>` (and publishes
                        # `<name>.connected`), apart from the `modbus-outstation`
                        # server, since OT-sim modules ignore messages from a sender
                        # with their own name.
          downstream:   # protocols to serve every polled point over, dnp3 and/or modbus;
          - dnp3        # defaults to dnp3, and any other value fails pre-start.
          - modbus      # Each point is served with that protocol's settings from its
                        # infrastructure variable (Modbus `scaling` and `data-type`, DNP3
                        # `sgvar`, `egvar`, `class` and `sbo`), whichever protocol it is
                        # polled with.
      - hostname: hmi
        metadata:
          type: fd-client
          connected_rtus: # fd-server or fep hosts to poll; a fep is polled over the
          - gateway       # `downstream` protocols it serves, at the addresses it serves
                          # them, not over the protocols it polls its `upstream` with.
                          # Clients are named `modbus-client-<host>` and
                          # `dnp3-client-<host>`, and publish `<name>.connected`.
```
# Node-RED
[Node-RED](https://www.node-red.dev/) is a coding software that is
used for creating flows of data between systems.
[Node-RED](https://www.node-red.dev/) is particularly useful for
creating human machine interfaces (HMI's) that allow for users to
visualize metrics and data. [Node-RED](https://www.node-red.dev/)
can be added to front end processor (fep), field client devices
(fd-client), and field server devices (fd-server).

```
      - hostname: hmi
        metadata:
          type: fd-client
          node-red:
            flow: /phenix/injects/foobar/node-red-flow.json
            endpoint:
              host: 0.0.0.0
              port: 1880
            auth:
              editor:
                user: admin
                pass: admin
              ui:
                user: foo
                pass: bar
```

# BACnet

An `fd-server` with a `bacnet` section is a BACnet/IP server: the app renders a
`bacnet` element with a Device object and one object per infrastructure variable,
and adds the `bacnet` module to the CPU module. The host is a HELICS federate like
any other `fd-server`, so it gets the I/O module and the `helics/federate`
annotation too. A host can list the same device under `bacnet` and under `modbus`
or `dnp3`.

```yaml
metadata:
  infrastructure: building
  helics:
    broker:
      address: 10.20.0.5
    federate: building
  infrastructures:
    building:
      vent:
        co2_ppm:
          type: analog-read            # served as analog-input 1
          bacnet:
            units: partsPerMillion
        fan_status: binary-read        # binary-input 1
        exhaust_pct:
          type: analog-read-write      # analog-output 1, commandable
          bacnet:
            units: percent
            min: 0
            max: 100
        setpoint_ppm:
          type: analog-read-write
          bacnet:
            object-type: analog-value  # a setpoint: a value object, commandable
            units: partsPerMillion
        mode:
          type: analog-read-write
          bacnet:
            object-type: multi-state-value
            states: [occupied, unoccupied, standby]
hosts:
- hostname: bas-vent
  metadata:
    type: fd-server
    bacnet:
      interface: IF0:47808
      instance: 3003
      name: BAS-VENT-1
      devices:
      - name: building/bas-vent
        type: vent
        objects:
          co2_ppm:
            name: FAC.VENT.AT01.PV
            description: Cellar CO2 sensor 1
```

Host `bacnet` settings (a map; there is no list form):

| Key | Default | Meaning |
|---|---|---|
| `instance` | required | Instance of the Device object, 0 to 4194302, unique on the BACnet network |
| `devices` | required | Devices to serve, as in `modbus` and `dnp3`: `name`, `type`, optional `endpoint` |
| `devices[].objects` | none | Per-variable settings for this device only (a point's own name, description, limits, instance); they override the variable's `bacnet` settings |
| `interface` | first topology interface, port 47808 | `interface[:port]` or `ip[:port]`. The address must be one of the node's own: the endpoint is rendered as `ip/prefix:port`, because a BACnet/IP node hears broadcasts on its subnet's broadcast address |
| `name` | the hostname | Name of the Device object |
| `stale-after` | off | Seconds without a value before an object reports a fault |
| `module` | `ot-sim-bacnet-module {{config_file}}` | Command the CPU module starts |

Variable `bacnet` settings (all optional):

| Key | Default | Meaning |
|---|---|---|
| `object-type` | by variable type: `analog-input`, `analog-output`, `binary-input`, `binary-output` | Also `analog-value`, `binary-value`, and, for an analog variable, `multi-state-value`. An output needs a read-write variable and an input a read-only one |
| `instance` | lowest free one of the object type, from 1, in device and variable order | Object instance |
| `name` | the tag, `<device>.<variable>` | Object name, unique within the host |
| `description` | none | Object description |
| `units` | none | BACnet engineering-units name (analog objects) |
| `cov-increment` | the module's default (0.1) | How far present-value moves before COV subscribers are notified (analog objects) |
| `min`, `max` | none | Limits of a written value (analog objects) |
| `states` | required for `multi-state-value` | State texts, state 1 first |
| `commandable` | true for a read-write variable | Gives the object a priority array and lets present-value be written. An output is always commandable; a read-only variable never is |

Troubleshooting:

| Error | Fix |
|---|---|
| `fd-server '<host>' sets bacnet without `instance`, the instance of its BACnet Device object` | Add `instance` |
| `fd-server '<host>' bacnet must be a map with `instance` and `devices`; it has no list form` | Move the device list under `devices` |
| `fd-server '<host>' has no topology interface with address <ip>; ...` | Set `interface` to an interface name or one of the node's addresses |
| `fd-server '<host>' BACnet object for '<tag>' is an output object, but the variable is '<type>': ...` | Make the variable read-write, or use an input or value object |
| `fd-server '<host>' has two <type> objects with instance <n> (second: '<tag>')` | Give one of them another `instance`, or leave it out |
| `<fep or fd-client> '<host>' polls '<device>', which serves only bacnet; OT-sim has no client for it, ...` | Give the device a `modbus` or `dnp3` section too, or stop polling it |

Limitations:

- The config is rendered for OT-sim's BACnet module (`ot-sim-bacnet-module`),
  which is proposed upstream and not in OT-sim's `main` branch yet. Until it is,
  the device image must have an OT-sim build that includes it.
- Server only. OT-sim has no BACnet client, so a `fep` or `fd-client` cannot
  poll a device over BACnet, and a `fep` cannot serve BACnet downstream.
- `units` is not checked here; the module rejects a name it does not know.
- The module's `override-tag` (a second tag that says whether a BACnet command
  is in force) is not rendered.

# Outstation point map

`phenix_apps.apps.otsim.points.Outstations` exposes, for any `fep` or `fd-server` host,
the DNP3 points its outstation serves (`AnalogInput 0` is `cap1.voltage` of a
`capacitor`, ...) and its listen endpoint, using the same register processing and
numbering as the generated config. Other apps (Ignition) build their point names from
it, so changes to how registers are collected or numbered here change those apps too.
