# Traffic Generator

## Metadata Options

```
metadata:
  scripts:
    trafficServer: /phenix/topologies/trafficgen-test/scripts/traffic-server.py
    backgroundGen: /phenix/topologies/trafficgen-test/scripts/background-gen.py
    malwareGen: /phenix/topologies/trafficgen-test/scripts/malware-gen.py
  targets:
  - hostname: traffic-server # default value if not provided
    interface: IF0 # default value if not provided
    duration: 30
    backgroundClient:
      hostname: background-gen
      rate: 10000
      probability: .01
    malwareClient:
      hostname: malware-gen
      rate: 20
      probability: 1.25
```

Each start command waits for the VM's miniccc client, for
`PHENIX_CC_CLIENT_GRACE` seconds (default 300) at most. The stop and cleanup
stages wait `PHENIX_CC_TEARDOWN_GRACE` seconds (default 20) at most for each
client, so that one VM without a client cannot use up the time phenix gives a
canceled run's teardown. They run their command in every VM even when one has no
client, then fail naming each VM they could not reach.
