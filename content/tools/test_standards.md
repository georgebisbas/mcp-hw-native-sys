# PR test standards

*MCP-owned — summarizes upstream rules; the sibling repos stay authoritative
(`pypto/.claude/rules/testing-and-examples.md`, `pypto/.claude/skills/testing`,
`pypto-lib/.claude/CLAUDE.md`, `simpler/docs/testing.md`,
`PTOAS/.claude/skills/ptoas-test-framework-guidance`, `pto-isa/tests/README.md`).
Verified against shallow upstream clones of pypto, pypto-lib, simpler, PTOAS and
pto-isa (2026-10-21).*

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

## simpler conventions

- Three test types: Python UT (`tests/ut`, `pytest`), C++ UT (`tests/ut/cpp`,
  GoogleTest via `ctest -LE requires_hardware`), and scene tests (`@scene_test`
  classes in `examples/**` and `tests/st/**`, run by `pytest examples tests/st`).
- Hardware classification: sim (`a2a3sim`, `a5sim`, or no `--platform`) needs no
  device; `requires_hardware[("a2a3")]` marks tests needing a device.
- Assert properties, not wall-clock: off-hardware tests must not use timing as a
  proxy for concurrency or speed (issue #1496). Timing is fine only when it is the subject.
- Reproducible defects need a test that fails first (`.claude/rules/discipline.md`).
- Runtime C++ or bindings changes need `pip install --no-build-isolation -e .`
  before testing; Python-only changes do not.
- Mirror CI shape, not a flat sweep: a2a3 uses `-m "not sdma and not sdma_fault" --exclude-level 4`
  with SDMA and fault-injection run in their own steps. A failure in a sweep that passes alone
  is an isolation issue, not a regression.
- Pre-commit adds `check-test-platform-literals`, `check-ut-cpp-case-naming`,
  clang-tidy, cpplint, ruff, pyright. Use a project-local `--system-site-packages` venv.
- CI jobs: ut, st-sim-a2a3, st-sim-a5, profiling-flags-smoke, ut/st-onboard (a2a3, a5),
  all gated by `_detect-changes.yml`.

## PTOAS conventions

- Prefer small regression tests over ad-hoc scripts; keep them under `test/`.
- Pick the framework by what is validated: `test/lit` (parser, verifier, pass output,
  `FileCheck`; every `.pto` needs a `// RUN:` line, `not ptoas ... | FileCheck` for
  negative cases), `test/lit/vpto` for `--pto-backend=vpto`, `test/dsl-st` for PTODSL
  semantic cases on the simulator, `test/vpto` for generated-kernel runtime checks,
  `test/tilelang_st` for TileLang DSL.
- Never add `.pto` under `test/basic` (lit does not discover it), and never put
  runtime or simulator expectations in lit tests.
- Pass bugs: Before / Expected / Actual with the exact `ptoas` invocation.
- Run: `ninja -C build check-pto` or `lit -v build/test/lit --filter '<case>'`;
  `ctest -L PTODSL`.
- CI `build-and-test` also runs a license-header check and a VMI source-patch check.

## pto-isa conventions

- CPU simulator is the PR-level gate: `python3 tests/run_cpu.py --testcase <op> --gtest_filter '<Suite.case>'`,
  `tests/run_cpu_tests.sh`, and `python3 tests/run_cpu.py --clean --verbose` for the full run.
- NPU STs: `python3 tests/script/run_st.py -r sim|npu -v a3|a5 -t <case>`, or
  `tests/run_st.sh --a3 --sim --all`. All suites use GoogleTest.
- A new operator ships ST testcases under `tests/<arch>/.../st/testcase/` with
  `main.cpp`, `gen_data.py` and a `CMakeLists.txt` (CONTRIBUTING.md); non-bug-fix
  changes start from an Issue.
- Validators: `tests/validate_op_coverage.py`, `tests/validate_testcase_names.py`.
- CI: pre-commit, docs-build, unit-tests (CPU SIM smoke and trace regressions),
  system-tests (`run_cpu_tests.sh`), plus a5-smoke.

`verify_ladder` suggests: PTOAS changes → `ir_smoke`, `lit_tests` (`ninja -C build check-pto`;
`ptodsl/` adds `ptodsl_ctest`); pto-isa include/kernel changes → `validate_op_coverage`,
`cpu_st_tests`; pto-isa `tests/` changes → `validate_testcase_names`, `cpu_st_tests`.
Docs-only changes in either repo suggest nothing. `lit_tests` needs a configured `./build`.

## Local gate before a PR

1. `pre-commit run --all-files`. In pypto this includes custom lints (emitter
   `CHECK` classification, op-name literals, docs EN/ZH parity and nav, English
   only) as well as ruff, pyright, clang-format, cpplint, markdownlint.
2. (pypto) Machine limits for local builds: `source .claude/skills/testing/load-env.sh`
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
