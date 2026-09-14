# syntax=docker/dockerfile:1.7
# Node-RED for the lab-compliance flow (GOAL "Node-RED flow imports and runs
# against the same broker"). Only node-red core nodes, the MQTT nodes that
# ship with it, and @flowfuse/node-red-dashboard are available — the flow may
# use nothing else.

FROM nodered/node-red:4.1.0

# The base image already runs as the unprivileged `node-red` user (uid 1000)
# and owns /usr/src/node-red, so the dashboard installs without root.
RUN npm install --no-audit --no-fund --no-update-notifier \
    @flowfuse/node-red-dashboard@1.31.0

# Seed the persistent userDir from the repo's flow on first start, then hand
# over to the stock Node-RED entrypoint. Once the volume has a flows.json,
# edits deployed from the editor win and are never overwritten.
COPY <<'SEED' /usr/src/node-red/seed-flows.sh
#!/bin/sh
set -e
if [ -f /flows/flow.json ] && [ ! -f /data/flows.json ]; then
  cp /flows/flow.json /data/flows.json
  echo "seeded /data/flows.json from /flows/flow.json"
fi
if [ -f /flows/settings.js ] && [ ! -f /data/settings.js ]; then
  cp /flows/settings.js /data/settings.js
  echo "seeded /data/settings.js from /flows/settings.js"
fi
exec "$@"
SEED
USER root
RUN chmod 0555 /usr/src/node-red/seed-flows.sh
USER node-red

ENTRYPOINT ["/usr/src/node-red/seed-flows.sh"]
CMD ["npm", "--no-update-notifier", "--no-fund", "start", "--cache", "/data/.npm", "--", "--userDir", "/data"]
EXPOSE 1880
