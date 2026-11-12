# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Local experiment registry under the lab data root (no remote telemetry)."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from dgx_lab import OPERATOR_ENV
from dgx_lab.host import detect_profile
from dgx_lab.paths import data_root, ensure_data_layout, load_config

RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")


def records_dir(root: Path | None = None) -> Path:
    root = ensure_data_layout(root or data_root())
    return root / "records"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _short_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:8]


def freeze_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable deep copy (stable key order via dumps roundtrip)."""
    return json.loads(json.dumps(config, sort_keys=True, default=str))


def new_run_id(frozen: dict[str, Any]) -> str:
    """Timestamp + short hash of frozen config with nonce (unique even within the same second)."""
    blob = json.dumps(frozen, sort_keys=True).encode() + secrets.token_bytes(16)
    return f"{_utc_stamp()}-{_short_hash(blob)}"


def run_dir(run_id: str, root: Path | None = None) -> Path:
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"Invalid run id: {run_id}")
    return records_dir(root) / "runs" / run_id


def _operator_name() -> str:
    override = os.environ.get(OPERATOR_ENV, "").strip()
    if override:
        return override
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "unknown"


def create_run(
    config_path: Path,
    *,
    root: Path | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> tuple[str, Path]:
    """Freeze experiment config into a new run record. Returns (run_id, run_dir)."""
    cfg = load_config(config_path)
    frozen = freeze_config(cfg)
    run_id = new_run_id(frozen)
    dest = run_dir(run_id, root)
    dest.mkdir(parents=True, exist_ok=False)
    (dest / "config.frozen.yaml").write_text(
        _to_yaml(frozen),
        encoding="utf-8",
    )
    # Attach host profile + operator (no secrets / tokens).
    profile = detect_profile(probe_docker_gpu=False)
    host_payload = profile.to_dict()
    # Drop bulky check details from the stored host summary if needed — keep checks.
    meta = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_config": str(config_path.resolve()),
        "status": "created",
        "operator": _operator_name(),
        "host": host_payload,
        **(extra_meta or {}),
    }
    write_json(dest / "meta.json", meta)
    # Keep a copy of the original file for audit
    shutil.copy2(config_path, dest / "config.source.yaml")
    return run_id, dest


def load_run(run_id: str, root: Path | None = None) -> dict[str, Any]:
    dest = run_dir(run_id, root)
    if not dest.exists():
        raise FileNotFoundError(f"Unknown run: {run_id}")
    meta = read_json(dest / "meta.json")
    frozen = load_config(dest / "config.frozen.yaml")
    return {"meta": meta, "config": frozen, "path": dest}


def update_run_status(
    run_id: str,
    status: str,
    *,
    root: Path | None = None,
    metrics: dict[str, Any] | None = None,
    notes: str | None = None,
) -> None:
    dest = run_dir(run_id, root)
    meta = read_json(dest / "meta.json")
    meta["status"] = status
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    if notes:
        meta["notes"] = notes
    write_json(dest / "meta.json", meta)
    if metrics is not None:
        write_json(dest / "metrics.json", metrics)


def list_runs(root: Path | None = None) -> list[dict[str, Any]]:
    base = records_dir(root) / "runs"
    if not base.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(base.iterdir(), reverse=True):
        meta_path = child / "meta.json"
        if meta_path.exists():
            out.append(read_json(meta_path))
    return out


def write_lock_record(
    payload: dict[str, Any],
    *,
    root: Path | None = None,
    name: str = "runtime.lock.json",
) -> Path:
    dest = records_dir(root) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, payload)
    return dest


def read_lock_record(
    *,
    root: Path | None = None,
    name: str = "runtime.lock.json",
) -> dict[str, Any] | None:
    dest = records_dir(root) / name
    if not dest.exists():
        return None
    return read_json(dest)


def compare_runs(
    left_id: str,
    right_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    left = load_run(left_id, root)
    right = load_run(right_id, root)
    left_m = _maybe_metrics(left["path"])
    right_m = _maybe_metrics(right["path"])
    cfg_diff = _dict_diff(left["config"], right["config"])
    metrics_diff = _dict_diff(left_m or {}, right_m or {})
    return {
        "left": left_id,
        "right": right_id,
        "config_diff": cfg_diff,
        "metrics_diff": metrics_diff,
        "left_metrics": left_m,
        "right_metrics": right_m,
        "left_status": left["meta"].get("status"),
        "right_status": right["meta"].get("status"),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _maybe_metrics(run_path: Path) -> dict[str, Any] | None:
    p = run_path / "metrics.json"
    if not p.exists():
        return None
    return read_json(p)


def _dict_diff(a: dict[str, Any], b: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    keys = set(a) | set(b)
    changed: dict[str, Any] = {}
    for key in sorted(keys):
        path = f"{prefix}.{key}" if prefix else key
        av, bv = a.get(key, _MISSING), b.get(key, _MISSING)
        if isinstance(av, dict) and isinstance(bv, dict):
            nested = _dict_diff(av, bv, path)
            changed.update(nested)
        elif av != bv:
            changed[path] = {"left": None if av is _MISSING else av, "right": None if bv is _MISSING else bv}
    return changed


class _Missing:
    pass


_MISSING = _Missing()


def _to_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=True, default_flow_style=False)
