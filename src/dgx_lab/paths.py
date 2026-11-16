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


# ---------------------------------------------------------------------------
# Bundled defaults
#
# The wheel ships copies of the repo's default golden set, KPI gates and a
# starter experiment under ``dgx_lab/_data`` (see ``[tool.hatch...force-include]``
# in pyproject.toml). In a source checkout / editable install those copies do
# not exist, so we fall back to the files in the repository itself.
# ---------------------------------------------------------------------------

_BUNDLED = {
    "golden": ("smoke.jsonl", ("evals", "golden", "smoke.jsonl")),
    "kpis": ("kpis-default.yaml", ("configs", "kpis", "default.yaml")),
    "experiment": ("experiment-example.yaml", ("configs", "experiments", "local-example.yaml")),
}


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def bundled_default(kind: str) -> Path:
    """Return the path of a bundled default file (``golden``, ``kpis``, ``experiment``)."""
    if kind not in _BUNDLED:
        raise KeyError(f"unknown bundled default: {kind}")
    packaged_name, repo_parts = _BUNDLED[kind]
    packaged = _package_dir() / "_data" / packaged_name
    if packaged.is_file():
        return packaged
    repo_file = _package_dir().parents[1].joinpath(*repo_parts)
    if repo_file.is_file():
        return repo_file
    raise FileNotFoundError(
        f"Bundled default {kind!r} not found (looked in {packaged} and {repo_file}). "
        "Reinstall dgx-lab or pass the file path explicitly."
    )


def resolve_resource(value: str | Path, *, relative_to: Path | None = None) -> Path:
    """
    Resolve a file path referenced from an experiment config.

    Search order for relative paths:
    1. current working directory
    2. the config file's directory and each of its parents (so
       ``evals/golden/smoke.jsonl`` works from ``configs/experiments/x.yaml``)
    3. bundled defaults with the same file name (installed-package users)
    """
    path = Path(value).expanduser()
    if path.is_absolute():
        if path.is_file():
            return path
        raise FileNotFoundError(f"File not found: {path}")

    candidates = [Path.cwd() / path]
    if relative_to is not None:
        base = relative_to.resolve()
        base = base if base.is_dir() else base.parent
        candidates += [d / path for d in (base, *base.parents)]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    for kind, (_, repo_parts) in _BUNDLED.items():
        if path.as_posix() == "/".join(repo_parts) or path.name == repo_parts[-1]:
            try:
                return bundled_default(kind)
            except FileNotFoundError:
                break
    searched = "the current directory"
    if relative_to is not None:
        searched += f" and {relative_to if relative_to.is_dir() else relative_to.parent} upwards"
    raise FileNotFoundError(f"File not found: {value} (searched {searched})")
