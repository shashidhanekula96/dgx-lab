# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""KPI gate evaluation for baselines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dgx_lab.paths import load_config


@dataclass
class GateResult:
    name: str
    ok: bool
    actual: float | int | bool | None
    threshold: float | int | bool | None
    comparator: str
    detail: str


@dataclass
class KpiReport:
    gates: list[GateResult]

    @property
    def ok(self) -> bool:
        return all(g.ok for g in self.gates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "gates": [
                {
                    "name": g.name,
                    "ok": g.ok,
                    "actual": g.actual,
                    "threshold": g.threshold,
                    "comparator": g.comparator,
                    "detail": g.detail,
                }
                for g in self.gates
            ],
        }


def load_kpi_config(path: Path) -> dict[str, Any]:
    return load_config(path)


def _cmp(actual: float, threshold: float, op: str) -> bool:
    if op == ">=":
        return actual >= threshold
    if op == "<=":
        return actual <= threshold
    if op == ">":
        return actual > threshold
    if op == "<":
        return actual < threshold
    if op == "==":
        return actual == threshold
    raise ValueError(f"Unsupported comparator: {op}")


def evaluate_kpis(metrics: dict[str, Any], kpi_config: dict[str, Any]) -> KpiReport:
    """
    Apply gates from KPI YAML.

    Expected shape::

        gates:
          success_rate: {min: 0.8}
          mean_latency_ms: {max: 5000}
          tokens_per_second: {min: 5}
          format_validity_rate: {min: 0.8}
    """
    gates_cfg = kpi_config.get("gates") or {}
    results: list[GateResult] = []

    mapping = {
        "success_rate": ("min", ">="),
        "format_validity_rate": ("min", ">="),
        "tokens_per_second": ("min", ">="),
        "mean_latency_ms": ("max", "<="),
        "p95_latency_ms": ("max", "<="),
    }

    for name, (bound_key, op) in mapping.items():
        if name not in gates_cfg:
            continue
        spec = gates_cfg[name] or {}
        if bound_key not in spec:
            continue
        threshold = float(spec[bound_key])
        if name not in metrics:
            results.append(
                GateResult(
                    name=name,
                    ok=False,
                    actual=None,
                    threshold=threshold,
                    comparator=op,
                    detail=f"metric {name!r} missing",
                )
            )
            continue
        actual = float(metrics[name])
        ok = _cmp(actual, threshold, op)
        results.append(
            GateResult(
                name=name,
                ok=ok,
                actual=actual,
                threshold=threshold,
                comparator=op,
                detail=f"{actual} {op} {threshold}",
            )
        )

    # Generic passthrough for custom numeric gates: {metric: {min|max: x}}
    for name, spec in gates_cfg.items():
        if name in mapping or not isinstance(spec, dict):
            continue
        if "min" in spec:
            threshold = float(spec["min"])
            op = ">="
        elif "max" in spec:
            threshold = float(spec["max"])
            op = "<="
        else:
            continue
        actual_v = metrics.get(name)
        if actual_v is None:
            results.append(
                GateResult(name, False, None, threshold, op, f"metric {name!r} missing")
            )
            continue
        actual = float(actual_v)
        results.append(
            GateResult(name, _cmp(actual, threshold, op), actual, threshold, op, f"{actual} {op} {threshold}")
        )

    return KpiReport(gates=results)
