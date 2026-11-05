"""Tests for mcp_hwnative_sys.profiling_summarize (summarize_profile_impl)."""

from __future__ import annotations

import json

import pytest

from mcp_hwnative_sys.profiling_summarize import summarize_profile_impl


def _write_results(run_dir, runs, header=None):
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {**(header or {}), "runs": runs}
    (run_dir / "results.json").write_text(json.dumps(payload), encoding="utf-8")


class TestSummarizeProfile:
    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Run directory not found"):
            summarize_profile_impl(str(tmp_path / "does-not-exist"))

    def test_dir_without_results_json_has_no_stacks(self, tmp_path):
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        result = summarize_profile_impl(str(run_dir))
        assert "stacks" not in result
        assert result["anomalies"] == []
        assert result["trace_files_found"] == 0

    def test_groups_runs_by_stack(self, tmp_path):
        run_dir = tmp_path / "run1"
        _write_results(
            run_dir,
            [
                {"stack": "pypto", "case_id": "a", "execute_s_mean": 1.0, "correctness": "pass"},
                {"stack": "pypto", "case_id": "b", "execute_s_mean": 2.0, "correctness": "pass"},
                {"stack": "hccl", "case_id": "c", "execute_s_mean": 0.5, "correctness": "pass"},
            ],
        )
        result = summarize_profile_impl(str(run_dir))
        assert result["run_count"] == 3
        by_stack = {s["stack"]: s for s in result["stacks"]}
        assert by_stack["pypto"]["cases"] == 2
        assert by_stack["pypto"]["mean_execute_s"] == pytest.approx(1.5)
        assert by_stack["hccl"]["cases"] == 1

    def test_correctness_failures_reported_as_anomalies(self, tmp_path):
        run_dir = tmp_path / "run1"
        _write_results(
            run_dir,
            [
                {"stack": "pypto", "case_id": "a", "execute_s_mean": 1.0, "correctness": "fail"},
                {"stack": "pypto", "case_id": "b", "execute_s_mean": 1.0, "correctness": "pass"},
            ],
        )
        result = summarize_profile_impl(str(run_dir))
        assert any("correctness failure" in a for a in result["anomalies"])
        stack = next(s for s in result["stacks"] if s["stack"] == "pypto")
        assert stack["failures"] == 1

    def test_zero_bandwidth_reported_as_anomaly(self, tmp_path):
        run_dir = tmp_path / "run1"
        _write_results(
            run_dir,
            [{"stack": "pypto", "case_id": "a", "execute_s_mean": 1.0, "bandwidth_gbps": 0.0}],
        )
        result = summarize_profile_impl(str(run_dir))
        assert any("zero bandwidth" in a for a in result["anomalies"])

    def test_slowest_cases_sorted_descending(self, tmp_path):
        run_dir = tmp_path / "run1"
        _write_results(
            run_dir,
            [
                {"stack": "pypto", "case_id": "slow", "execute_s_mean": 9.0},
                {"stack": "pypto", "case_id": "fast", "execute_s_mean": 0.1},
            ],
        )
        result = summarize_profile_impl(str(run_dir))
        assert result["slowest_cases"][0]["case_id"] == "slow"

    def test_falls_back_to_wall_time_when_execute_missing(self, tmp_path):
        run_dir = tmp_path / "run1"
        _write_results(run_dir, [{"stack": "pypto", "case_id": "a", "wall_s_mean": 3.0}])
        result = summarize_profile_impl(str(run_dir))
        assert result["slowest_cases"][0]["execute_s"] == 3.0

    def test_trace_files_detected(self, tmp_path):
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        (run_dir / "trace.json").write_text("{}", encoding="utf-8")
        result = summarize_profile_impl(str(run_dir))
        assert result["trace_files_found"] == 1
        assert "note" in result
