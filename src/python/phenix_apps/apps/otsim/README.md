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
            # An fd-server with modbus or dnp3 devices needs a `hostname`
            # or `address` from one of the two; pre-start fails naming the
            # host otherwise.
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
          # protocol will be used.

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

# Outstation point map

`phenix_apps.apps.otsim.points.Outstations` exposes, for any `fep` or `fd-server` host,
the DNP3 points its outstation serves (`AnalogInput 0` is `cap1.voltage` of a
`capacitor`, ...) and its listen endpoint, using the same register processing and
numbering as the generated config. Other apps (Ignition) build their point names from
it, so changes to how registers are collected or numbered here change those apps too.
