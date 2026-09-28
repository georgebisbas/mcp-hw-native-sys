# hw-native-sys MCP server

A local Model Context Protocol (MCP) server for full-stack compiler development across the hw-native-sys workspace. It combines **operations** (git health, code search, running named tasks) with a **knowledge layer** (architecture docs, task routing, an abstraction index, pass pipeline info, cross-repo status) so an agent — or you — can get oriented in one or two calls instead of grepping five repos by hand. pypto-lib is the model layer and compiles through pypto. InCore kernels then lower `pypto → PTOAS → pto-isa` and run on simpler; orchestration goes `pypto → simpler` directly.

This doc is the full reference: setup, every tool/resource/prompt, the config files behind them, how the knowledge index is built and kept honest, and how to extend the server yourself.

## Repositories it operates over

| Repo | Role |
|------|------|
| `pypto` | Compiler framework: Python DSL → IR → passes → codegen |
| `PTOAS` | PTO assembler/optimizer: `.pto` MLIR → AICore/AIV kernel C++ |
| `pto-isa` | Virtual tile ISA: C++ headers, CPU/NPU backends |
| `simpler` | simpler runtime: task graph execution on AICore/AICPU |
| `pypto-lib` | Model zoo and golden validation harness |
| `pypto-3.0-notes` | Enriched planning notes, retrospectives, cross-repo status (secondary tier — not canonical) |
| `pypto_top_level_documents` | Top-level design/architecture proposals (design tier — non-canonical, forward-looking) |
| `pytorch-hccl-tests` | OSU-style PyTorch/HCCL bandwidth micro-benchmarks (NPU) |
| `pypto-tooling` | Umbrella: agent skills, runbooks, task-submit doc |
| `pypto-skills` | Shared agent-skill plugins (`pypto-user`, `pypto-developer`) |
| `pypto-docker` | Docker images and build scripts for the pypto stack (this server's sim images) |
| `pypto-profiling` | Collective benchmark harness (pypto vs simpler vs HCCL) |
| `pypto-tools` | VS Code toolkit: chip swimlane viewer, task dependency graph, perf table over dfx outputs |
| `pypto.wiki` | Wiki clone: weekly project-changes log |
| `mcp-hw-native-sys` | This MCP server |

## Setup

From a checkout of this repo, next to the sibling stack repos:

```bash
cd mcp-hw-native-sys
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires Python ≥ 3.10, the `mcp` package (installed by the command above), and `rg` (ripgrep) on `PATH` for `search_code`. `search_tracker` also needs the GitHub CLI (`gh`) logged in to an account that can read the `hw-native-sys` org. The server does not pick a model. Cursor, VS Code, Claude Code, and Claude Desktop each choose Claude, GPT, Gemini, Grok, or whatever else that client offers; the tools and prompts are the same.

### Workspace root resolution

The server needs to know where the sibling repos live. In order of precedence:

1. `HW_NATIVE_SYS_ROOT` env var, if set.
2. `config/repos.json`'s `"workspace_root"` field. It is checked in as `".."`, resolved from this repo, so the parent directory that holds the sibling repos. That is the path a normal checkout uses.
3. Fallback, only when `workspace_root` is empty: `project_root().parents[1]` (the parent of that workspace directory, not the workspace itself).

You generally don't need to set `HW_NATIVE_SYS_ROOT` unless you're running the server from a copy that isn't in its usual place relative to the sibling repos.

### Quick local run (stdio, manual)

```bash
source .venv/bin/activate
hw-native-sys-mcp
```

`HW_NATIVE_SYS_ROOT` is optional. Set it only when this repo is not checked out as `mcp-hw-native-sys/` inside the workspace that holds the sibling repos.

### Clients

The process is a stdio MCP server. The command is `.venv/bin/hw-native-sys-mcp`, relative to this repo. `${workspaceFolder}` below is the directory that contains both this repo and its siblings.

**Cursor.** Project file `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "hw-native-sys-mcp": {
      "command": "${workspaceFolder}/mcp-hw-native-sys/.venv/bin/hw-native-sys-mcp"
    }
  }
}
```

After the command changes, enable the server once under Customize → MCPs. Prompts then show up in chat as `/hw-native-sys-mcp/start_compiler_work`, `/hw-native-sys-mcp/start_ascend_work`, `/hw-native-sys-mcp/start_distributed_work`, `/hw-native-sys-mcp/start_npu_verify`, `/hw-native-sys-mcp/debug_codegen_work`, and `/hw-native-sys-mcp/finish_work`.

**VS Code.** Workspace file `.vscode/mcp.json`:

```json
{
  "servers": {
    "hw-native-sys": {
      "type": "stdio",
      "command": "${workspaceFolder}/mcp-hw-native-sys/.venv/bin/hw-native-sys-mcp"
    }
  }
}
```

**Claude Code.** `.mcp.json` in the workspace root:

```json
{
  "mcpServers": {
    "hw-native-sys": {
      "command": "mcp-hw-native-sys/.venv/bin/hw-native-sys-mcp"
    }
  }
}
```

Tools appear as `mcp__hw-native-sys__<tool_name>`.

**Claude Desktop.** Add a stdio server whose command is the absolute path to `.venv/bin/hw-native-sys-mcp` in your checkout. Desktop configs do not expand `${workspaceFolder}`.

## Recommended daily workflow

1. Call the **`start_compiler_work`** prompt (or `start_distributed_work` / `start_ascend_work` / `start_npu_verify` depending on the task) — this gives you the exact next steps.
2. Call **`bootstrap_session(task_type=...)`** — one call returns route metadata (`read_plan`), repo health, and active-program hints together.
3. Follow `read_plan`: read canonical docs first, enriched docs second. Use **`read_doc(path, section=...)`** to pull a single markdown section out of a large note instead of the whole file.
4. Call **`layer_guide(layer)`** for the framework layer you are in (`pypto`, `ptoas`, `pto-isa`, `simpler`, `pypto-lib`). It returns that repo's docs, skills, and rules. Use **`explain_pass`** / **`explain_abstraction(name, layer=...)`** / **`search_abstractions`** / **`trace_contract`** / **`trace_in_stack`** to pin down stack concepts before writing code. Pass `layer` when the same name exists in two layers (`tmov` in PTOAS vs `TMOV` in pto-isa).
5. Call **`program_status`** for the local plan dashboard, and **`search_tracker`** for live open and merged GitHub issues and PRs. Call **`collective_status`** if the work touches collective communication ops.
6. Implement.
7. Run **`verify_ladder(changed_paths)`** to get the minimal verify set: `suggested_tasks` (pytest) plus `static_checks` — when a changed path is a C/C++ file in a C++ repo, `static_checks` is `["clang-tidy"]` and **clang-tidy on the changed files is required before committing** (see the `tools/clang_tidy_workflow` resource for the compile-db prerequisite and per-repo commands).
8. Run `agent_verify_tasks` via **`run_task`**. Never run `developer_verify_tasks` (NPU/hardware-gated) yourself — those are for the human developer.

## Build & test policy (NPU-or-sim-Docker)

The server never builds/tests directly on a local repo unless NPUs are
reachable. Every heavy (build/test/package) task is routed on
`npu-smi` availability:

- **NPU reachable** → the host `command` runs as configured (host builds allowed).
- **No NPU** → `run_task` re-routes the task into the repo's sim Docker image
  (mounted worktree + in-container install) and reports the redirect in the
  result's `note`. Images: `pypto3-hw-native-sys:sim` (pypto/pto-isa),
  `simpler-hw-native-sys:sim`, `pypto-lib-hw-native-sys:sim` — built from
  `pypto-docker/Dockerfile.*sim.ubuntu22.04`.
- **No NPU + image missing** → the task is refused with the exact `docker build`
  command to create the image first.
- **No sim image for the repo** (e.g. PTOAS) → refused with guidance.
- `run_command` refuses ad-hoc build/test commands (`cmake`/`make`/`ninja`/
  `pip install`/`pytest`/…) when no NPU is reachable; read-only commands are
  unaffected. Tasks whose command already runs in a container are marked
  `sim_docker: true` and bypass routing.

See `content/tools/sim_docker_workflow.md` (MCP resource `tools/sim_docker_workflow`)
for the full loop, and `pypto-3.0-notes/pr_plans/00-branch-and-pr-standards.md`
§ Sim Docker for the canonical iteration loop.

## Tools

### Operations (`mcp_hwnative_sys/server.py`)

| Tool | Purpose |
|------|---------|
| `list_repositories` | Repos, paths, and architecture metadata |
| `repository_health` | Branch, dirty state, ahead/behind upstream, last commit, `active_program_hints` per repo |
| `search_code` | Ripgrep across one/many/all repos. `mode=locations` (default, file+line only) or `mode=context` (+ matched text and surrounding lines); `use_regex`, `file_glob`, `group_by_file` |
| `list_tasks` | Named tasks configured for a repo (from `config/repos.json`), with risk/warning metadata |
| `run_task` | Run a named task in a repo, with `extra_args` and a timeout. Returns `elapsed_ms` and `output_bytes` for cost awareness |
| `run_command` | Ad-hoc shell command in a repo's root; destructive patterns (`git reset --hard`, `rm -rf /`, …) are blocked. Returns `elapsed_ms` and `output_bytes` |
| `explain_task` | Show the exact command + metadata for one named task (repo-first: `explain_task(repo, task)`) |
| `git_log` | Structured commit list (sha, author, date, message) for a repo |
| `git_diff` | `git diff` for a repo, `stat_only` for orientation or full patch text |
| `read_file` | Read an arbitrary source file from a repo (paginated via `offset`/`max_lines`) without shelling out |
| `bootstrap_session` | Single-call session bootstrap: route + `read_plan` + health + program hints |
| `gate_pr_script` | Generate a self-contained bash script for the PR gate (rebase → pre-commit → sim-Docker tests → squash → force-push). Validates preconditions but never executes git/docker itself |

### Knowledge (`mcp_hwnative_sys/knowledge.py` and friends)

| Tool | Purpose |
|------|---------|
| `list_task_types` | All valid `task_type` values (for `route_task`/`bootstrap_session`) with descriptions |
| `route_task` | Read-first docs (canonical + enriched), rules, entrypoints, matching skills, and verify tasks for a `task_type` |
| `list_knowledge_topics` | Enumerate all task routes, MCP resources, notes topics, and bootstrap prompts in one call |
| `read_doc` | Read a workspace doc with tier labeling (`canonical`/`enriched`/`design`/`mcp-owned`); optional `section` extracts one markdown heading |
| `layer_guide` | Docs, skills, and rules for one framework layer (`pypto`, `ptoas`, `pto-isa`, `simpler`, `pypto-lib`, or `all`). Optional `topic` summarizes up to 15 matching docs. Full pages stay on `read_doc` |
| `explain_abstraction` | Concept card for an IR node, pass, codegen stage, ISA instruction, PTOAS op, or Ascend hardware concept. Optional `layer` selects one card when the folded name exists in more than one layer. Reports `source: curated` or `source: generated` |
| `search_abstractions` | Keyword search across the abstraction index. Optional `layer` keeps the search inside one card layer or framework prefix. Results include `by_layer` |
| `explain_scheduler` | simpler scheduler level (`L0`–`L6`), engine (orchestrator / scheduler / worker), or a concrete implementation tree |
| `list_workloads` | pypto-lib model catalog from `docs/models/index.md`. A name returns that model's prefill/decode kernel filenames |
| `explain_task_queue` | Read-only `task-submit` guide: which hosts require the queue, how to join a container, and the failure rules. Does not submit a job. See `pypto-docker/TASK_QUEUE.md` |
| `search_tracker` | Read-only GitHub search of issues and PRs (`open`, `closed`, `merged`). Default repos are PTOAS and pto-isa. Also accepts pypto, simpler, pypto-lib, or `all` of that allowlist |
| `explain_pass` | Pass-pipeline card: order, phase, neighbors, verify tasks (from the `Default` pypto pipeline); on a miss suggests near-name passes |
| `program_status` | Structured open PRs, blockers, and plan cross-index from `pypto-3.0-notes/pr_plans/status_prs.md` |
| `collective_status` | Collective-comm feature parity status (merged/planned/gap) from the parity matrix in `pypto-3.0-notes/distributed/current_status.md`, with optional `op`/`axis` substring filters. Read-only — never writes to the source doc |
| `verify_ladder` | Minimal suggested verify tasks for a list of changed file paths (longest-matching-prefix rules) |
| `find_generated_artifacts` | Locate generated-code artifacts across the workspace: pass dumps, `.pto` MLIR, kernel/orchestration C++, dfx outputs (scans `build_output`/`outputs`/`build` roots, read-only) |
| `list_skills` | Inventory the agent-skill corpus per repo (pypto, pypto-lib, simpler, PTOAS, pto-isa, pypto-* plugins, pypto-tooling), read live from each SKILL.md |
| `find_skill` | Match a task description against every repo's skill names/descriptions to find the right workflow (e.g. compare-codegen, generate-ir-trace, dfx-analyze) |
| `find_entrypoints` | Code entrypoints for a repo and optional sub-area |
| `trace_in_stack` | Locate a symbol or path in the `pypto → PTOAS → pto-isa → simpler` stack (lightweight: abstraction card or path-prefix stage only) |
| `trace_contract` | Enriched cross-layer trace: stack location + contract triangle + cross-layer verify tasks + active-PR links |
| `knowledge_health` | Self-audit: missing paths, stale enriched docs (>30 days since `last_verified`), Ascend corpus checks, pto-isa/PTOAS index **coverage**, pass-index build status |
| `ascend_env_check` | Read-only NPU/CANN/HCCL environment diagnosis (devices, `LD_PRELOAD`, Docker hints) |
| `generate_verify_handoff` | Markdown handoff for a human to run NPU verification. On queue hosts the commands are wrapped in `task-submit --device auto` with `$TASK_DEVICE` inside `--run`. `LD_PRELOAD` is not exported in the client shell |
| `summarize_profile` | Summarize a `pypto-profiling/` campaign directory (`results.json`, anomalies) |

## MCP resources

Fixed URIs, read via an MCP resource client (or by finding the matching path via `read_doc`/`list_knowledge_topics`):

| Prefix | Example URIs | Content |
|--------|--------------|---------|
| `overview/*` | `overview/ecosystem`, `overview/pipeline` | Multi-repo roles, compilation pipeline |
| `pypto/*` | `pypto/ir`, `pypto/passes`, `pypto/codegen`, `pypto/distributed` | pypto subsystem overviews |
| `ptoas/*`, `pto-isa/*`, `simpler/*` | `ptoas/overview`, `pto-isa/overview`, `simpler/overview`, `simpler/l3_distributed_collectives` | Sibling-repo overviews |
| `pypto-lib/*` | `pypto-lib/overview`, `pypto-lib/status`, `pypto-lib/building_blocks`, `pypto-lib/attention`, `pypto-lib/models`, `pypto-lib/distributed_support`, `pypto-lib/moe` | Model zoo / harness layer |
| `pytorch-hccl-tests/*` | `pytorch-hccl-tests/overview`, `pytorch-hccl-tests/bandwidth-runbook` | HCCL bandwidth benchmarking |
| `agent/*` | `agent/invariants`, `agent/distributed_work_policy`, `agent/routing` | Agent-facing rules and the task-routing index |
| `ascend/*` | `ascend/hardware`, `ascend/arch_families`, `ascend/memory_hierarchy`, `ascend/cann_mapping`, `ascend/hccl_runtime`, `ascend/platform_decisions`, `ascend/alignment_rules`, `ascend/hccl_container_checklist` | Ascend hardware/platform reference |
| `flows/*` | `flows/compile_to_device`, `flows/matmul_demo`, `flows/distributed_allreduce`, `flows/dependency_triangle`, `flows/performance` | End-to-end worked examples |
| `tools/*` | `tools/sim_docker_workflow`, `tools/clang_tidy_workflow`, `tools/gate_pr_workflow` | MCP-owned task workflows (sim-Docker loop, mandatory clang-tidy step, PR gate) |
| `debug/*` | `debug/codegen-inspection` | Pipeline-wide map of generated-code inspection: per-stage artifact → flag/API → output path → inspection tool/skill |
| `notes/*` | see notes topics below | Enriched notes (secondary tier) |

**Doc tiers** (returned by `read_doc`/`route_task`): `canonical` (sibling repo docs — authoritative) > `enriched` (`pypto-3.0-notes` — secondary, check `last_verified`) > `design` (`pypto_top_level_documents` — forward-looking proposals, non-canonical) > `mcp-owned` (`content/` — this server's own decision-tree docs) > `ephemeral` (`pr_plans/`, `pull_requests/` — living/scratch, refused by `read_doc`, use `program_status`/`collective_status` instead).

### Notes topics (`notes/{topic}`, resource or `read_doc`)

`abstractions_master`, `codegen_infrastructure`, `dependency_triangle`, `distributed_work_policy`, `host_collectives`, `kernel_orchestration`, `machine_hierarchy`, `moe`, `multi_level_runtime_ring`, `notes_simpler`, `pass_infrastructure`, `ptoas_abstractions`, `ptoisa_abstractions`, `pypto_abstractions`, `pypto_lib_attention`, `pypto_lib_building_blocks`, `pypto_lib_distributed_support`, `pypto_lib_models`, `pypto_lib_status`, `runtime_arch_index`, `runtime_async`, `runtime_design`, `serving_implementation_plan`, `sharded_tensor`, `simpler_abstractions`, `simpler_distributed_runtime_design`, `stack_availability`, `tensor_layout`, `tensor_valid_shape`, `tpush_tpop_isa_design`

## MCP prompts

| Prompt | Params | Use when |
|--------|--------|----------|
| `start_compiler_work` | `area` (= task_type, default `stack_overview`) | General compiler work — any new session should start here or with one of the below |
| `start_distributed_work` | `focus`: `collectives` / `host_collectives` / `codegen` / `runtime` / `inference` | Collectives, L3 runtime, distributed codegen, large-scale inference |
| `start_ascend_work` | `focus`: `arch` / `tuning` / `hccl` / `runtime` / `verify` | Ascend hardware architecture, performance tuning, HCCL |
| `start_npu_verify` | — | Developer-only: hand off to real-NPU container verification (agent must not run this itself — see the prompt body for the exact gate) |
| `finish_work` | — | Closing loop: verify_ladder → agent_verify_tasks → clang-tidy (if C++ changed) → generate_verify_handoff for the NPU-gated remainder |
| `debug_codegen_work` | `focus`: `passes` / `pto` / `kernel` / `orch` / `runtime` | Debug a compile/lowering/codegen bug by inspecting generated code at each pipeline stage (route → catalog → find artifacts → inspect → fix → verify) |

Each prompt returns a short markdown playbook naming the exact tool-call sequence for that kind of work.

## Task types (`route_task` / `bootstrap_session` / `list_task_types`)

| task_type | Covers |
|-----------|--------|
| `stack_overview` | Any new session — multi-repo roles and compilation pipeline |
| `ir_change` | New IR nodes, types, or structural changes |
| `pass_change` | Pass pipeline additions or modifications |
| `codegen_pto` | InCore codegen to `.pto` MLIR (AICore path) |
| `codegen_orch` | Orchestration codegen to simpler runtime C++ (AICPU path) |
| `debug_codegen` | Debug by inspecting generated code across the pipeline: pass dumps, `.pto` MLIR, ptoas dumps, kernel/orchestration C++, dfx artifacts |
| `distributed` | Distributed ops, collectives, multi-rank |
| `distributed_collectives` | Composite collectives, ring vs. mesh algorithms |
| `host_collectives_program` | Host builtin collectives program (barrier, broadcast, reduce_scatter, allgather) |
| `distributed_codegen` | Distributed codegen backend |
| `distributed_runtime` | `simpler` comm-domain, L3 worker, remote execution |
| `large_model_inference` | pypto-lib models, golden harness, inference paths |
| `pypto_lib_building_blocks` | What building blocks/ops/models exist in pypto-lib and their distributed support |
| `ptoas` | PTO assembler and optimizer (`.pto` → C++) |
| `pto_isa` | Virtual tile ISA headers and backends |
| `runtime` | `simpler` task runtime execution on Ascend |
| `pypto_lib` | Model zoo, kernels, golden validation harness |
| `performance` | Compile/runtime profiling for training/inference tuning |
| `ascend_arch` | Ascend chip architecture: AIC/AIV, memory hierarchy, A2A3 vs. A5 |
| `ascend_runtime` | HCCL, comm windows, CANN container verify, distributed execution |
| `npu_tuning` | Performance tuning: block_dim, swimlanes, PMU, arch-specific backend handlers |
| `npu_verify_handoff` | Developer NPU verification handoff — container checkout, HCCL STs, record SHA |
| `hccl_bandwidth` | PyTorch/HCCL collective + p2p bandwidth benchmarking via `pytorch-hccl-tests` |
| `dockerfile_sync` | Sync Dockerfile SHA pins to latest `origin/main` for the stack repos |

`route_task` returns **`agent_verify_tasks`** (safe for an agent to run, e.g. sim-Docker UTs) separately from **`developer_verify_tasks`** (NPU/hardware-gated — an agent must never run these; they're for the human developer, typically via `generate_verify_handoff`).

### Host collectives (plan 33)

| Agent | Task |
|-------|------|
| Sim UT gate | `pypto-docker:host_collectives_ut_sim` |
| NPU ST (developer) | `pypto:host_collectives_st_npu` |

Read `hw-native-sys://notes/host_collectives` before resuming fork work in this area, and `hw-native-sys://agent/distributed_work_policy` (sim known failures) before running distributed STs in sim.

## Configuration files

| File | Purpose | Curation |
|------|---------|----------|
| `config/repos.json` | Workspace root, repo paths, named tasks, `repository_meta` | Hand-maintained |
| `config/knowledge.json` | Task routes, resources, notes topics | Hand-maintained |
| `config/skills.json` | Repo → agent-skill directory map (inventory read live from each repo's SKILL.md frontmatter) | Hand-maintained |
| `config/entrypoints.json` | Per-repo code entrypoints, by area | Hand-maintained |
| `config/abstractions.json` | Hand-curated compiler/stack concept cards | Hand-maintained — **always wins** over generated cards on name collision |
| `config/ascend_abstractions.json` | Ascend hardware, arch, HCCL concept cards | Hand-maintained, merged into the same abstraction index as `abstractions.json` |
| `config/pto_isa_generated.json` | ~150 pto-isa instruction cards (tile-local + comm) | **Generated** by `tools/build_pto_isa_index.py` from `pto-isa/docs/isa/manifest.yaml` + `docs/isa/comm/README.md` |
| `config/ptoas_generated.json` | ~510 PTOAS IR op cards | **Generated** by `tools/build_ptoas_index.py`, regex-scraped from `PTOOps.td`/`VPTOOps.td`'s `let summary`/`let description` fields |
| `config/passes_index.json` | Default pipeline pass order, phase, verify tasks | **Generated** by `tools/build_knowledge_index.py` from `pypto/python/pypto/ir/pass_manager.py` — see caveat below |
| `config/program_status.json` | Structured PR status | **Generated** by `tools/sync_status_to_json.py` from `pypto-3.0-notes/pr_plans/status_prs.md` |
| `config/collective_status.json` | Structured collective-comm parity matrix | **Generated** by `tools/sync_collective_status_to_json.py` from `pypto-3.0-notes/distributed/current_status.md` |
| `config/simpler_scheduler.json` | L0–L6, the three engines, scheduler `.cpp`/`.h` trees, and completion schedulers | **Generated** by `tools/build_simpler_scheduler_index.py` from `simpler/src` (`.venv` is skipped) |
| `config/pypto_lib_workloads.json` | Model workloads and prefill/decode kernel names | **Generated** by `tools/build_pypto_lib_workloads.py` from `pypto-lib/docs/models/index.md` and `models/` |
| `content/ascend/*.md` | MCP-owned decision trees (platform, alignment, HCCL) | Hand-maintained |

All generated files are checked into git (so a fresh checkout works without a build step) but are meant to be periodically regenerated — see below. None of the generator scripts ever write to the sibling repos or to `pypto-3.0-notes`; they only read from them.

### Provenance: curated vs. generated abstraction cards

`load_abstractions()` merges, in order: `pto_isa_generated.json`, `ptoas_generated.json`, the `cards` objects inside `simpler_scheduler.json` and `pypto_lib_workloads.json`, then `abstractions.json` and `ascend_abstractions.json`. **Any hand-curated card always wins outright** on an exact name collision. `explain_abstraction` reports which one you got via its `source` field (`curated` or `generated`). Generated instruction and op cards additionally carry `generated_from` (the exact source file scraped).

Why this split exists: pto-isa and PTOAS have far more instructions/ops (about 150 and 510) than the hand-curated cards (about 80 combined). Rather than leave the long tail undocumented, the generators mechanically extract what pto-isa/PTOAS already document about themselves (structured `manifest.yaml` entries, TableGen `let summary` fields) — lower-quality than hand curation, but far better than nothing, and it never silently overrides a hand-written card.

### Maintaining the knowledge config

Run these after upstream changes to the scraped sources (pass pipeline, pto-isa manifest, PTOAS `.td` files, PR/plan status, or the collective status matrix). For a full refresh in one command:

```bash
# Regenerate every generated index, re-stamp config/.index_build_time, then audit
./tools/refresh_all.sh
```

Or run the steps individually when only one source changed:

```bash
# Verify every path referenced by knowledge.json/abstractions/entrypoints actually exists
python tools/verify_knowledge_config.py

# Rebuild passes_index.json (from pypto's pass_manager.py) + suggest new abstraction
# candidates (printed to stdout only -- never auto-merged into abstractions.json)
python tools/build_knowledge_index.py

# Rebuild pto_isa_generated.json from pto-isa/docs/isa/manifest.yaml + comm/README.md
python tools/build_pto_isa_index.py

# Rebuild ptoas_generated.json from PTOAS's PTOOps.td / VPTOOps.td
python tools/build_ptoas_index.py

# Sync status_prs.md -> program_status.json for agents
python tools/sync_status_to_json.py

# Sync current_status.md's parity matrix -> collective_status.json
python tools/sync_collective_status_to_json.py

# Rebuild simpler_scheduler.json from scheduler directories plus the L0-L6 table
python tools/build_simpler_scheduler_index.py

# Rebuild pypto_lib_workloads.json from the model index and models/ directories
python tools/build_pypto_lib_workloads.py
```

**Caveat on `build_knowledge_index.py`**: it only rebuilds `passes_index.json` when re-run explicitly — `load_passes_index()` does not invalidate the on-disk cache on its own (unlike `load_abstractions()`, which is mtime-keyed). The scraper matches `passes.<name>` factory references inside `pass_manager.py`'s `_get_pass_factories` body (the old `("Name", lambda: passes.foo())` PassSpec tuples are gone — the pipeline now runs through a C++ `PassPipeline` but the recipe is still a Python tuple list of factories). If a rebuild returns `pypto_pass_count` as `0` with a warning, upstream moved away from that shape again — inspect the recipe before assuming the scraper is simply stale. **Don't blindly overwrite a healthy checked-in cache with a broken re-scrape** — diff it first; if the rebuild produces materially less data than what's committed, something upstream changed and needs a matching fix in `passes_index.py`, not a cache overwrite.

### Pre-commit gate

`tools/hooks/pre-commit` runs ruff + `tools/verify_knowledge_config.py` + the
test suite before every commit, so config drift (stale refs, missing skill
paths, broken routes) never lands. Install once per clone:

```bash
git config core.hooksPath tools/hooks
```

### CI and knowledge freshness

`.github/workflows/ci.yml` runs the lint gate (ruff, pinned to `0.14.8` with an
explicit rule set in `pyproject.toml`) and the **sandboxed** test subset
(`pytest -m "not workspace"`) on every push/PR — it needs only this repo. The
sibling repos (pypto, pypto-3.0-notes, …) are private and cannot be cloned
anonymously, so the workspace-dependent pieces run **locally** instead:

- the full test suite incl. the `@pytest.mark.workspace` smoke tests
  (`pytest tests/` from the workspace),
- the knowledge-config audit (`tools/verify_knowledge_config.py`),
- the freshness drift guard `tools/check_fresh.sh` — regenerate every
  generated cache and fail when the checked-in indexes have drifted from the
  upstream sources (ignores the re-stamped `config/.index_build_time`):

```bash
bash tools/check_fresh.sh
```

The pre-commit hook above runs all three on every local commit, so CI and
local together cover the full gate.

### Self-auditing: `knowledge_health`

Call `knowledge_health` any time you want a health check on the knowledge layer itself, without a manual audit:

- `missing_paths` — any route/resource/abstraction path that no longer exists on disk.
- `stale_enriched` — enriched docs whose `last_verified` (from `pypto-3.0-notes/NOTES_FRESHNESS.md`) is more than 30 days old.
- `coverage.pto_isa_indexed` / `coverage.ptoas_indexed` — how many generated cards currently exist, so index drift (e.g. after a pto-isa/PTOAS refactor) is visible without re-running the multi-agent audit that originally found this gap.
- `pypto_pass_count` / `pypto_passes_index_warning` — whether the pass-pipeline scrape is currently healthy (see caveat above). Explicitly scoped to pypto — no other repo's pass pipeline is scraped, so don't read this as a cross-repo figure.
- `scheduler_implementation_count` / `workload_count` / `catalog_issues` — whether the simpler scheduler index and the pypto-lib workload catalog exist and are non-empty.
- `ascend_issues`, `last_index_build`, `ascend_route_count` — misc corpus checks.

## Task profile (operations)

Balanced profile: fast daily tasks (git, lint) plus heavier tasks (docker, profiling, hardware tests). Warnings are surfaced by `list_tasks`, `explain_task`, and `run_task`. Destructive patterns (`git reset --hard`, `git clean -fdx`, `rm -rf /`, `rm -rf ~`) are blocked at the `run_command`/`run_task` layer regardless of which repo task config requests them.

## Walkthroughs

**Developer, lowering bug.** Call `layer_guide("ptoas")` for that layer's docs, skills, and rules. Then `explain_abstraction("tmov", layer="ptoas")` and `explain_abstraction("TMOV", layer="pto-isa")` so the assembler op and the ISA instruction stay separate. If the failure is in the runtime, call `explain_scheduler("L3")` or `explain_scheduler("hierarchical")`. Then `search_tracker("tmov", repo="PTOAS", state="merged")` and the same query with `state="open"`.

**User, a model.** Call `list_workloads("deepseek_v4_1_flash")` for the summary, serving support, and prefill/decode filenames. Then `layer_guide("pypto-lib")` for that layer's docs and rules. Read a page with `read_doc`.

**NPU queue.** Call `explain_task_queue` before any hardware handoff. Queue hosts are `192.168.150.11` and `.12`. Host `.13` and sim images are not queued. The handoff from `generate_verify_handoff` wraps developer commands as `task-submit --device auto --device-num N --max-time 3600 --timeout 0 --run '… $TASK_DEVICE'`. Put `LD_PRELOAD` inside `--run`. The full recipe is `pypto-docker/TASK_QUEUE.md`. The agent does not submit the job.

## Example agent prompts

- "Invoke `start_compiler_work` with area=`codegen_orch` and follow the bootstrap."
- "`route_task` for `host_collectives_program` — sim Docker UT vs NPU ST split."
- "`explain_abstraction` for `host_collectives_program`."
- "`explain_abstraction` for `BackendHandler910B` — when is GM pipe buffer required?"
- "`explain_abstraction` for `TSCATTER` — note it covers both the local-tile and collective-comm meaning, merged from two sources."
- "`route_task` `ascend_runtime` — HCCL windows and container flags."
- "`ascend_env_check` then `generate_verify_handoff` for branch feat/foo."
- "`search_abstractions` hccl window."
- "`explain_abstraction` for `IterArgCarryAnalyzer`."
- "`trace_in_stack` for `pypto/src/codegen/pto/pto_codegen.cpp`."
- "`search_abstractions` for allreduce."
- "`collective_status` with axis=`Dynamic NR` — what's the parity gap across ops?"
- "`knowledge_health` — any stale or missing docs, or coverage gaps?"
- "`route_task` `debug_codegen` — how do I inspect pass dumps / .pto / kernel C++ for this lowering bug?"
- "`read_doc` `content/debug/codegen-inspection.md` then `find_generated_artifacts` for program `qwen_decode`."
- "`find_skill` — which workflow diffs generated code between branches?"
- "`layer_guide` ptoas — which rules and skills apply before I edit an op?"
- "`explain_scheduler` hierarchical — which queue does a SUB task use?"
- "`list_workloads` deepseek_v4_1_flash — which files are prefill?"
- "`search_tracker` TMOV state=merged repo=PTOAS,pto-isa — was this already fixed?"
- "`explain_task_queue` — does this host require task-submit?"

## Prerequisite notes

- Simulator/CPU tests: Python deps and build toolchain.
- Hardware tasks: Ascend runtime/device environment.
- Docker tasks: daemon available; can be heavy on disk/network.
- Profiling: start with `profiling_smoke` before `profiling_full`.

## Extending this server

Every tool follows the same shape: a plain, unit-testable `_impl(...)` function (in `mcp_hwnative_sys/<module>.py`) plus a thin `@mcp.tool()`-decorated wrapper that calls it.

1. Put the real logic in a module-level `def foo_impl(...) -> dict[str, Any]` — no MCP/pydantic types inside, so it can be imported and called directly from tests.
2. Register it in `register_knowledge(mcp)` (in `knowledge.py`) or directly in `server.py`, using `Annotated[T, Field(description=...)]` for every parameter — the description is what the calling agent sees, so make it concrete (include example values). Prefer a **local import inside the tool function body** for the impl module (e.g. `from mcp_hwnative_sys.foo import foo_impl`) to avoid import cycles, matching the existing convention for `explain_pass`, `trace_contract`, `verify_ladder`, `collective_status`, etc.
3. Raise plain `ValueError`/`RuntimeError`/`FileNotFoundError` for user-facing errors — there's no custom exception hierarchy.
4. Add a test in `tests/test_<module>.py`: plain `pytest` functions (no classes), `from __future__ import annotations`, `monkeypatch.setattr(<module>, "workspace_root", lambda: tmp_path)` (or the relevant path function) to sandbox filesystem-touching code, plus one smoke test against the real workspace. If the tool lives in `tools/` (a maintenance script, not part of the installed package), import it in tests via a `sys.path.insert(0, str(TOOLS_DIR))` at the top of the test file, matching `test_build_pto_isa_index.py`/`test_build_ptoas_index.py`.
5. Run `pytest tests/` from `mcp-hw-native-sys/` (use the project's own `.venv`: `.venv/bin/python -m pytest tests/`).
6. If your tool scrapes a source that could drift (like the pto-isa/PTOAS generators or the pass-pipeline scraper), prefer writing to a **new** generated JSON file that gets layered in at load time, rather than writing into a hand-curated config — that way hand edits are never at risk of being silently overwritten by a bad scrape, and regenerating is always safe to re-run.

## Known caveats

- `passes_index.py` recovers pass names by regex-scraping `passes.<name>` factory references inside `pypto/python/pypto/ir/pass_manager.py`'s `_get_pass_factories` body, deduplicated in source order. It is current as of the September 2026 recipe shape; if pypto changes the recipe syntax again (or moves pass description out of Python entirely), the scraper must be updated in the same change — `knowledge_health`'s `pypto_passes_index_warning` is the tripwire, and `tools/refresh_all.sh` regenerates the checked-in cache after any pass-pipeline change.
- Some `notes/*` topics are defined both in `resources` and `notes_topics`; `register_knowledge` deduplicates them at registration time (the `resources` entry, with its per-topic `max_chars`, wins).
