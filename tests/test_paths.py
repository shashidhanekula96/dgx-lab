# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for paths / YAML extends."""

from __future__ import annotations

from pathlib import Path

import yaml

from dgx_lab.paths import deep_merge, ensure_data_layout, load_config


def test_deep_merge_overlay_wins():
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "list": [1]}
    over = {"nested": {"y": 9, "z": 3}, "list": [2, 3], "b": 2}
    merged = deep_merge(base, over)
    assert merged == {"a": 1, "nested": {"x": 1, "y": 9, "z": 3}, "list": [2, 3], "b": 2}


def test_load_config_extends(tmp_path: Path):
    base = tmp_path / "base.yaml"
    child = tmp_path / "child.yaml"
    base.write_text(yaml.safe_dump({"name": "base", "serve": {"port": 8000}, "a": 1}), encoding="utf-8")
    child.write_text(
        yaml.safe_dump({"extends": "base.yaml", "name": "child", "serve": {"model": "x"}, "b": 2}),
        encoding="utf-8",
    )
    cfg = load_config(child)
    assert cfg["name"] == "child"
    assert cfg["a"] == 1
    assert cfg["b"] == 2
    assert cfg["serve"]["port"] == 8000
    assert cfg["serve"]["model"] == "x"
    assert "extends" not in cfg


def test_circular_extends(tmp_path: Path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text("extends: b.yaml\nx: 1\n", encoding="utf-8")
    b.write_text("extends: a.yaml\ny: 2\n", encoding="utf-8")
    try:
        load_config(a)
        assert False, "expected circular extends error"
    except ValueError as exc:
        assert "Circular" in str(exc)


def test_ensure_data_layout(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DGX_LAB_ROOT", str(tmp_path / "lab"))
    root = ensure_data_layout()
    for name in ("models", "datasets", "adapters", "evals", "records", "logs"):
        assert (root / name).is_dir()
