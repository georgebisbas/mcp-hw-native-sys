#!/usr/bin/env bash
# Refresh every generated knowledge index from its current upstream source in
# the hw-native-sys workspace, then self-audit the result.
#
# Upstream sources (each lives in a sibling repo and drifts independently):
#   - config/passes_index.json        <- pypto/python/pypto/ir/pass_manager.py
#   - config/pto_isa_generated.json   <- pto-isa/docs/isa/manifest.yaml + comm/README.md
#   - config/ptoas_generated.json     <- PTOAS PTOOps.td / VPTOOps.td
#   - config/program_status.json      <- pypto-3.0-notes/pr_plans/status_prs.md
#   - config/collective_status.json   <- pypto-3.0-notes/distributed/current_status.md
#   - config/simpler_scheduler.json   <- simpler scheduler trees + L0-L6 table
#   - config/pypto_lib_workloads.json <- pypto-lib/docs/models/index.md + models/
#
# Run it whenever those sources change (or before a knowledge-heavy session) so
# explain_pass / explain_abstraction / program_status / collective_status do not
# serve stale data. The generators only read from the sibling repos and never
# touch the hand-curated config/abstractions.json (hand cards always win).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

echo "[1/7] pto-isa instruction cards  (build_pto_isa_index.py)"
"$PY" tools/build_pto_isa_index.py

echo
echo "[2/7] PTOAS op cards            (build_ptoas_index.py)"
"$PY" tools/build_ptoas_index.py

echo
echo "[3/7] pypto pass index          (build_knowledge_index.py)"
"$PY" tools/build_knowledge_index.py

echo
echo "[4/7] PR status                 (sync_status_to_json.py)"
"$PY" tools/sync_status_to_json.py

echo
echo "[5/7] collective parity matrix  (sync_collective_status_to_json.py)"
"$PY" tools/sync_collective_status_to_json.py

echo
echo "[6/7] simpler scheduler index   (build_simpler_scheduler_index.py)"
"$PY" tools/build_simpler_scheduler_index.py

echo
echo "[7/7] pypto-lib workloads       (build_pypto_lib_workloads.py)"
"$PY" tools/build_pypto_lib_workloads.py

# build_knowledge_index.py already stamped config/.index_build_time at step 3;
# re-stamp now so the marker records the whole refresh, not just the pass scrape.
"$PY" -c "from datetime import datetime, timezone; from pathlib import Path; Path('config/.index_build_time').write_text(datetime.now(timezone.utc).isoformat(), encoding='utf-8')"

echo
echo "[audit] verifying every config path resolves (verify_knowledge_config.py)"
set +e
"$PY" tools/verify_knowledge_config.py
rc=$?
set -e
exit "$rc"
