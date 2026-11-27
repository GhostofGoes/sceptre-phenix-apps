# cherrymountain App

cherrymountain is a phenix user app that provisions the CherryMountain Brewery
topology
([DESIGN.md 16](https://github.com/GhostofGoes/sceptre-phenix-topologies/blob/feat-secret-topo/cherrymountain-brewery/docs/DESIGN.md#16-new-and-extended-software)).
To provision a topology is to prepare its VMs for use. The app makes sure that
the scenario agrees with `plant/plant.yaml`. It renders every per-host file
that the VMs need at boot. It monitors provisioning, and it exports the data of
the run at the end.

The topology is the `cherrymountain-brewery` directory of
[sceptre-phenix-topologies](https://github.com/GhostofGoes/sceptre-phenix-topologies/tree/feat-secret-topo/cherrymountain-brewery)
(branch `feat-secret-topo` of the fork). "DESIGN.md" below is the
`docs/DESIGN.md` file of that directory. The app does nothing without that
directory ([Inputs it reads](#inputs-it-reads)).

```
name:   cherrymountain
exe:    phenix-app-cherrymountain
stages: configure, pre-start, post-start, running, cleanup
```

## Where it goes in the scenario

Put the app after `ot-sim` and before `helics`. ot-sim annotates the field
devices with `helics/federate`. This app annotates the sim-* federate nodes.
helics counts both
([DESIGN.md 15.2](https://github.com/GhostofGoes/sceptre-phenix-topologies/blob/feat-secret-topo/cherrymountain-brewery/docs/DESIGN.md#152-apps)).
A federate is one program of the HELICS co-simulation.

In the full scenario, the `mirror` app comes before this app. In each stage,
phenix runs the apps in the order of the list in the scenario. The post-start
stage of this app needs the ports that the mirror app records in its own
post-start stage ([Mirror ports](#mirror-ports)).

plantgen is the file generator of the topology. plantgen emits the block with
`runPeriodically: 5m`. Thus phenix runs the `running` stage every five minutes,
and the status stays current. The schedule belongs to the process that starts
the experiment:

- `phenix ui` keeps the schedule for an experiment that it starts. Such a start
  is a `phenix workflow apply` (which starts the experiment through the server)
  or a start from the UI.
- A plain `phenix experiment start <name>` from the CLI does not keep the
  schedule. Pass `--honor-run-periodically`, and the command then stays in the
  foreground until the experiment stops. As an alternative, run the stage by
  hand: `phenix experiment trigger running <name> cherrymountain`. Name the
  app. Without the app name, the command runs the `running` stage of every app,
  and for the `scorch` app that stage is SCORCH run 0.

## Stages

| Stage | What it does |
|---|---|
| configure | The stage makes sure that the metadata is correct (strict Pydantic models). It loads `plant.yaml` for `variant` through plantgen and compares it with the topology. It makes sure that every plant host of the variant exists. It also makes sure that each interface of such a host has the name, address, prefix length, and VLAN from plant.yaml. It annotates each sim node that runs federates with `helics/federate: [{broker: sim-ctl\|mgmt, fed-count: N}]`. It writes the `sohProfile` of each host (processes, listeners, custom tests) into the host metadata of this app. The soh (state of health) app of phenix reads the profile there |
| pre-start | The stage does the same tests again. Then it renders the files below into `<experiment dir>/cherrymountain/<host>/` and injects them. An injection replaces any other injection to the same destination. Thus a rendered file wins over a static file in the topology. `injections.json` lists each file and its destination |
| post-start and running | Each stage runs `systemctl is-active` for the provisioning units of each host through cc. cc is the command-and-control function of minimega. The timeouts are short, and the stage never blocks on a VM that did not boot. The stage also reads the plant KPIs from the sim-ctl event API. It writes both results to `status.apps.cherrymountain`. Because miniccc runs a command without a shell, the check is the plain unit list. When a post-start stage fails, phenix stops the experiment. Thus post-start does not fail on an error that it cannot work around. It records the error (`error: <type>` in the status). `running` reports such an error to its caller. When the scenario has a `mirror` app, both stages first set `options:df_default=false` on the GRE ports of that app ([Mirror ports](#mirror-ports)) |
| cleanup | The stage runs the export scripts on the FUXA hosts and the historian. It copies two files to `<files>/cherrymountain/<host>-<file>`. The first file is `fuxa-export.tar.gz`. It holds the alarm history from the API, and the `_db` of FUXA with the alarm and SQLite DAQ stores. The second file is `influx-backup.tar.gz`. The stage logs and records a failed export, and a failed export does not fail the stage |

## Inputs it reads

All inputs come from `sourceDir`, which is the cherrymountain-brewery directory
inside the phenix container. `phenix workflow apply` reads the directory from
there:

| Input | Used for |
|---|---|
| `plant/plant.yaml` (through `tools/plantgen`) | Hosts, interfaces, roles, federates, northbound protocols |
| `plant/generated/<variant>/` | `helics.json`, `openplc/<plc>/modbus_*.json`, `tags.json`, `registers.json` |
| `phenix-injects/openplc/<program>.zip` (ci), `phenix-injects/openplc/<variant>/<program>.zip` (full, lite) | The program ZIPs that `plc/plc-cellar/build_zip.sh` and `plc/common/build_zip.sh` build. Git LFS stores them. A pointer file fails pre-start with a message that says to run `git lfs pull` |
| `fuxa/build_project.py` | The FUXA project of each FUXA host (scada-fuxa, and bas-fuxa in full and lite), built for the variant |
| `phenix-injects/openplc/`, `phenix-injects/fuxa/` | The provisioning scripts and units. The app injects them without changes |
| `phenix-injects/brand/`, `phenix-injects/grafana/` | The mark, icons, and colors of the brewery (copies of `brand/` that `sync.py` keeps), and the image script of Grafana. `brand.py` says which file goes to which destination on which host |

The app imports plantgen and the FUXA builder from `sourceDir`. They are not
installed in the image. Thus the code always matches the plant data next to it.

## Metadata

App block:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `variant` | name | required | The variant from plant.yaml (`ci`, `lite`, `full`). For a site of the fleet, it is the code of the site |
| `site` | two letters | none | The code of one site of the fleet, from `plant/sites.yaml` ([A site of the fleet](#a-site-of-the-fleet)). Without this key, the experiment is the single site |
| `sourceDir` | absolute path | `/phenix/topologies/cherrymountain-brewery` | The topology directory |
| `simCtl.hostname` | hostname | `sim-ctl` | The host of the HELICS root broker and the event API |
| `simCtl.eventPort` | port | `8080` | The port of the event API inside sim-ctl |
| `simCtl.timeout` | seconds | `10` | The timeout of a request to the event API |
| `simCtl.vizPort` | port | `8090` | The port of cm-viz on 127.0.0.1 in sim-ctl (DESIGN.md 15.10). cm-viz is the 3D view of the white cell (the staff that runs the exercise) |
| `mgmt.enabled` | bool | `true` | The app injects the MGMT nftables policy |
| `mgmt.interface` | interface | `mgmt` | The name of the MGMT interface in the topology. It is not the device name in the guest, because phenix does not rename NICs. The startup hook finds the device by the MGMT address of the host |
| `mgmt.brokerPorts` | ports | `[23404, 23405, 23406]` | The HELICS broker ports on sim-ctl |
| `mgmt.federatePortMin`, `mgmt.federatePortMax` | ports | `23407`, `23999` | The HELICS federate core ports. The broker connects back to these ports. Nothing pins them. The broker assigns one port to each core. For each host, it counts up from immediately above its own ports (23414 in HELICS 3.6). Thus keep the start of the range immediately after the broker ports |
| `mgmt.opensearchPort` | port | `9200` | The port of the ground-truth OpenSearch on sim-ctl |
| `mgmt.exclude` | hostnames | `[]` | The MGMT members that keep no policy |
| `historian.org` | name | `cherrymountain` | The InfluxDB organization |
| `historian.buckets` | names | `[scada, bas, oee]` | The InfluxDB buckets |
| `historian.retentionHours` | integer | `720` (30 days) | The retention of the buckets. `0` keeps data forever |
| `historian.recordsBucket` | name | `records` | The TTB records bucket (DESIGN.md 12.4). A daily InfluxDB task copies the last value of each `recordsTags` series from `scada` into this bucket. An empty value turns the bucket off |
| `historian.recordsRetentionHours` | integer | `26280` (3 years) | The retention of the records bucket (27 CFR 25.300, C.R.S. 44-3-503(6)) |
| `historian.recordsTags` | Flux regular expression | packaging counts and rejects, BBT levels, fermenter extract | The tag names that the task copies into the records bucket |
| `historian.influxPort`, `grafanaPort`, `mqttPort` | ports | `8086`, `3000`, `1883` | The ports of the historian services |
| `historian.mqttTopicRoot` | topic | `cherrymountain/frontrange` | The root of the PackTags topics |
| `wazuh.manager` | hostname | `wazuh` | The Wazuh manager. Without a `wazuh` block, the app renders no Wazuh files |
| `wazuh.interface`, `wazuh.enrollmentPort` | interface, port | `IF0`, `1515` | The interface and the port where agents enroll |
| `wazuh.agents` | hostnames | `[]` | The hosts that run an agent and get the enrollment password. The list is an explicit allowlist (plantgen writes it from plant.yaml `app.wazuh.agents`). An empty list enrolls nobody |
| `secrets.*` | string | generated | `openplcPassword`, `fuxaPassword`, `fuxaOperatorPassword`, `fuxaJwtSecret`, `influxPassword`, `influxToken`, `grafanaPassword`, `guacamolePassword`, `wazuhEnrollment`, `malcolmPassword`, `wazuhPassword`, `vendorGuacPassword`, `vendorTotpSecret` (Base32), `vendorEwsPassword` |
| `wireguardKeys` | `generate` or `scenario` | `generate` | `generate` replaces the `wireguard` keys of the scenario (the fixed-seed keys of plantgen) with keys for this experiment at configure |
| `verify.timeout`, `verify.clientGrace` | seconds | `15`, `5` | The timeouts of each check in post-start and running |
| `verify.recheck` | `unprovisioned` or `all` | `unprovisioned` | The hosts that `running` asks again. A check sets the cc filter of minimega for a moment, and a namespace has only one such filter. In that moment, a command that the soh app of phenix or a SCORCH component sends from another process goes to the wrong VM. Thus, by default, the stage does not ask a host again after the host is `provisioned`. The app then keeps the state until the next start, and a settled plant gets no cc commands from this app. `all` asks every host on every pass. State of health is the check for a service that stops later |
| `vendorTechnicians` | list of short names | `[akim, jdiaz]` | The technicians of Ridgeline. Each technician gets a named Guacamole account (`ridgeline-<name>`) with its own TOTP key, and its own EWS account (DESIGN.md 13). The scripted session of vendor-ws signs in as the first technician |
| `staffAccounts` | list of account names | `[]` | The company's own staff at the jump host of a site that the vendor does not reach, for example `[corp-controls, ep-maint]`. The generated scenario of such a site sets the list from `plant/sites.yaml` (`staff`). Each account gets a Guacamole password, a TOTP key, and an EWS password for the experiment. A name does not start with `ridgeline-` |
| `exportOnCleanup` | bool | `true` | The app runs the cleanup exports |

Host metadata, which `type` selects:

| `type` | Fields (defaults) | Renders |
|---|---|---|
| `openplc` | `program` (the hostname), `northbound` (from plant.yaml: `modbus_slave`, `opcua`, `s7comm`), `opcua.port` (4840), `opcua.interface` (IF0), `opcua.debugMap`, `opcua.cycleTimeMs` (100), `s7comm.port` (102), `restPort` (8443), `compileTimeout` (900) | The program ZIP, `conf/modbus_master.json` and `modbus_slave.json` (plantgen), `conf/opcua.json` (from the debug map of the compiled program) or `conf/s7comm.json`, and `/etc/default/cm-openplc`. Also the provisioning script, unit, and boot hook |
| `fuxa` | `role` (`scada`), `project` (built), `expectDevices` (every project device), `daq` (`auto`: InfluxDB when the app has a historian, else SQLite), `bucket` (the role), `port` (1881) | The project JSON, `mysettings.json` (secure mode, JWT secret, DAQ store, no Node-RED), and `/etc/default/cm-fuxa` (the `admin` and `operator` passwords). Also the provisioning script, unit, and hook, and `cm-export-fuxa`. Also the brand: the tab icon, the mark, and `66-fuxa-brand.sh` with `FUXA_TITLE` ("CherryMountain Brewery SCADA" or "... BAS") |
| `rio` | `telnet` (`interface` IF0, `port` 23, `banner` default) | Nothing, unless `telnet` is set. In that case, the telnet module goes into the ot-sim `config.xml` that the ot-sim app rendered (relay-main). In all other cases, the app only tests the host (ot-sim devices of any role) |
| `sim-ctl` | `federates` (from plant.yaml for this host) | The same files as `sim-federate`, when the host runs a federate. Where the ground-truth Grafana runs (`ground-truth.env`), the app also renders the Grafana dashboard with the series colors of the brand. It also renders the Grafana images and script of the brand |
| `sim-federate` | `federates` (from plant.yaml for this host), `logLevel` (`INFO`) | `helics.json`, `/etc/cherrymountain/federates`, `/etc/default/cm-federate-<name>`, `cm-federate@.service`, `60-cm-federates.sh` |
| `historian` | `interface` (IF0) | `/etc/default/cm-historian`, Telegraf, Mosquitto, Grafana data sources and dashboard, systemd drop-ins, `cm-historian-provision` and its unit and hook, and `cm-export-historian`. Also the Grafana images and script of the brand. The lines of the plant dashboard take the series colors of `brand/tokens.json` |
| `hmi` | `fuxa` (`scada-fuxa`), `view` (`Overview`), `interface` (the interface of the FUXA host, IF0) | `/etc/default/cm-kiosk` (the URL of the view), `/etc/default/cm-kiosk-credentials` (0600: the `operator` sign-in), `cm-kiosk`, and the XDG autostart entry ([HMI kiosk](#hmi-kiosk)) |
| `guacamole` | `connections` (`ews-rdp`, `ews-ssh`), `recording` (true), `totp` (true) | The Guacamole initdb SQL (salted hash only) and `/etc/default/cm-guacamole` |
| `wazuh-manager` | | With the `wazuh` block of the app: the enrollment password and the dashboard admin password (`/etc/default/cm-wazuh-manager`), and the boot hook |
| `bbmd` | | Nothing. The topology injects cm-bbmd.service and its configuration from `phenix-injects/bbmd/`. The app only tests the host (SoH: the `cm_bbmd.py` process) |
| `ews` | | `/etc/default/cm-ews` (0600). It holds the OpenPLC REST account that `cm_plc_tool.py` uses. The app creates the same account on every PLC |

Every topology node with a `mgmt` NIC gets three files, whether the app lists
the node or not. The files are `/etc/cherrymountain/nftables-mgmt.nft`,
`/etc/default/cm-mgmt` (the MGMT address of the node), and the startup hook
`4-cm-mgmt-nftables.sh`.

The policy only matches the MGMT interface. It allows ICMP echo, HELICS,
OpenSearch, and NTP to sim-ctl. It also allows HELICS from the broker to the
federate cores. It drops everything else on MGMT
([DESIGN.md 10.1](https://github.com/GhostofGoes/sceptre-phenix-topologies/blob/feat-secret-topo/cherrymountain-brewery/docs/DESIGN.md#101-zones-and-conduits-purdue-model--isaiec-62443)).

phenix does not rename the NICs of a guest. Thus the hook runs after
`3_interfaces-start.sh`. It finds the device that holds the MGMT address and
passes the name of the device to the ruleset (`nft -D mgmt_if=<device>`).

## A site of the fleet

The fleet has four breweries, and each one is a site. The generator writes
the files of each site. The scenario of a site sets `site` in the app block.
The key changes four things:

| Part | Without `site` | With `site: fc` |
|---|---|---|
| Generated files | `plant/generated/<variant>/` | `plant/generated/fleet/fc/` |
| The plant | plant.yaml, expanded for the variant | plant.yaml, expanded for the site by plantgen (`fleet.expand_site`). The hosts have the names and the addresses of the site |
| Default host names | `sim-ctl`, `wazuh`, `scada-fuxa`, `ews` | `fc-sim-ctl`, `fc-wazuh`, `fc-scada-fuxa`, `fc-ews` |
| HELICS broker | The phenix `helics` app starts the root broker | This app injects `cm-helics-broker.service` on the sim-ctl of the site |

- A default host name gets the prefix only where the scenario gives no name. A
  name in the scenario stays as it is.
- A site does not need each kind of host. `fc` has one SCADA host, and it has
  no workstation, no jump host, and no Wazuh. The app then renders nothing for
  those kinds.
- A site has no program ZIPs of its own. A PLC of a site runs the ZIP of the
  `full` variant, under the name with no prefix (`fc-plc-cellar` runs
  `plc-cellar`). The boot script replaces the plugin configuration in the ZIP
  with that of the site.
- `fuxa/build_project.py` builds the FUXA project of a site from the tag
  lists of the site.

The broker of a site: the fleet has one broker for each site, and the `helics`
app has one root broker for an experiment. Thus the scenario of a site has no
`helics` block. The app stops at configure when it finds one, because two
brokers on one host fail without a message.

- The unit runs `helics_broker --name <host> -f<count> --ipv4
  --local_interface <MGMT address>`. The count is `federate_count` in the
  `helics.json` of the site.
- The broker listens on the MGMT address of its host only. A federate of a
  different site then cannot join it by accident.
- `55-cm-helics-broker.sh` starts the unit at boot. The federates try again
  until the broker answers.
- A site restarts as a whole. When the broker restarts, restart each federate
  and each field device of the site.

## Example

The ci variant:

```yaml
- name: cherrymountain
  metadata:
    variant: ci
  hosts:
    - hostname: sim-ctl
      metadata:
        type: sim-ctl
    - hostname: sim-process
      metadata:
        type: sim-federate
    - hostname: rio-cellar
      metadata:
        type: rio
    - hostname: plc-cellar
      metadata:
        type: openplc
    - hostname: scada-fuxa
      metadata:
        type: fuxa
```

A fuller plant (excerpt):

```yaml
- name: cherrymountain
  metadata:
    variant: full
    wazuh:
      manager: wazuh
  hosts:
    - hostname: plc-brewhouse
      metadata:
        type: openplc
        opcua:
          debugMap: plc/plc-brewhouse/debug_map.json
    - hostname: historian
      metadata:
        type: historian
    - hostname: hmi-brewhouse
      metadata:
        type: hmi
        view: Brewhouse
    - hostname: dmz-jump
      metadata:
        type: guacamole
    - hostname: wazuh
      metadata:
        type: wazuh-manager
    - hostname: ot-svc
      metadata:
        type: bbmd
    - hostname: bas-bbmd
      metadata:
        type: bbmd
```

## Status

`status.apps.cherrymountain` after post-start or running:

```json
{
  "stage": "running",
  "updated": "2026-11-09T01:00:00+00:00",
  "provisioned": "4/5",
  "provisioning": {"plc-cellar": {"state": "provisioned"}, "scada-fuxa": {"state": "pending", "detail": "cm-fuxa-provision.service=activating"}},
  "kpis": {"available": true, "batches": 2, "bottles": 3968, "packaged_bbl": 13.0, "energy_kwh": 120.0, "kwh_per_bbl": 9.23, "demand_kw": 88.5}
}
```

The host states are `provisioned`, `pending`, `failed`, `unreachable` (no C2
client yet), and `not-checked` (no provisioning unit). The C2 client is miniccc,
the minimega agent in a VM. After cleanup, `exports` maps each host to the
exported file, or to `failed: <error type>`. If the scenario has a `mirror` app,
the status also has a `mirror` entry ([Mirror ports](#mirror-ports)).

Read the status from the stored experiment:

```shell
docker exec phenix phenix config get experiment/<name> -o json -p
```

Then look under `status.apps.cherrymountain`. `updated` says when the last
`running` (or post-start) pass wrote the status. Immediately after a start, most
hosts are `pending` or `unreachable`. `kpis.available` is false, and the status
gives the reason. The next `running` pass fills in the values.

## Mirror ports

The full variant mirrors the VLANs of the plant to Malcolm with the `mirror` app
of phenix. The mirror app adds a GRE tunnel port to the Open vSwitch bridge of
every cluster host. A mirrored frame that fills the path MTU grows past the MTU
inside the tunnel. By default, Open vSwitch sets DF (the do-not-fragment flag)
on the outer header. Thus the network loses full-size frames unless the port has
`options:df_default=false`.

The mirror app does not set that option. Before, a person had to run an
`ovs-vsctl` loop in the minimega container after every start. This app sets the
option:

- Which ports: the ports that the mirror app recorded in `status.apps.mirror`,
  not every GRE port on the host. The record is `mirrors.<target>.mirrorName`,
  which is the tunnel port and also the name of the mirror. Which hosts: every
  cluster host of `status.schedules`, because the mirror app creates a port on
  each host.
- How: the app runs
  `ovs-vsctl --timeout=10 set interface <port> options:df_default=false`
  through the `shell` command of minimega, in the namespace of the experiment.
  On the headnode (the main cluster host), it uses `shell`. On another host, it
  uses `mesh send <host> shell`. The `ovs-vsctl` calls of the mirror app do the
  same (`mm.MeshShell`). In each case, minimega runs the command without a
  shell in its container, where Open vSwitch is.
- When: at post-start, and again at every `running` pass. The mirror app must
  record its status first, so the full scenario lists the mirror app before
  this app. The status can be absent because the scenario lists the mirror app
  after this app, or because its post-start failed. If the status is absent,
  the step records `dfDefault: waiting`. Then `running` sets the option as soon
  as the status appears.
- The step never fails the stage, because a failed start stops the experiment.
  The app logs and records a host that does not answer, a missing port, or a
  dead minimega socket. The next `running` pass tries those items again.
- The step is safe to repeat. An option that you set to the value that it
  already has changes nothing in Open vSwitch. The app does not send the
  command again for a port that the status records as set on a host. Thus a
  settled
  experiment gets no commands from the `running` stage. A mirror app that ran
  again made new ports (new random names), and the app sets those ports.
- The step has nothing to do without a `mirror` app (lite and ci), with a
  disabled mirror app, or in a dry run. It also has nothing to do when the
  mirror uses ERSPAN and not GRE (`skipped`).

The record is under `status.apps.cherrymountain.mirror`:

```json
{
  "dfDefault": "set",
  "updated": "2026-11-10T01:00:00+00:00",
  "ports": {
    "kQ7xT2mLb9NcR4d": {"target": "malcolm", "bridge": "cherrymtn", "hosts": {"phenix-host": "set", "node2": "set"}}
  }
}
```

`dfDefault` is `set` (every port on every host), `incomplete` (a host shows
`failed: <reason>`), `waiting`, or `skipped`. To examine the option by hand, run
`ovs-vsctl get interface <port> options:df_default` in the minimega container
of a cluster host. The command prints `"false"`.

## Credentials

The credentials are for the range only. A value that you set under `secrets`
wins. The app generates every other value once for each experiment into
`<experiment dir>/cherrymountain/secrets.json` (mode 0600). It uses the same
values again on restarts, so the VMs and their already-provisioned services
agree. The app writes and injects each file that holds a credential with mode
0600.

- Vendor persona: the app renders `ridgeline.env` for every node to which the
  topology gives that file (dmz-jump, ews, vendor-ws). For each technician of
  `vendorTechnicians`, the file holds the Guacamole password, the TOTP key, and
  the EWS password. The values of the first technician come from
  `secrets.vendor*`. The app keeps the values of the other technicians in
  `<experiment dir>/cherrymountain/
  vendor.json` (0600). The rendered file replaces the committed copy. Thus the
  three nodes always agree, and the values change with each experiment.
- Staff accounts: the app renders `staff.env` for every node to which the
  topology of a site gives that file (the `dmz-jump` and the `ews` of the
  site). For each account of `staffAccounts`, the file holds the Guacamole
  password, the TOTP key, and the EWS password. A person types the two
  passwords, so they have letters and digits only. The app keeps the values in
  `<experiment dir>/cherrymountain/staff.json` (0600). The rendered file
  replaces the copy of the site, whose values are placeholders that everyone
  can read. The app stops when nodes take the file and `staffAccounts` is
  empty, and when `staffAccounts` has accounts and no node takes the file.
- FUXA accounts: both FUXA hosts get two accounts. `admin` is the editor
  account (`fuxaPassword`). `operator` (`fuxaOperatorPassword`) is in the
  Operator group of FUXA (`groups: 2`). This account can write tags from a view
  and acknowledge alarms. It cannot open the editor or call the project, users,
  settings, or device APIs. FUXA keeps those for administrators (`groups` -1 or
  255).

  A client that opens `/home` with no session is the guest. The guest sees the
  views, and FUXA refuses its writes. The FUXA configuration leaves
  `secureOnlyEditor` and `userRole` unset, and the app never sets them.

  The HMI kiosks sign themselves in as `operator` ([HMI kiosk](#hmi-kiosk)).
  Thus an operator station writes values and presses buttons with nobody at it.
  Any other browser signs in by hand with the password from `secrets.json`. To
  sign in, use the account icon at the top right of the header, or do a write,
  which opens the same dialog. The session ends after `tokenExpiresIn` (12 h)
  or at sign-out.

  `cm-fuxa-provision` creates the account after it sets the admin password. If
  the password or the group of the account differs, it resets them. It fails
  when FUXA lets the account use the users API. A second run (a reboot) and a
  second import of the project leave the account alone. The SoH check
  `fuxa-operator-account` signs in as `operator` and tests the same things.
- Web consoles: the app generates `malcolm_password` (the user `malcolm` of
  Malcolm) and `wazuh_password` (the user `admin` of the Wazuh dashboard) like
  the other values. Thus the passwords are in `secrets.json`, and nobody has to
  open the console of a VM to read them. Both passwords are 24 characters of
  letters and digits. The Wazuh password also has one of `.+-`. The reason is
  the Wazuh passwords tool. It takes only passwords of 8 to 64 characters. A
  password must have an upper case letter, a lower case letter, a digit, and
  one of `.*+?-`. The tool also puts the password into an `eval`, so the app
  leaves out `*` and `?`.

  At configure, the app refuses a value under `secrets` that breaks its rule.
  It also refuses a hand-edited `secrets.json` that breaks the rule (to
  generate the value again, delete the key). The passwords go to these places:
  - Malcolm: the password goes into `/etc/default/cm-malcolm-credentials`
    (0600, `MALCOLM_ADMIN_PASSWORD`). Every node to which the topology gives
    `cm-malcolm-provision` gets this file (malcolm). Only
    `cm-malcolm-provision.service` reads the file. It reads the file after
    `/etc/default/cm-malcolm`, the sizing profile of the topology, which the
    app does not touch.
  - Wazuh: the password is `WAZUH_ADMIN_PASSWORD` in
    `/etc/default/cm-wazuh-manager` (0600). `cm-wazuh-provision.service` reads
    that file. The script tells the passwords tool to set the password of the
    `admin` user from a root-only file (`-f`). Thus the password is on no
    command line. The tool still generates the passwords of the other users
    (the indexer service accounts and the Wazuh API users). All the passwords
    are in `/var/lib/cm-wazuh/passwords.txt` on the VM.

  Without the value from the app (when you run the scripts by hand), each
  script generates its own password as before. In both cases, the VMs keep a
  root-only copy (`/var/lib/cm-malcolm/admin-password`,
  `/var/lib/cm-wazuh/passwords.txt`). Thus the console path still works.
- WireGuard: with `wireguardKeys: generate`, configure replaces the private key
  of each `wireguard` host. The app keeps the new key in
  `<experiment dir>/cherrymountain/wireguard.json` (0600). The configure stage
  also rewrites every peer entry that named the old public key. The app must
  come before `wireguard` in the scenario, and it does.

SoH test scripts never hold a credential. If a check needs a credential,
it sources the root-only configuration file on the VM. Errors and warnings name
the host and the field, never the value.

## HMI kiosk

`hmi-brewhouse` and `hmi-packaging` sign themselves in to FUXA as `operator`.
Thus an operator station writes values and presses buttons with nobody at it,
for the whole run. A kiosk is a screen that shows one full-screen view.
`/usr/local/bin/cm-kiosk` does the sign-in. It is a Python 3 script that uses
the standard library only, because the `python3-pydantic` of noble is 1.x.
`/etc/xdg/autostart/cm-kiosk.desktop` starts the script at login as root,
because the desktops autologin as root.

1. It waits until the project of FUXA has the view. After `KIOSK_WAIT` (10
   minutes), it continues anyway. `cm-fuxa-provision` makes the account first
   and imports the project after that. A page that loaded the old project keeps
   the old project. The client of FUXA does not notice an import (the table of
   runs below shows this).
2. It starts Chromium on the view with the flags that it always had. It adds
   `--remote-debugging-pipe` and a new `--user-data-dir` in `/run/cm-kiosk`. The
   debugging protocol then runs over two inherited file descriptors (3 and 4).
   It uses no port and no socket.
3. It signs in with `POST /api/signin` itself, so the password never enters the
   browser. It gives the browser the profile that FUXA sent in its answer. The
   client of FUXA keeps its session in `sessionStorage` (`currentUser`), for
   each tab. The client reads the session once when the page starts
   (`auth.service.ts`, constructor). It opens its socket with the token
   (`hmi.service.ts`). The server examines the token when the socket connects
   (`server/runtime/index.js`).

   Thus the script registers a snippet with
   `Page.addScriptToEvaluateOnNewDocument`. The snippet writes the profile into
   `sessionStorage` before the scripts of the page run. It does so for the
   origin of the view, in the top frame only. Then the script reloads the page.
   FUXA reloads the page itself after a server restart or a sign-out. The
   snippet restores the session then too.
4. Every `KIOSK_POLL` seconds, it asks the page what session the page holds.
   When the token is at two thirds of its life (8 h of 12 h), the script signs
   in again. It replaces the snippet and reloads the page. Thus the page loses
   a half-typed value, and the view flickers about every 8 hours. The renewal
   of FUXA itself does not do this for a screen that nobody touches.
   `/api/heartbeat` renews only after a click. At expiry, it answers `guest`.
   The page then signs out and reloads as a guest.

| Situation | What the kiosk does |
|---|---|
| At start, FUXA is down or has no project yet | The kiosk waits `KIOSK_WAIT`. Then it opens the view anyway (the error page of Chromium while FUXA is down) |
| A sign-in fails because FUXA is down, the account does not exist yet (401), or the password is wrong | The view stays, as a guest, which cannot write. The status says `sign-in as operator failed: <reason>`. The kiosk tries again after 10, 20, 40, and 80 s, and then every 120 s (`KIOSK_RETRY_MIN`, `KIOSK_RETRY_MAX`). When FUXA answers, the kiosk turns an error page into the view |
| FUXA restarts, and the token is still good | The socket of the page reconnects with its token. If FUXA reloads the page, the snippet restores the session |
| A person signs in with another account at the kiosk | At the next poll, the kiosk signs in again as `operator`. The kiosk is an operator station (the editor is for `ews`). To let another live session stand, change `judge()` in the script so that it accepts that session |
| FUXA is down longer than the token lives | The page is a guest from its first reconnect (`jwt expired`). The next sign-in after FUXA answers restores the session, within `KIOSK_RETRY_MAX` |
| The browser exits (crash, kill) | The kiosk starts the browser again after 10 s, 20 s, ... 120 s while the browser continues to exit within a minute. Then the kiosk signs in again |
| The browser does not answer for 60 s (a tab crash: "Aw, Snap!") | The kiosk kills the browser and starts it again |
| The debugging pipe is unusable (Chromium exits at once, or never answers) | The next browser starts without the pipe and shows the view as a guest. The browser after that one tries the pipe again |
| There is no `/etc/default/cm-kiosk-credentials`, or the file has no user or no password | A guest kiosk, as before |

Files:

| File | Holds |
|---|---|
| `/etc/default/cm-kiosk` (0644) | `KIOSK_URL`. Optional: `KIOSK_BROWSER` (`chromium`), `KIOSK_WAIT` (600), `KIOSK_POLL` (5), `KIOSK_RETRY_MIN` (10), `KIOSK_RETRY_MAX` (120). The times are in seconds |
| `/etc/default/cm-kiosk-credentials` (0600) | `KIOSK_USER` (`operator`) and `KIOSK_PASSWORD` (`fuxa_operator_password`). Only the HMI hosts get this file. In the same way, only the Malcolm sensor gets the Malcolm credentials file. The user of the kiosk is root, and the file is root-only |
| `/run/cm-kiosk/status` | `state` (`operator`, `guest`, `starting`, `down`), `detail`, `updated`. The file holds no secret. The SoH check `kiosk-operator-session` reads the file, and fails when the file is older than two minutes. The SoH process check looks for the browser (`chromium.*--kiosk`), because `cm-kiosk` stays up to restart the browser |

The password is never on a command line or in the environment of the browser.
The script logs only the reason that a sign-in failed. The browser holds the
token of the operator (12 h, renewed). Any script in the FUXA page can read that
token anyway. The sign-in is an HTTP `POST /api/signin` on port 1881, in clear
text like the sign-in of a person. Thus the capture of the HMI VLAN shows the
sign-in at each start and renewal. A kiosk that cannot sign in shows as a `401`
every 2 minutes.

Why a pipe: with `--remote-debugging-port`, any local process and user can
drive the browser. They can read the token, run script in the FUXA page as the
operator, and open `file://` pages. A pipe has no address. Only the two
processes that hold its descriptors can use it. Only root can read
`/proc/<pid>/fd/3` and `4`. Both processes run as root, and root can read the
credentials file anyway.

Nothing listens on the network or on loopback (`ss -ltunp` shows no Chromium
socket). The packaged `/usr/bin/chromium` (xtradeb 156) keeps descriptors 3 and
4 through its `exec`.

The kiosk does not use these alternatives:

- An extension with a content script. With the Chromium of the image and
  `--incognito`, the content script did not run. Without `--incognito`, it ran.
  "Allow in incognito" is an option of the profile that has no flag. The
  removal of `--incognito` also changes what the kiosk keeps on disk.
- The refresh-cookie mode of FUXA. `enableRefreshCookieAuth` changes the
  sign-in of every client. The cookie is `HttpOnly` with path `/api/refresh`
  and lasts 7 days. Thus, to seed the cookie, the script needs the cookie store
  of the browser or the debugging protocol anyway. `POST /api/signout` clears
  the cookie.
- Keystrokes into the dialog with `xdotool`. This method is blind. It depends
  on focus, layout, and timing, and every X client on the display can watch the
  keystrokes.
- A proxy on loopback that adds the token. The page still thinks that it is a
  guest, and any local request gets operator rights.

By hand, in a real browser, with no VM: the steps below are the steps of the
real run. You need a FUXA 1.3.6 checkout with `node_modules`, node, Xvfb,
`xdotool`, and the Chromium of the image. To get that Chromium on a noble
machine, use one of two methods. The first method is `apt-get install chromium`
from the xtradeb source of `phenix-images/cm-desktop.yml`. The second method is
to `dpkg-deb -x` the `chromium` and `chromium-common` packages of that source
into a directory. Then run `usr/lib/chromium/chromium` with the five libraries
that a plain noble container lacked (`libopenh264-7`, `libdouble-conversion3`,
`libharfbuzz-subset0`, `libxnvctrl0`, `libminizip1t64`).

1. In an empty user directory, write `_appdata/mysettings.json`. Put in it
   `secureEnabled: true`, a `secretCode`, `tokenExpiresIn` (`12h`, or `1m` to
   see the renewal), and `uiPort`. Start
   `node main.js --userDir <dir> --port <port>` in the `server/` directory of
   the checkout.
2. Run `FUXA_URL=http://127.0.0.1:<port> FUXA_ADMIN_PASSWORD=... FUXA_OPERATOR_PASSWORD=...
   FUXA_PROJECT=fuxa/full/scada-fuxa-project.json bash phenix-injects/fuxa/cm-fuxa-provision.sh`.
   Its output ends `PASS: project imported`. Without PLCs, the devices of the
   project show errors and the batch engine refuses a Start. But the buttons of
   the Batch view still write the `BATCH.CMD` of FUXA itself. The run below had
   stand-in PLCs on loopback: an OPC UA server for plc-brewhouse and a Modbus
   server for plc-cellar. The project of that run had new addresses for those
   two devices and had the other devices disabled.
3. Write the two configuration files as the app renders them. The first file
   holds `KIOSK_URL=http://127.0.0.1:<port>/home?viewName=Batch` and
   `KIOSK_BROWSER=<chromium>`. The second file holds `KIOSK_USER` and
   `KIOSK_PASSWORD`, with mode 0600. Run
   `DISPLAY=:99 python3.12 cm-kiosk --env <file> --credentials <file> --state-dir <dir>`
   on `Xvfb :99 -screen 0 1440x900x24`. Put the `KIOSK_*` tuning in the
   environment.
4. Click Start with `DISPLAY=:99 xdotool mousemove 380 457 click 1`. Read the
   log of FUXA (`api-signin`, `Client connected with authenticated token`, `unauthorized
   write attempt from guest`). Look at the account icon (blue when signed in).
   Read the engine tags with `GET /api/getTagValue` as `admin`.

The run showed these results, with Chromium 156.0.8078.73 from the package of
the image, Python 3.12, and FUXA 1.3.6 in secure mode:

| Run | Seen |
|---|---|
| The kiosk of today (the old `cm-kiosk` flags, no script), Start | `device-values: unauthorized write attempt from guest`, the sign-in dialog, `BATCH.CMD` stays 0 |
| `cm-kiosk`, 12 h tokens, Start | No dialog. FUXA: `api-signin: operator`, then `Client connected with authenticated token` (after one guest connection while the first page load ran). `BATCH.CMD` 1, then the engine: `Batch FOP-0001 running: MILL (1 of 11)`. No `unauthorized` line |
| `tokenExpiresIn` 1m, 2.5 minutes, then Start | A sign-in every 40 s, and an authenticated connection after each sign-in. Start, 1.5 minutes after the first token expired, ran the batch |
| The same, with FUXA stopped for 80 s (the token expired in that time) | Kiosk log: `operator`, `sign-in as operator failed: ConnectionRefusedError`, `guest`, `operator`. FUXA: `Token error: TokenExpiredError: jwt expired` at the reconnect of the page, and a sign-in 3 s later. Abort then aborted the batch |
| FUXA stopped, then the kiosk started | No browser, status `starting`. About 5 s after FUXA started, the browser was up and signed in |
| `KIOSK_WAIT=5`, FUXA stopped | The error page ("This site can't be reached"), `sign-in as operator failed: ConnectionRefusedError`. After FUXA started, the next try turned the error page into the signed-in view |
| Fresh FUXA (no account, no project), default wait | No browser until the import finished. The browser started 1 s after that, and the kiosk signed in 0.2 s later |
| Fresh FUXA, `KIOSK_WAIT=5` | The guest view. `HTTP 401` at 0, 10, 30, and 70 s (the log of FUXA). After provisioning, the try at 150 s signed in and reloaded |
| `SIGKILL` of the browser | The kiosk started the browser again after 10 s and signed in |
| `SIGSEGV` of its renderer | "Aw, Snap!". No answer for 60 s. The kiosk killed the browser, started it again, and signed in |
| A launcher that closes descriptors 3 and 4 | Chromium prints `Remote debugging pipe file descriptors are not open.` and exits. The next browser ran without the pipe and showed the view as a guest (black account icon) |
| Control: the script signs in once and never again (`KIOSK_POLL=100000`), 1m tokens | At +5:00, the heartbeat of FUXA: `POST /api/heartbeat 200`, `POST /api/signout 204`, a reload, two guest connections. The renewal of FUXA itself does not keep a screen that nobody touches signed in |
| A POST of a project while a page shows the old project | The page kept the old project (the sidebar still had the renamed view) |
| `ss -ltunp`, `/proc/<pid>/fd` | No Chromium socket. `fd/3` and `fd/4` are pipes. No process has the password in its command line or environment |

Two things in that run are specific to Chromium 156. First, a registered
`Page.addScriptToEvaluateOnNewDocument` script never runs until a client calls
`Page.enable` on the session. The kiosk script makes that call first. Second,
the top-level target list also holds `browser_ui` targets. The kiosk script
takes the target of type `page`.

The run did not show these things yet. The first boot of an HMI VM must show
them:

- The XDG autostart entry starts `cm-kiosk` when the XFCE session can run
  Chromium (`DISPLAY` set, `/run` writable). `cm-kiosk` then runs as root with
  the packaged `python3` (3.12).
- The clock of a VM agrees with the clock of FUXA to within the life of the
  token. The page and the script each judge a token by their own clock.
- A real screen at 1440x900 under xfwm4 shows the view full screen. The reload
  at each renewal looks acceptable there (the harness had no window manager).
- The `pgrep -f chromium.*--kiosk` of SoH finds the browser through miniccc.
  The `kiosk-operator-session` check passes after the account exists.
- The sign-ins and `401`s of the kiosk raise nothing in Wazuh, Suricata, or
  Zeek that the blue team can take for an attack. The blue team is the group
  of defenders in the exercise.

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `metadata.<field>: unknown key, ignored -> did you mean '<key>'?` | A key has a spelling error. Correct the key. |
| `metadata.type: not a known host type` | Use one of the types above. |
| `network.interfaces[IF1].address: differs from plant.yaml hosts.<host>.interfaces.IF1.ip` | The topology and plant.yaml disagree. Correct one of them. Then run plantgen again. |
| `<role> host is missing from the topology` | The variant in plant.yaml lists a host that the topology lacks. |
| `plant.yaml plc host is not in the app's hosts; the app will not provision it` | Add the host with `type: openplc`. This message is a warning. |
| `metadata.northbound: differs from plant.yaml hosts.<host>.northbound` | To use the value from plant.yaml, leave `northbound` out. |
| `phenix-injects/openplc/<program>.zip is a Git LFS pointer` | Run `git lfs pull` in the topology directory. |
| `no debug map for <program>` | OPC UA needs the `debug_map.json` of the compiled program. Put it in the ZIP or at `plc/<program>/debug_map.json`, or set `opcua.debugMap`. |
| warning `the <program> ZIP was built with other plugin configs than plant/generated/<variant>` | The ZIP is from a build for another variant (for example, the ci ZIP in full). Build it again with `plc/<program>/build_zip.sh` for this variant. |
| `the debug map of <program> is not from the program in its ZIP` | Build the ZIP and the debug map again, together. |
| `<n> host(s) could not be rendered:` and a line for each host | The pre-start stage renders every host before it fails. Correct each input in the list. |
| status `unreachable` for a host | The C2 client of the host is not up yet. `running` asks again. |

## Tests

The tests run the app on a checkout of the topology directory, with its Git LFS
files (`git lfs pull`). They find the checkout in `CHERRYMOUNTAIN_TOPOLOGY_DIR`,
or in a `sceptre-phenix-topologies` checkout next to this repository
(`tests/topology.py`). Without a checkout, pytest skips the tests, and one
skipped test gives the reason. The checks of the topology itself run the tests
the same way from an installed package
(`pytest --pyargs phenix_apps.apps.cherrymountain`). Run these commands from
`src/python`:

```shell
export CHERRYMOUNTAIN_TOPOLOGY_DIR=/phenix/topologies/cherrymountain-brewery
make test TEST=phenix_apps/apps/cherrymountain
```

`tests/test_sites.py` runs the app on each of the four sites. It builds the
experiment of a site from the generated workflow, topology file, and scenario
of the checkout, with no recorded copy.

The tests run every stage on two recorded experiments,
`tests/fixtures/experiment-ci.json` and `experiment-full.json`.
`tests/build_fixtures.py` records each experiment from the topology (with the
included modules), scenario, and workflow of its variant (`phenix-ci.yml`,
`phenix.yml`). It also uses `tests/fixtures/app-ci.yml` or `app-full.yml`, which
are copies of the blocks in the scenarios. `test_fixtures.py` fails when a copy
differs, or when a recorded experiment is not current. After a change to one of
those topology files, record the experiments again and commit the result:

```shell
python3 -I phenix_apps/apps/cherrymountain/tests/build_fixtures.py
```

The tests read the real plantgen output, program ZIP, and FUXA builder from the
topology directory.

`test_chain.py` runs the real phenix user apps from the scenario of each
variant (`ot-sim`, this app, `helics`, `protonuke`, `wireguard`). It runs them
in scenario order, as phenix does, through configure and two starts.

`fixtures/debug_map-plc-cellar.json` is the strucpp (`fcccfbdf`) debug map of
the committed plc-cellar program. It is a recording for the test of the OPC UA
configuration.

`test_kiosk.py` runs `cm-kiosk` as a process against two fakes, with no
browser. `fuxa_fake.py` imitates the sign-in of FUXA, with tokens that look
real. `kiosk_fake_browser.py` imitates the debugging pipe of Chromium. The test
cuts the waits of the script to milliseconds.

The test proves the logic of the script:

- When the script signs in and renews.
- What the script gives to the browser.
- That the password goes nowhere else.
- The retries and their growing waits.
- The restarts.
- The fallback without the pipe.

If node is installed, node runs the JavaScript of the snippet. The run by hand
in [HMI kiosk](#hmi-kiosk) shows that the real Chromium takes what the script
gives it.

`test_template_lint.py` runs `shellcheck`, `systemd-analyze`, and
`desktop-file-validate` on the scripts, units, and desktop entry in
`templates/`. These tests need no topology checkout. If a tool is missing,
pytest skips its tests, or fails them when `CI` is set.

## Limitations

- The app did not run on a VM. Every image for which the app renders files
  exists (`phenix-images/`), but no image booted. The historian and Wazuh only
  render and pass their tests. The Guacamole stack ran once in containers
  outside a VM, with files rendered like the files of the app. The script of
  the HMI kiosk ran against a real FUXA and the Chromium of the image on a
  virtual display, not on its VM. [HMI kiosk](#hmi-kiosk) lists what a first
  boot must still show. TODO(verify) notes in `render.py` mark guesses. The
  guesses are the keys of the InfluxDB DAQ store of FUXA, the s7comm mapping
  types beyond `int_output`/`int_input`, and the Guacamole schema version.
- The KPIs need `GET /api/v1/kpis` from the sim-ctl event API. The weather
  federate serves that API in full and lite. Until the API answers, the status
  says `available: false` and gives the reason. The compliance figures of the
  API go under `kpis.compliance`. These figures are TTB barrels, fill, CIP,
  wastewater, and the run hours and test hours of the genset (an engine-driven
  generator). A `genset-exercise` event advances those hours. The same place
  also has the test hours that are left under the 40 CFR 60.4211(f) cap.
- The app injects the Guacamole init SQL with mode 0644, not 0600 like the
  other rendered files that came from a secret. The reason is that the
  entrypoint of PostgreSQL runs the SQL as the `postgres` user of the
  container. The SQL holds a salted hash, no password.
- If the topology still starts a federate with its own unit (the
  `cm-cellar.service` of the ci slice), the app leaves the federate to that
  unit. The status check accepts either unit.
- The SoH check of the HELICS federate count counts the distinct peers that
  connect to the broker port. This number is an approximation of the federate
  count.
