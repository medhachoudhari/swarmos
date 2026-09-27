#!/usr/bin/env bash
#
# SWARMOS launcher - Edge-AI Based Distributed Fleet Coordination for AMRs
# SIH26123 / Bharat Electronics Limited
#
# Usage:
#   ./run.sh                 start the server on port 8770
#   ./run.sh 8080            start on a different port
#   ./run.sh --open [PORT]   start, wait for health, then open a browser
#   ./run.sh --demo [PORT]   --open, and also start the reference demo run
#   ./run.sh --test          run the test suite instead
#   ./run.sh --check         environment check only, then exit
#
# Deliberately portable: tools/run_server.sh pins an absolute interpreter that
# only exists on the author's machine. This script discovers a usable Python
# instead, so an evaluator can start the project on a clean laptop.
set -u

cd "$(dirname "$0")" || exit 1
MIN_MINOR=10

# The reference demo. Fleet 8 is the MEASURED parity point against the baseline
# policy at 1800 ticks on rush_50 (20 completions against 22), so the demo can
# be shown without overclaiming throughput. The differentiation is what happens
# after a fault is injected, not the raw task count.
DEMO_SCENARIO="rush_50"
DEMO_SEED=11
DEMO_FLEET=8

find_python() {
    # The build machine ships 3.4.1 as "python3", which cannot parse this
    # codebase (it uses the 3.10+ "X | Y" annotation syntax). So version is
    # checked, never assumed.
    local candidates=(
        "/pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3"
        "python3.12" "python3.11" "python3.10" "python3" "python"
    )
    for c in "${candidates[@]}"; do
        if command -v "$c" > /dev/null 2>&1 || [ -x "$c" ]; then
            if "$c" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $MIN_MINOR) else 1)" 2>/dev/null; then
                echo "$c"
                return 0
            fi
        fi
    done
    return 1
}

find_browser() {
    # Ordered by how likely it is to already be running a session the user can
    # see. Returning empty is not an error: the URL is always printed too.
    local candidates=(
        "xdg-open"
        "/pkg/google-chrome-/125.0.6422.112/x86_64-linux/bin/google-chrome"
        "/pkg/mozilla-firefox-/140.2.0esr/x86_64-linux4.18-glibc2.28/bin/firefox"
        "google-chrome" "chromium" "firefox"
    )
    for c in "${candidates[@]}"; do
        if command -v "$c" > /dev/null 2>&1 || [ -x "$c" ]; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

PY="$(find_python)" || {
    echo "ERROR: no Python 3.${MIN_MINOR}+ found." >&2
    echo "SWARMOS needs 3.${MIN_MINOR}+ for PEP 604 annotations (X | Y)." >&2
    exit 1
}
echo "python:  $PY  ($("$PY" --version 2>&1))"

missing=""
for mod in starlette uvicorn pydantic; do
    "$PY" -c "import $mod" 2>/dev/null || missing="$missing $mod"
done
if [ -n "$missing" ]; then
    echo "ERROR: missing required modules:$missing" >&2
    echo "Install with: $PY -m pip install starlette uvicorn pydantic" >&2
    exit 1
fi
echo "deps:    starlette, uvicorn, pydantic present"

MODE="serve"
case "${1:-}" in
    --test)
        # PYTEST_DISABLE_PLUGIN_AUTOLOAD is required on the build machine: a
        # stale site-wide plugin raises PluginValidationError at collection.
        echo "running test suite..."
        exec env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
            "$PY" -m pytest tests/ -q
        ;;
    --check)
        "$PY" -c "import sys; sys.path.insert(0, '.'); \
from app.sim.engine import SimEngine; from app.sim.scenarios import SCENARIOS; \
e = SimEngine(SCENARIOS['rush_50'], seed=11); e.run(20); \
print('engine:  OK, 20 ticks, trace_hash=' + e.trace_hash)"
        echo "check:   passed"
        exit 0
        ;;
    --open)
        MODE="open"
        shift
        ;;
    --demo)
        MODE="demo"
        shift
        ;;
esac

PORT="${1:-8770}"
URL="http://127.0.0.1:${PORT}"

if [ "$MODE" = "serve" ]; then
    echo ""
    echo "SWARMOS starting on ${URL}"
    echo "Open that URL in a browser. Press Ctrl-C to stop."
    echo ""
    exec "$PY" -m uvicorn app.api.server:app \
        --host 127.0.0.1 --port "$PORT" --log-level warning
fi

# ---------------------------------------------------------------------------
# --open / --demo. The server runs in the background only long enough to be
# handed a browser, then this script waits on it so Ctrl-C still stops it.
# ---------------------------------------------------------------------------
echo ""
echo "SWARMOS starting on ${URL}  (mode: ${MODE})"
"$PY" -m uvicorn app.api.server:app \
    --host 127.0.0.1 --port "$PORT" --log-level warning &
SERVER_PID=$!

# Only ever signal the PID we started. Never pattern-match on uvicorn: a
# pkill -f would also match the shell that is running this script.
cleanup() {
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

# Poll /api/health rather than sleeping a guessed interval. A fixed sleep is
# either a slow start or a race, and on a projector it is always the race.
echo -n "health:  waiting"
READY=0
for _ in $(seq 1 60); do
    if "$PY" - "$URL" <<'PYEOF' 2>/dev/null
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1] + "/api/health", timeout=1) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PYEOF
    then
        READY=1
        break
    fi
    echo -n "."
    sleep 0.5
done
echo ""

if [ "$READY" != "1" ]; then
    echo "ERROR: the server did not answer ${URL}/api/health within 30 s." >&2
    echo "Check the output above for a traceback, or try a different port." >&2
    exit 1
fi
echo "health:  OK"

if [ "$MODE" = "demo" ]; then
    # Start the reference run server-side, so the map is already moving when
    # the browser attaches. This is what the live demo opens with.
    "$PY" - "$URL" "$DEMO_SCENARIO" "$DEMO_SEED" "$DEMO_FLEET" <<'PYEOF'
import json, sys, urllib.request
url, scenario, seed, fleet = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
body = json.dumps({"scenario": scenario, "seed": seed, "fleet_size": fleet}).encode()
req = urllib.request.Request(
    url + "/api/sim/start", data=body,
    headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()
    print("demo:    %s, seed %d, fleet %d - running" % (scenario, seed, fleet))
except Exception as err:
    # Not fatal. The UI carries a Start demo run button for exactly this case.
    print("demo:    could not auto-start (%s)" % err)
    print("         press Start demo run in the browser instead.")
PYEOF
fi

BROWSER="$(find_browser)" || BROWSER=""
if [ -n "$BROWSER" ]; then
    echo "browser: $BROWSER"
    "$BROWSER" "$URL" > /dev/null 2>&1 &
else
    echo "browser: none found on PATH"
fi

echo ""
echo "SWARMOS is live at ${URL}"
echo "If the page did not open, paste that URL into a browser."
echo "Remote host? Forward the port first:  ssh -L ${PORT}:127.0.0.1:${PORT} $(hostname)"
echo "Press Ctrl-C to stop."
echo ""
wait "$SERVER_PID"
