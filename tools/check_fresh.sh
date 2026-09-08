#!/usr/bin/env bash
# Knowledge-freshness drift guard.
#
# Regenerates every generated cache from the current sibling-repo sources and
# fails when the working tree changed as a result. `config/.index_build_time`
# is excluded — it is re-stamped on every run by design, so it must not count
# as drift. Run locally after upstream sources change, or from CI (scheduled)
# to catch the "caches went stale" failure mode automatically.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "check_fresh: regenerating generated caches (refresh_all.sh)"
if ! bash tools/refresh_all.sh >/tmp/check_fresh_refresh.log 2>&1; then
    echo "check_fresh: refresh_all.sh failed:"
    tail -20 /tmp/check_fresh_refresh.log
    exit 1
fi

changed="$(git status --porcelain -- config | grep -v index_build_time || true)"
if [ -n "$changed" ]; then
    echo "check_fresh: generated caches are STALE — commit the regenerated files:"
    echo "$changed"
    exit 1
fi

echo "check_fresh: generated caches are fresh."
