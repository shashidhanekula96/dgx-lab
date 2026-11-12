# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for experiment tracking registry."""

from __future__ import annotations

from pathlib import Path

import yaml

from dgx_lab.tracking import compare_runs, create_run, list_runs, load_run, update_run_status


def _write_exp(tmp_path: Path, name: str = "exp", **extra) -> Path:
    path = tmp_path / f"{name}.yaml"
    data = {"name": name, "serve": {"model_name": "qwen3-8b"}, **extra}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_create_and_load_run(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DGX_LAB_ROOT", str(tmp_path))
    monkeypatch.setenv("DGX_LAB_OPERATOR", "tester")
    cfg = _write_exp(tmp_path, latency_budget_ms=1000)
    run_id, dest = create_run(cfg)
    assert dest.exists()
    assert (dest / "config.frozen.yaml").exists()
    loaded = load_run(run_id)
    assert loaded["meta"]["run_id"] == run_id
    assert loaded["config"]["name"] == "exp"
    assert loaded["config"]["latency_budget_ms"] == 1000
    assert loaded["meta"]["operator"] == "tester"
    assert "host" in loaded["meta"]
    assert "arch" in loaded["meta"]["host"]
    assert "memory_bytes" in loaded["meta"]["host"]
    # No secrets leaked into meta
    blob = (dest / "meta.json").read_text(encoding="utf-8").lower()
    assert "api_token" not in blob
    assert "bearer" not in blob


def test_rerun_compare(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DGX_LAB_ROOT", str(tmp_path))
    a = _write_exp(tmp_path, "a", value=1)
    b = _write_exp(tmp_path, "b", value=2)
    id_a, _ = create_run(a)
    id_b, dest_b = create_run(b)
    update_run_status(id_b, "passed", metrics={"success_rate": 1.0})
    assert (dest_b / "metrics.json").exists()
    diff = compare_runs(id_a, id_b)
    assert "value" in diff["config_diff"]
    assert diff["right_metrics"]["success_rate"] == 1.0
    runs = list_runs()
    assert {r["run_id"] for r in runs} >= {id_a, id_b}
