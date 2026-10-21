# PR test standards

*MCP-owned — summarizes upstream rules; the sibling repos stay authoritative
(`pypto/.claude/rules/testing-and-examples.md`, `pypto/.claude/skills/testing`,
`pypto-lib/.claude/CLAUDE.md`). Verified against pypto and pypto-lib only;
simpler, PTOAS and pto-isa are not covered here yet.*

## What a PR must contain

| Change | Required test |
| ------ | ------------- |
| New feature / public API | Tests that exercise it, plus edge cases |
| Bug fix | A regression test that fails without the fix |
| Cross-layer change (C++ ↔ Python) | Test covering both sides |
| Docs-only | None (CI skips build and tests) |

`verify_ladder` returns `test_presence.warnings` when pypto, simpler, PTOAS
or pto-isa production files change without any test file in the diff.
It cannot tell a bug fix from a feature: treat the warning as "state your
test strategy", not as a hard failure.

## pypto conventions

- pytest only: plain `assert`, fixtures, `pytest.raises`. No `unittest`, no
  `print` as a check.
- Tests live under `tests/` only (`tests/ut/...`, `tests/st/...`). No scratch
  scripts or examples at the repo root. Prefer extending an existing test file.
- Every test file ends with `if __name__ == "__main__": pytest.main([__file__, "-v"])`.
- IR/pass tests use `@pl.program` `Before` / `Expected` classes and
  `ir.assert_structural_equal(After, Expected)`.
- `tests/st/**` and `examples/**` use the `@pl.jit` family; `@pl.program` is
  for `tests/ut/` only. New files must follow this.
- Verify a new `@pl.jit` kernel with a full `compile()`, never `lower()` alone.
- Never hack a test to pass; fix the cause.

## pypto-lib conventions

- `tests/` tests the golden harness and serving contracts. Model/kernel work
  must leave them unchanged unless the task needs a harness or contract change,
  so no test-presence warning is raised for this repo.
- Run `python -m pytest tests/golden -v`, `tests/lint/check_headers.py` and
  `tests/lint/check_english_only.py`.

## Local gate before a PR

1. `pre-commit run --all-files`. In pypto this includes custom lints (emitter
   `CHECK` classification, op-name literals, docs EN/ZH parity and nav, English
   only) as well as ruff, pyright, clang-format, cpplint, markdownlint.
2. Machine limits for local builds: `source .claude/skills/testing/load-env.sh`
   (`PYPTO_BUILD_JOBS`, `PYPTO_TEST_JOBS`); unit tests run with `-n`.
3. Tests from `verify_ladder` (`suggested_tasks`), run via
   [`gate_pr_workflow`](gate_pr_workflow.md) in the [sim Docker](sim_docker_workflow.md).
4. clang-tidy on changed C++ ([`clang_tidy_workflow`](clang_tidy_workflow.md)).
5. NPU verification is a developer gate, not an agent step.

## Test images (pypto-docker)

Run PR tests in the NPU-free sim images built from `pypto-docker`
(`scripts/build-sim-images.sh [pypto|simpler|all]`), not on the host:

| Image | Dockerfile | Use for |
| ----- | ---------- | ------- |
| `pypto3-hw-native-sys:sim` | `Dockerfile.hw-native-sys.sim.ubuntu22.04` | pypto `tests/ut` (`-n auto --maxprocesses 8`), `tests/st/codegen --codegen-only`, `tests/st/runtime/...` with `--forked --platform=a2a3sim` / `a5sim` |
| `simpler-hw-native-sys:sim` | `Dockerfile.simpler.sim.ubuntu22.04` | simpler L3 worker/collective STs on `a2a3sim` (`scripts/run-simpler-l3-sim.sh`, mirrors CI `st-sim-a2a3`) |
| pypto-lib sim | `Dockerfile.pypto-lib.sim.ubuntu22.04` (layers on the pypto sim image) | pypto-lib `tests/golden` and example/model sim smoke tests |
| `pypto3-hw-native-sys:cann9` and other `*.cann9.0` | `Dockerfile.*.cann9.0` | Real-NPU runs (developer gate only) |

Mount the checkout over the baked one (see [sim Docker](sim_docker_workflow.md)).
`Dockerfile.pto-kernels.cann9.0` is for pto-kernels, which needs the CANN CA-model
simulator or a real NPU; plain pytest has no device.

## What CI runs (pypto)

A `changes` job filters by path. Jobs: pre-commit, clang-tidy, unit-tests,
docs-examples, examples-tests, codegen-tests, system-tests (sim and device),
dist-system-tests, pypto-lib-compile/model, serving-guard, a5 onboard/sim.
Passing the local gate does not replace these.
