# Management tap user application

This user application will create a tap on the management network of the
experiment it is assigned to, allowing a user to copy files to and from
machines in the network as long as the vm has a connection to the
management network.

E.g.
```yaml
- name: mgmt_tap
  metadata:
    subnet: 172.16.0.0/16
    vlan: MGMT_1
    bridge: phenix
```

## Metadata

| Key      | Required | Default                                   | Description                                        |
| -------- | -------- | ----------------------------------------- | -------------------------------------------------- |
| `subnet` | no       | `172.16.0.0/16`                           | Subnet used to address the host taps.               |
| `vlan`   | no       | `MGMT`                                    | VLAN alias the tap is attached to.                  |
| `bridge` | no       | experiment `spec.defaultBridge` (`phenix`) | OVS bridge the host tap is created on.              |

If `bridge` is not set, the app uses the experiment's `spec.defaultBridge`.
If the experiment does not define one, it falls back to `phenix`.

## Host tap

In `post-start`, the app creates a host tap on every cluster host, in the
experiment's minimega namespace (its full name), on the `vlan` alias and
`bridge`, addressed from `subnet` in host order. The tap is named `mgmt_`
followed by the first nine hex digits of the SHA-256 of the experiment name,
which keeps it within the 14 characters minimega allows and distinct for
experiments whose names share a prefix. A failing `tap create` fails
`post-start`, naming the host, and so do a host that gives no reply, which is
what minimega answers for a host its mesh has no route to, and a minimega that
cannot be reached. In `cleanup`, the app deletes the tap from every host,
ignoring hosts where it is already gone, and then fails naming each host where
the delete failed for any other reason or gave no reply.

A dry run checks the `vlan` alias and `subnet` but creates and deletes no tap,
since its VLANs are not real.

If minimega restarts with `-recover` while the experiment runs, it puts the tap
back on its bridge but no longer counts it as the namespace's, and no minimega
command can delete it then. `cleanup` fails with
`not a host tap in active namespace`, and the next start of the experiment
fails in `post-start` with `tap already on bridge`, since the tap name depends
only on the experiment name. The experiment stop still kills its VMs, but phenix
stops applying the apps of a stage at the first one that fails, so the apps
after `mgmt_tap` are not cleaned up either. Removing the tap from OVS alone does
not help: minimega keeps it in memory until it restarts. To recover, do steps 1
and 2 on each host the error names, then step 3 once:

1. Remove the tap and its address from the host with
   `ovs-vsctl --if-exists del-port <bridge> <tap>`, where `<tap>` is the
   `mgmt_` name `ovs-vsctl list-ports <bridge>` shows.
2. Stop minimega, delete the tap's line from the `taps` file in its base
   directory (`/tmp/minimega` by default), and start it again. A stop with
   SIGTERM also kills every VM minimega runs; to keep them, stop it with
   SIGKILL and start it again with `-recover`.
3. Run the cleanup the failure skipped with
   `phenix experiment trigger cleanup <experiment> mgmt_tap <app> ...`, naming
   the apps after `mgmt_tap`. `mgmt_tap` now finds no tap and succeeds.

## Upgrading

Earlier releases named the tap `<name[:9]>_<name[:4]>`, with its second part
lowercased, in the minimega namespace `<name[:9]>`, and ignored a failing
`tap create`. Stop
experiments started with such a release before upgrading: cleanup deletes only
the new tap name, and deleting the old one could remove the tap of another
experiment sharing the prefix.
