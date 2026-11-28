#!/bin/bash
# phenix startup hook on the sim-ctl of a site of the fleet (cherrymountain
# app): start the site's own HELICS broker. Startup scripts run in name order,
# so the broker starts before 60-cm-federates.sh starts the federates, which
# retry until it answers. --no-block: this runs inside phenix.service.
set -euo pipefail

settings=/etc/default/cm-helics-broker
[ -f "${settings}" ] || { echo "cm-helics-broker: ${settings} is missing" >&2; exit 1; }

systemctl daemon-reload
systemctl enable --now --no-block cm-helics-broker.service
