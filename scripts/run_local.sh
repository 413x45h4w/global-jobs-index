#!/usr/bin/env bash
# Refresh the local database and the static dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m jobdir run "$@"
