# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Shared paths and YAML config loading with ``extends`` overlays."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from dgx_lab import DATA_ROOT_ENV, DEFAULT_DATA_ROOT_NAME

DATA_SUBDIRS = ("models", "datasets", "adapters", "evals", "records", "logs")


def data_root() -> Path:
    """Return the lab data root (``$DGX_LAB_ROOT`` or ``~/dgx-lab``)."""
    override = os.environ.get(DATA_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / DEFAULT_DATA_ROOT_NAME).resolve()


def ensure_data_layout(root: Path | None = None) -> Path:
    """Create ``~/dgx-lab/{models,datasets,adapters,evals,records,logs}``."""
    root = root or data_root()
    root.mkdir(parents=True, exist_ok=True)
    for name in DATA_SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay onto base (overlay wins). Lists are replaced."""
    out: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if key == "extends":
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)  # type: ignore[arg-type]
        else:
            out[key] = value
    return out


def load_config(path: Path, *, _stack: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Load YAML config resolving relative ``extends`` chains."""
    path = path.resolve()
    if path in _stack:
        chain = " -> ".join(str(p) for p in (*_stack, path))
        raise ValueError(f"Circular extends: {chain}")
    raw = load_yaml(path)
    extends = raw.get("extends")
    merged: dict[str, Any] = {}
    if extends:
        if isinstance(extends, str):
            extends = [extends]
        if not isinstance(extends, list):
            raise ValueError(f"'extends' must be str or list in {path}")
        for rel in extends:
            parent = (path.parent / rel).resolve()
            merged = deep_merge(merged, load_config(parent, _stack=(*_stack, path)))
    return deep_merge(merged, raw)
