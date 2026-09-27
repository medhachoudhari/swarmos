#!/bin/bash
# SWARMOS test runner
#
# The default python3 on this machine is Python 3.4.1 (old Anaconda) and is
# NOT compatible with this project (pyproject.toml requires >= 3.11).
# This script pins the correct interpreter.
#
# Verified baseline on 2026-09-20: 296 passed in 0.84s
#
# Note on dependencies: the pinned interpreter already provides
# pydantic 2.3.0 and pytest 7.4.0, which satisfy pyproject.toml. A local
# .venv is therefore not required, and is in fact not usable here because
# the corporate proxy performs TLS interception and pip cannot verify the
# PyPI certificate chain. If you are on a machine with normal network
# access, a .venv works fine:
#
#   python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
#
# Usage:
#   ./run_tests.sh                 # full suite, quiet
#   ./run_tests.sh -v              # verbose
#   ./run_tests.sh tests/test_auction.py
#   ./run_tests.sh -k auction      # only matching tests

set -euo pipefail

PYTHON_BIN="${SWARMOS_PYTHON:-/pkg/fs-foundation-/dynamic/bin/python3.11}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: interpreter not found: $PYTHON_BIN" >&2
    echo "Override with: SWARMOS_PYTHON=/path/to/python3.11 ./run_tests.sh" >&2
    exit 1
fi

PY_VER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$PY_VER" in
    3.1[1-9]|3.[2-9]*) : ;;
    *)
        echo "ERROR: Python $PY_VER found, but >= 3.11 is required." >&2
        exit 1
        ;;
esac

cd "$REPO_ROOT"

if [ $# -eq 0 ]; then
    set -- -q
fi

echo "SWARMOS tests | python $PY_VER | $PYTHON_BIN"
echo "-------------------------------------------------------------"
PYTHONPATH="$REPO_ROOT" exec "$PYTHON_BIN" -m pytest "$@"

# File contains AI-generated response based on internal company sources
