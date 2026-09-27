#!/bin/bash
# Launch the SWARMOS server. Port is overridable: tools/run_server.sh 8080
PORT="${1:-8999}"
cd "$(dirname "$0")/.." || exit 1
exec /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 -m uvicorn \
    app.api.server:app --host 127.0.0.1 --port "$PORT" --log-level warning
