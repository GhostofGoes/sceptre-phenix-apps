# plantevent Component

plantevent is a SCORCH component. It injects operational events into the
CherryMountain Brewery simulation through the sim-ctl event API
([DESIGN.md 9.5](https://github.com/GhostofGoes/brew/blob/main/docs/DESIGN.md#95-scenario-events-and-ground-truth),
[15.6](https://github.com/GhostofGoes/brew/blob/main/docs/DESIGN.md#156-scorch-pipelines)).
An operational event is a change in the plant, for example a utility outage.
sim-ctl is the VM that runs the event API.
The simulation is part of the `cherrymountain-brewery` topology. The
[cherrymountain app](../../cherrymountain/README.md) provisions that topology.

```
type:   plantevent
exe:    phenix-scorch-component-plantevent
stages: configure, start, stop, cleanup
```

Each stage that lists the component does the same thing. First, the component
makes sure that the API is healthy. Then it posts each entry of `events`, in
order. For events at different points of a run, define one `plantevent`
component for each point (refer to the examples).

## What you get

The component writes these files in its run folder
(`<files>/scorch/run-<run index>/<component name>/loop-<loop>-count-<count>/`):

```
plantevent_<stage>.json     each event posted: time, request body, and the API's reply
<stage>-<UTC time>.json     the SCORCH status file (logs, and the error on failure)
```

## Before you start

- sim-ctl runs the event API on port 8080 (`cherrymountain_sim`). The topology
  node of sim-ctl carries the autotunnel entry `"18080:8080"`
  (`phenix/startup-autotunnel`).
- The host port is not 18080. 18080 is the source port of the forward.
  `phenix-tunneler` opens that port on the machine of a user who runs it
  (`phenix-tunneler serve http://<phenix host>:3000`). From there, the traffic
  goes through `phenix ui` to the tunnel.

  On the phenix host itself, minimega listens on a random port in 50000-64999.
  minimega picks a new port for each new tunnel. The component runs on the
  phenix host. Thus, at the start of every stage, it finds the port with
  `cc tunnel list sim-ctl` (the row with `dst 127.0.0.1` and `dst port 8080`).
  It connects to that port on the minimega host that serves sim-ctl (127.0.0.1
  on the headnode). It never assumes a fixed port.
- The `GET /experiments/{exp}/vms/{vm}/forwards` request of phenix cannot
  replace that lookup. Its `srcPort` is the annotation label, and the host port
  is not in the reply.
- With the autotunnel loop of phenix (`ci-e2e-minimega` of the fork), the
  tunnel is always there. Upstream phenix creates no tunnel for an experiment
  that the CLI starts, and it never creates a tunnel again. In that case, with
  `create_tunnel: true` (the default), the component opens a tunnel itself. It
  uses the same command as phenix
  (`cc tunnel sim-ctl <random port> 127.0.0.1 8080`). Later stages use that
  tunnel again.

## Metadata

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `sim_ctl.hostname` | hostname | no | `sim-ctl` | The VM that runs the event API |
| `sim_ctl.port` | port | no | `8080` | The port of the API inside the VM |
| `sim_ctl.url` | URL | no | | The component sends to this URL and does not look up the tunnel (for example, a host-side relay) |
| `sim_ctl.create_tunnel` | bool | no | `true` | If no cc tunnel exists, the component opens one |
| `sim_ctl.timeout` | seconds | no | `10` | The time that the component waits for each request |
| `events` | list | yes | | The events to post, in order. The list must have at least one event |
| `interval` | seconds | no | `0` | The pause between two events |
| `check_health` | bool | no | `true` | The component sends `GET /api/v1/health` before the first event |

Events (`event` selects the kind of event):

| `event` | Fields | Meaning |
|---|---|---|
| `start-batch` | `recipe` (default `fire-of-the-phenix`), `brews` (1-4, default 2: brews queued back to back), `batch_id` | Start a brew day. If no PLC writes, the brewhouse autopilot runs the brews. If plc-brewhouse is in control, the brewhouse panel counts the request and the FUXA batch engine on scada-fuxa starts the brews. A request that arrives while FUXA is down waits at the panel until FUXA is back |
| `utility-breaker` | `action`: `open` or `close` (required) | A utility outage and its restoration |
| `genset-exercise` | `action`: `start` (default) or `stop`, `load_bank_kw` (0-100, default 0), `duration` (default 1800 s, the NFPA 110 monthly minimum) | Exercise the standby genset (an engine-driven generator) under load. The run goes into the genset test log and the 40 CFR 60.4211(f) test hours |
| `chiller-fault` | `compressor` (1 or 2, default 1), `action`: `fail` (default) or `clear` | A compressor fault of the glycol chiller |
| `co2-release` | `fv` (required: `FV-102` or `BBT-201`), `rate`: `low`, `medium`, or `high` (default), `duration` (default 600 s) | A CO2 release into the cellar |
| `jam` | `machine`: `rinser`, `filler`, `labeler` (default), or `packer`. The field also accepts `depalletizer` and `capper`, which jam the rinser and the filler. You cannot name the `coder` and `kegger` of the simulation here. `duration` (default 300 s) | A packaging jam |
| `weather-step` | `delta_f` (-60 to 60, required), `duration` (default 0: hold) | Change the outside temperature in one step |
| `cip-panel` | `circuit`: `bh`, `fv101` .. `fv104`, `bbt201`, `bbt202`, or `none` (required) | Swing the CIP (clean-in-place) panel onto a circuit, as a cellar worker does before a CIP run |
| `co2-leak` | `zone`: `tank`, `filler`, or `draft` (required), `rate`: `low`, `medium`, or `high` (default), `duration` (default 600 s) | A CO2 leak on the supply piping at the bulk tank, the filler, or the cold room and draft system. At 30,000 ppm, the supply shutoff closes the bulk valve and the leak stops |
| `gas-detection` | `action`: `fail` (default) or `restore` | Fail the gas-detection panel. Both relays drop, which inhibits carbonation and shuts off the CO2 supply |
| `refrigerant-leak` | `action`: `leak` (default), `repair`, or `recharge`. `rate`: `low`, `medium` (default), or `high` | A refrigerant leak in the chiller. `recharge` tops off the refrigerant and writes the charge record with its leak rate |
| `bess-thermal` | `action`: `start` (default) or `clear` | A cell of the BESS (battery energy storage system) heats toward thermal runaway. The BMS (battery management system) trips the PCS (power conversion system). Then the off-gas detector gives an alarm |

The component posts each event as JSON with `POST /api/v1/events`. The fields
above are the keys (for example `{"event": "co2-release", "fv": "FV-102", "rate":
"high", "duration": 600.0}`).

## Examples

A brew day: the component starts a batch when the run starts.

```yaml
components:
  - name: start-brew
    type: plantevent
    metadata:
      events:
        - event: start-batch
          recipe: fire-of-the-phenix
runs:
  - configure: []
    start: [start-brew]
    stop: []
    cleanup: []
```

A utility outage: one component opens the breaker at the start, and a second
component closes it at the stop.

```yaml
components:
  - name: outage-open
    type: plantevent
    metadata:
      events:
        - event: utility-breaker
          action: open
  - name: outage-close
    type: plantevent
    metadata:
      events:
        - event: utility-breaker
          action: close
runs:
  - configure: []
    start: [outage-open]
    stop: [outage-close]
    cleanup: []
```

A monthly genset exercise with a 30 kW load bank. NFPA 110 asks for 30 % of
the 100 kW nameplate for 30 minutes (DESIGN.md 7.3).

```yaml
components:
  - name: genset-exercise
    type: plantevent
    metadata:
      events:
        - event: genset-exercise
          load_bank_kw: 30
          duration: 1800
runs:
  - configure: []
    start: [genset-exercise]
    stop: []
    cleanup: []
```

A CO2 leak in the cellar during a heat wave. The component sends through a
fixed relay and does not look up the tunnel.

```yaml
components:
  - name: co2-leak
    type: plantevent
    metadata:
      sim_ctl:
        url: http://127.0.0.1:18080
        timeout: 5
      interval: 30
      events:
        - event: weather-step
          delta_f: 15
        - event: co2-release
          fv: FV-102
          rate: high
          duration: 900
runs:
  - configure: []
    start: [co2-leak]
    stop: []
    cleanup: []
```

To make sure that a configuration is correct before an experiment, run
`phenix-scorch-validate scenario.yaml`. The command tests the SCORCH structure
only. The component tests the event fields when the stage runs.

## Troubleshooting

| Error | Cause and fix |
|---|---|
| `no cc tunnel to sim-ctl:8080; is the VM's C2 client active, and does sim-ctl carry a phenix/startup-autotunnel entry for port 8080?` | `create_tunnel: false` is set and no tunnel exists. Wait for the C2 client of sim-ctl (miniccc, the minimega agent in the VM), add the autotunnel entry, or let the component create the tunnel. |
| `sim-ctl has no active C2 client, so no cc tunnel can reach it` | sim-ctl did not boot, or miniccc does not run. Look at the output of `cc clients`. |
| `GET /api/v1/health: ConnectionError` | The tunnel exists, but nothing listens on port 8080 in sim-ctl. Make sure that the event API service runs there. |
| `POST /api/v1/events: HTTP 400` | The API refused the event. The event has an unknown kind, or a parameter that the API cannot use. The component keeps the status code only, not the `{"error": ...}` reply of the API. Compare the fields of the event with the table above, or post the body by hand to read the reason. |
| `events.0: Input tag 'outage' found using 'event' does not match any of the expected tags` | The kind of event is unknown. Use a kind from the table above. |
| warning `metadata warning for component '<name>': events.0.fvv: unknown key, ignored` | A field name has a spelling error. The component does not send that field. Correct the key. |

## Limitations

- The event API is part of `cherrymountain_sim`. The weather federate on
  sim-ctl serves it. A federate is one program of the HELICS co-simulation. The
  ci variant has no weather federate, and thus no API.
- A tunnel that the component creates stays open until the C2 client of sim-ctl
  goes away.
- The component posts each event once. There is no retry. To repeat or
  randomize events, use SCORCH `loop` with `replace`.
