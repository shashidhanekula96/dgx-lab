# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for KPI gates."""

from __future__ import annotations

from pathlib import Path

import yaml

from dgx_lab.kpis import evaluate_kpis, load_kpi_config


def test_evaluate_kpis_pass_fail():
    cfg = {
        "gates": {
            "success_rate": {"min": 0.8},
            "mean_latency_ms": {"max": 1000},
            "tokens_per_second": {"min": 5},
            "format_validity_rate": {"min": 0.8},
        }
    }
    good = evaluate_kpis(
        {
            "success_rate": 1.0,
            "mean_latency_ms": 100,
            "tokens_per_second": 20,
            "format_validity_rate": 1.0,
        },
        cfg,
    )
    assert good.ok
    bad = evaluate_kpis(
        {
            "success_rate": 0.5,
            "mean_latency_ms": 100,
            "tokens_per_second": 20,
            "format_validity_rate": 1.0,
        },
        cfg,
    )
    assert not bad.ok
    assert any(g.name == "success_rate" and not g.ok for g in bad.gates)


def test_load_kpi_config_repo_default():
    root = Path(__file__).resolve().parents[1]
    cfg = load_kpi_config(root / "configs" / "kpis" / "default.yaml")
    assert "gates" in cfg
    assert "success_rate" in cfg["gates"]


def test_custom_gate(tmp_path: Path):
    path = tmp_path / "k.yaml"
    path.write_text(yaml.safe_dump({"gates": {"custom_score": {"min": 0.9}}}), encoding="utf-8")
    cfg = load_kpi_config(path)
    report = evaluate_kpis({"custom_score": 0.95}, cfg)
    assert report.ok
