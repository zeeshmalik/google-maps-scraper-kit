#!/bin/bash
# Cheap keep-alive watcher for Claude Code cloud sessions. The container only stays up while the session
# has work running, so Claude starts this with run_in_background (2h timeout) and re-starts it each time
# it exits. The exit code says what happened, so a quiet heartbeat costs Claude a single tool call:
#   0  = heartbeat after ~112 min, nothing to do: just start it again
#   10 = the supervisor wrote a line to $OPS/notify (e.g. a region finished): deliver it, clear the file
#   11 = the supervisor is not running (crashed or finished): read $OPS/queue.out
OPS=${OPS_DIR:-/root/gmaps-ops}
cd "$(dirname "$0")/../.." || exit 1
bash scripts/ops/recover.sh
for i in $(seq 1 225); do
  if [ -s "$OPS/notify" ]; then cat "$OPS/notify"; exit 10; fi
  if ! { [ -f "$OPS/queue.pid" ] && kill -0 "$(cat "$OPS/queue.pid")" 2>/dev/null; }; then
    echo SUPERVISOR_DEAD; tail -5 "$OPS/queue.out" 2>/dev/null; exit 11
  fi
  sleep 30
done
echo HEARTBEAT; tail -1 "$OPS/queue.out" 2>/dev/null
