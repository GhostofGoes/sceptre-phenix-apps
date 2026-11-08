### mirror

The `mirror` app configures cluster-wide packet mirroring for specific VLANs
to a specific interface on a predefined node using GRE tunnels.

For example, let's assume the app is configured as follows in the scenario
file:

```yaml
apiVersion: phenix.sandia.gov/v2
kind: Scenario
metadata:
  name: foobar
  annotations:
    topology: traffic-gen
spec:
  apps:
  - name: mirror
    hosts:
    - hostname: monitor
      metadata:
        interface: IF0
        vlans:
        - EXP_1
```

Given the above configuration, each cluster host participating in the
experiment except for the cluster host the `monitor` VM is scheduled on will
create a GRE tunnel port in OVS to the cluster host the `monitor` VM is
scheduled on. Each cluster host will also create an OVS mirror that includes
taps from all VMs with an interface in the `EXP_1` VLAN that are not routers
or firewalls, using the GRE tunnel as the destination port for the mirrored
traffic, except for the cluster host the `monitor` VM is scheduled on, which
will instead use the tap of the `IF0` interface for the `monitor` VM as the
mirror destination.

#### Output

The app prints the experiment it read with `metadata`, `spec` and `status` as
the stage left them. Other top-level fields pass through unchanged, but fields
inside those three that the phenix types the app is built with do not know are
dropped.

#### Failures

The app exits 1 without printing the experiment when a stage fails, when it is
not given exactly one argument (the stage), when that is not one of
`configure`, `pre-start`, `post-start`, `running` and `cleanup` (or
`version`), or when stdin is not an experiment, so phenix fails the stage. A failing `post-start` first removes the
taps and mirrors it created, and the app records `status.apps.mirror` only
when `post-start` succeeds. `cleanup` has nothing to remove without that
status, as after a failed start, and succeeds.
