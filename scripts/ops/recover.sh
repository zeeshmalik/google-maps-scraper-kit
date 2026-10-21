#!/bin/bash
# Idempotent keep-alive for Claude Code cloud sessions: bring Docker, the scraper container and the
# long-running supervisor back after the container restarts. Safe to run any time (SessionStart hook,
# scheduled routine, keepalive.sh).
#
# The supervisor is whatever $OPS/queue.sh runs (it should `exec` the real process so the pid sticks).
# Optional $OPS/on_restart.sh runs after a Docker restart, e.g. to drop jobs the restart orphaned.
OPS=${OPS_DIR:-/root/gmaps-ops}
mkdir -p "$OPS"
cd "$(dirname "$0")/../.." || exit 1
echo "$(date -u +%F' '%H:%M) recover" >> "$OPS/recover.log"

RESTARTED=0
if ! docker info >/dev/null 2>&1; then
  RESTARTED=1
  (setsid nohup dockerd >> "$OPS/dockerd.log" 2>&1 < /dev/null &)
  for i in $(seq 1 40); do docker info >/dev/null 2>&1 && break; sleep 1; done
fi
docker compose up -d >/dev/null 2>&1
for i in $(seq 1 60); do
  [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://localhost:8080/api/v1/jobs)" = 200 ] && break
  sleep 2
done

pid() { cat "$OPS/queue.pid" 2>/dev/null; }
alive() { [ -n "$(pid)" ] && kill -0 "$(pid)" 2>/dev/null; }

# The scraper's in-flight job does not survive a restart: stop the supervisor, let on_restart.sh clean up.
if [ $RESTARTED = 1 ]; then
  alive && kill -TERM "$(pid)" && sleep 3
  [ -f "$OPS/on_restart.sh" ] && bash "$OPS/on_restart.sh"
fi
# A session reconnect can move the outbound proxy port; a supervisor holding the old one can't get out.
if alive && [ -n "$HTTPS_PROXY" ] &&
   [ "$(tr '\0' '\n' < /proc/"$(pid)"/environ | grep '^HTTPS_PROXY=' | cut -d= -f2-)" != "$HTTPS_PROXY" ]; then
  kill -TERM "$(pid)"; sleep 3
fi
if [ -f "$OPS/queue.sh" ] && ! alive; then
  setsid nohup bash -c "echo \$\$ > '$OPS/queue.pid'; exec bash '$OPS/queue.sh'" >> "$OPS/queue.out" 2>&1 < /dev/null &
  sleep 3
fi
echo "docker=$(docker info >/dev/null 2>&1 && echo up || echo down)" \
     "api=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://localhost:8080/api/v1/jobs)" \
     "queue_pid=$(pid)"
