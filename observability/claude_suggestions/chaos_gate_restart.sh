#!/usr/bin/env bash
# Measures how long the stack takes to recover after the gRPC gate container gets a NEW IP.
# Fails if recovery exceeds MAX_RECOVERY_S. Run from the repo root with the compose stack up.
#
#   PROBE_CMD='curl -fsS -X POST http://localhost:8080/<a checkout path that calls the gate> -d @probe.json -H "Content-Type: application/json"' \
#   bash chaos/chaos_gate_restart.sh
#
# PROBE_CMD must exit 0 only when a request that goes THROUGH the gate succeeds (a CHALLENGE decision
# produced by an OPEN breaker must exit non-zero, so make the probe check the response body).
set -euo pipefail
: "${PROBE_CMD:?set PROBE_CMD to a command that succeeds only when the gate path works}"
GATE_SERVICE="${GATE_SERVICE:-fraud-gate-grpc}"
COMPOSE=(${COMPOSE:-docker compose})
MAX_RECOVERY_S="${MAX_RECOVERY_S:-15}"
LOAD_CMD="${LOAD_CMD:-}"                       # optional background load, e.g. a short k6 run

ip_of() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$("${COMPOSE[@]}" ps -q "$GATE_SERVICE")"; }

eval "$PROBE_CMD" >/dev/null 2>&1 || { echo "probe fails BEFORE the experiment; fix PROBE_CMD first"; exit 2; }
BEFORE="$(ip_of)"; NET="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$("${COMPOSE[@]}" ps -q "$GATE_SERVICE")")"
echo "gate IP before: $BEFORE (network $NET)"

[ -n "$LOAD_CMD" ] && { eval "$LOAD_CMD" >/tmp/chaos_load.log 2>&1 & LOAD_PID=$!; trap 'kill ${LOAD_PID:-0} 2>/dev/null || true; docker rm -f chaos-ipsquat-1 chaos-ipsquat-2 >/dev/null 2>&1 || true' EXIT; }

"${COMPOSE[@]}" stop "$GATE_SERVICE" >/dev/null
# squat the freed address so the restarted gate cannot get it back
for n in 1 2; do docker run -d --rm --name "chaos-ipsquat-$n" --network "$NET" alpine sleep 120 >/dev/null; done
"${COMPOSE[@]}" start "$GATE_SERVICE" >/dev/null
START=$(date +%s.%N)
AFTER="$(ip_of)"; echo "gate IP after:  $AFTER"
[ "$BEFORE" != "$AFTER" ] || { echo "IP did not change; experiment invalid (add more squatters)"; exit 3; }

while true; do
  if eval "$PROBE_CMD" >/dev/null 2>&1; then break; fi
  NOW=$(date +%s.%N); ELAPSED=$(python3 -c "print(round($NOW-$START,1))")
  python3 -c "import sys; sys.exit(0 if $ELAPSED < $MAX_RECOVERY_S + 60 else 1)" || { echo "no recovery after ${ELAPSED}s"; exit 4; }
  sleep 0.5
done
END=$(date +%s.%N); RECOVERY=$(python3 -c "print(round($END-$START,1))")
echo "recovery after IP change: ${RECOVERY}s (limit ${MAX_RECOVERY_S}s)"
python3 -c "import sys; sys.exit(0 if $RECOVERY <= $MAX_RECOVERY_S else 1)" || { echo "FAIL: slower than ${MAX_RECOVERY_S}s"; exit 1; }
echo "PASS"
