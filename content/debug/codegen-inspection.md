# Debugging by Inspecting Generated Code — Pipeline-Wide

MCP-owned decision tree. When debugging a compile, codegen, or lowering bug, an
agent should (1) decide which stage the symptom belongs to, (2) produce that
stage's artifact with the right switch, (3) locate it, and (4) inspect or diff
it with the right tool. The canonical per-repo docs below are the authority;
this page is the map between stages and switches.

Scope: pypto (DSL → IR passes → InCore `.pto` → ptoas → kernel C++) and
pypto-lib (orchestration + runtime + dfx). PTOAS / pto-isa / simpler stages are
noted where the pypto flow hands off to them.

## Stage table

| # | Stage | Artifact to inspect | Produce it with | Lands at | Inspect with |
|---|-------|--------------------|------------------|----------|--------------|
| 0 | DSL source | `@pl.jit` kernel / `@pl.program` class | n/a (author) | repo source | read the kernel file |
| 1 | Pass pipeline | IR snapshot after each pass | `ir.compile(..., dump_passes=True)` or `PassDumpLevel.EXPLICIT`; JIT path `RunConfig(dump_passes=...)` | `passes_dump/00_frontend.py`, `NN_after_<PassName>.py` | read as Python-IR text; `explain_pass`/`explain_abstraction`; per-pass docs in `pypto/docs/en/dev/passes/` |
| 2 | Backend (ptoas) passes | full-module IR after each ptoas pass | `ir.compile(..., dump_ptoas_passes=True)`; JIT path `RunConfig(dump_ptoas_passes=True)` | `ptoas_passes/<kernel-or-group>/` | read as MLIR text; no effect with `skip_ptoas=True` |
| 3 | InCore codegen | `.pto` MLIR text | default codegen; keep raw units with `skip_ptoas=True` | `ptoas/*.pto` (or `ptoas/` dir) | read as MLIR; `skip_ptoas` isolates pypto IR→MLIR bugs from ptoas bugs |
| 4 | Kernel C++ | ptoas-generated AIC/AIV wrappers | default codegen (ptoas step) | `kernels/aic/*.cpp`, `kernels/aiv/*.cpp` | read_file; clang-tidy before C++ edits |
| 5 | Orchestration C++ | AICPU orchestration source + built `.so` | default codegen (`generate_orchestration`) | `orchestration/*.cpp` (+ compiled `.so`) | read_file; task-graph semantics via `simpler` docs |
| 6 | Config / runtime / dfx | kernel registry, I/O data, DFX artifacts | runtime phase; `--enable-chip-swimlane` etc. | `kernel_config.py`, `data/in|out/`, `dfx_outputs/`, `report/` | pypto-lib runtime-dfx doc; swimlane tooling |

Output root for pypto-lib harness runs is `build_output/<ProgramName>_<timestamp>/`
(with `passes_dump/`, `ptoas/`, `kernels/{aic,aiv}/`, `orchestration/`,
`kernel_config.py`, `report/`, `data/`, `dfx_outputs/` subdirs). pypto's own
test/example flows may write to a `build/` or `build_output/` root instead —
`find_generated_artifacts` locates whatever exists.

## Read-first docs (canonical)

- `pypto/docs/en/dev/07-ir-lower-trace.md` — pass dumps, ptoas dumps, `pypto-ir-trace` HTML report.
- `pypto/docs/en/dev/codegen/00-pto_codegen.md` — InCore `.pto` codegen.
- `pypto/docs/en/dev/codegen/01-orchestration_codegen.md` — AICPU orchestration C++.
- `pypto/docs/en/dev/03-runtime-dfx.md` — runtime DFX (swimlanes, args dumps).
- `pypto/docs/en/user/tools/00-debugging.md` — user-level debugging walkthrough.
- `pypto-lib/docs/run-and-validate/compile-runtime-workflow.md` — full harness flow + output layout.
- `pypto-lib/docs/debug-and-tune/debugging.md` — pypto-lib debugging playbook.

## Inspection recipes (branch/artifact tooling)

| Goal | Tool / skill | Notes |
|------|--------------|-------|
| Turn a `passes_dump/` dir into a standalone HTML lowering trace | `pypto-ir-trace <dump>` CLI; skill `generate-ir-trace` | canonical doc `07-ir-lower-trace.md`; skill lives in `pypto-skills/plugins/pypto-user/skills/generate-ir-trace/` |
| Diff generated code (`.pto`, pass dumps) between branches | skill `compare-codegen` | runs a `tests/st/...` pytest node id with `--save-kernels` + `--dump-passes` on both branches via git worktree; writes `build_output/compare_<ts>/` |
| Profile generated kernels in-core (cycles, pipes) | skill `incore-profiling` | msprof op simulator; per-kernel traces |
| Isolate IR→MLIR vs ptoas regressions | recompile with `skip_ptoas=True` | keeps raw `.pto`, skips C++ wrapper step |
| Inspect a single pipeline stage's IR text | `read_doc`/`read_file` on the dumped snapshot | pass dumps are Python-IR text; `.pto` is MLIR text |

Skills also exist for the sibling layers: pypto-lib `debug-and-tune/*` docs
(perf, dependency/scheduling, incore-simulator), `simpler` skills
(`dfx-analyze`, `insight-trace`, `core-swimlane`), `pypto-tooling/debugging_skills`
(NPU error codes: 507018 / 507033 / 507899 triage), PTOAS
(`debug-matmul-mx`, `msprof-op-simulator-insight`). Use `list_skills` /
`find_skill` to enumerate them.

## Pitfalls

- `dump_ptoas_passes` does nothing when `skip_ptoas=True`.
- The default strategy keeps only the final pass list; the exact pass order
  changes often — consult `passes_index.json` / `explain_pass` for the current
  Default pipeline, not memory.
- `@pl.jit` kernels inherit `RunConfig`'s disabled dump defaults; `@pl.program`
  kernels inherit `ir.compile`'s enabled defaults — check which surface your
  case uses before assuming dumps exist.
- After changing which artifact you inspect, re-run `refresh_all.sh` if you also
  changed pypto pass docs; generated indexes are snapshots, not live.
