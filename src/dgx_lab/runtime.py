# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Runtime admit / smoke / lock for digest-pinned vLLM container images."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from dgx_lab import API_TOKEN_ENV
from dgx_lab.endpoint import EndpointError, assert_loopback_bind, validate_endpoint
from dgx_lab.host import detect_profile, profile_matches_requires
from dgx_lab.paths import data_root, load_config
from dgx_lab.tracking import read_lock_record, write_json, write_lock_record

DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
IMAGE_DIGEST_RE = re.compile(
    r"^(?P<ref>.+?)@(?P<digest>sha256:[a-f0-9]{64})$"
)


class AdmitError(ValueError):
    """Raised when a candidate runtime fails admission preflight."""


def parse_image_pin(image: str) -> tuple[str, str]:
    """Return (repo_ref, digest) from ``name@sha256:...``."""
    match = IMAGE_DIGEST_RE.match(image.strip())
    if not match:
        raise AdmitError(
            "VLLM_IMAGE must be digest-pinned as "
            "'registry/image@sha256:<64hex>' (no floating tags for admit)."
        )
    return match.group("ref"), match.group("digest")


def require_vllm_image_env(env: dict[str, str] | None = None) -> str:
    env = env or os.environ
    value = env.get("VLLM_IMAGE", "").strip()
    if not value:
        raise AdmitError(
            "VLLM_IMAGE is required for admit. "
            "Example: export VLLM_IMAGE='vllm/vllm-openai@sha256:<64hex>'"
        )
    parse_image_pin(value)
    return value


def buildx_platform_preflight(
    image: str,
    *,
    required_platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Inspect image manifest via Buildx; optionally require specific platforms."""
    parse_image_pin(image)
    proc = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    text = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise AdmitError(f"buildx imagetools inspect failed for {image}: {text[:400]}")

    platforms = _parse_platforms(text)
    required = [p.lower() for p in (required_platforms or [])]
    matched: list[str] = []
    for req in required:
        if "/" not in req:
            continue
        want_os, want_arch = req.split("/", 1)
        arch_aliases = {want_arch}
        if want_arch in {"arm64", "aarch64"}:
            arch_aliases.update({"arm64", "aarch64"})
        ok = any(
            p.get("os", "").lower() == want_os
            and p.get("architecture", "").lower() in arch_aliases
            for p in platforms
        )
        if not ok:
            lowered = text.lower()
            if req in lowered or (want_arch == "arm64" and "linux/arm64" in lowered):
                ok = True
        if ok:
            matched.append(req)
        else:
            raise AdmitError(
                f"Required platform {req} not found for {image}. "
                f"Platforms seen: {platforms or 'none'}"
            )

    return {
        "image": image,
        "platforms": platforms,
        "required_platforms": required,
        "matched_platforms": matched,
        "inspect_excerpt": "\n".join(text.splitlines()[:40]),
    }


def buildx_arm64_preflight(image: str) -> dict[str, Any]:
    """Backward-compatible ARM64-only preflight used by Spark candidates."""
    result = buildx_platform_preflight(image, required_platforms=["linux/arm64"])
    result["arm64"] = True
    return result


def _parse_platforms(inspect_text: str) -> list[dict[str, str]]:
    platforms: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in inspect_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("platform:"):
            value = stripped.split(":", 1)[1].strip()
            if "/" in value:
                os_name, arch = value.split("/", 1)
                platforms.append({"os": os_name, "architecture": arch.split("/")[0]})
            continue
        if "Architecture:" in stripped or stripped.lower().startswith("architecture:"):
            arch = stripped.split(":", 1)[1].strip()
            current["architecture"] = arch
        if stripped.lower().startswith("os:") and "os version" not in stripped.lower():
            current["os"] = stripped.split(":", 1)[1].strip()
        if current.get("os") and current.get("architecture"):
            platforms.append(dict(current))
            current = {}
    return platforms


def admit_candidate(
    candidate_config: Path,
    *,
    env: dict[str, str] | None = None,
    root: Path | None = None,
    probe_docker_gpu: bool = False,
) -> dict[str, Any]:
    """
    Preflight a digest-pinned vLLM image.

    Does **not** lock. Records an admit attempt under records/admits/.
    Applies candidate ``requires`` against the detected host profile.
    """
    cfg = load_config(candidate_config)
    image = require_vllm_image_env(env)
    _, digest = parse_image_pin(image)

    cfg_image = (cfg.get("runtime") or {}).get("image") or cfg.get("image")
    if cfg_image and cfg_image != image:
        raise AdmitError(
            f"VLLM_IMAGE ({image}) does not match candidate config image ({cfg_image}). "
            "Update the env or the config so they agree before admit."
        )

    requires = cfg.get("requires") or (cfg.get("runtime") or {}).get("requires") or {}
    profile = detect_profile(probe_docker_gpu=probe_docker_gpu)
    mismatches = profile_matches_requires(profile, requires if isinstance(requires, dict) else {})
    if mismatches:
        raise AdmitError(
            "Host does not satisfy candidate requires: " + "; ".join(mismatches)
        )

    runtime_platform = (cfg.get("runtime") or {}).get("platform")
    required_platforms: list[str] = []
    if isinstance(runtime_platform, str) and runtime_platform:
        required_platforms = [runtime_platform]
    elif isinstance(requires, dict) and requires.get("platform"):
        plat = requires["platform"]
        required_platforms = [plat] if isinstance(plat, str) else list(plat)

    if required_platforms:
        preflight = buildx_platform_preflight(image, required_platforms=required_platforms)
    else:
        # No platform pin — still inspect so admit records platforms, but do not fail.
        parse_image_pin(image)
        proc = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", image],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        text = proc.stdout + proc.stderr
        if proc.returncode != 0:
            raise AdmitError(
                f"buildx imagetools inspect failed for {image}: {text[:400]}"
            )
        preflight = {
            "image": image,
            "platforms": _parse_platforms(text),
            "required_platforms": [],
            "matched_platforms": [],
            "inspect_excerpt": "\n".join(text.splitlines()[:40]),
        }

    source = (cfg.get("candidate") or {}).get("source") or cfg.get("source")
    inspected_at = (cfg.get("candidate") or {}).get("inspected_at") or cfg.get(
        "inspected_at"
    )

    record = {
        "status": "admitted_preflight",
        "admitted_at": datetime.now(timezone.utc).isoformat(),
        "image": image,
        "digest": digest,
        "candidate_config": str(candidate_config.resolve()),
        "candidate_source": source,
        "candidate_inspected_at": inspected_at,
        "requires": requires,
        "host": profile.to_dict(),
        "buildx": {
            "platforms": preflight.get("platforms"),
            "required_platforms": preflight.get("required_platforms"),
            "matched_platforms": preflight.get("matched_platforms"),
            "arm64": any(
                (p.get("architecture") or "").lower() in {"arm64", "aarch64"}
                for p in (preflight.get("platforms") or [])
            ),
        },
        "locked": False,
        "notes": "Preflight only — run smoke on this host before lock.",
    }
    root = root or data_root()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = root / "records" / "admits" / f"{stamp}-{digest[7:15]}.json"
    write_json(out, record)
    write_json(root / "records" / "admit.latest.json", record)
    return record


def loopback_bound(host: str, port: int) -> bool:
    """Return True if something is listening on loopback:port."""
    if not is_loopback_host_compat(host):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def is_loopback_host_compat(host: str) -> bool:
    from dgx_lab.endpoint import is_loopback_host

    return is_loopback_host(host)


def assert_loopback_only(bind_host: str) -> None:
    """Compat wrapper — raises AdmitError for non-loopback binds."""
    try:
        assert_loopback_bind(bind_host, allow_non_loopback=False)
    except EndpointError as exc:
        raise AdmitError(str(exc)) from exc


def smoke_chat(
    *,
    base_url: str = "http://127.0.0.1:8000",
    token: str | None = None,
    model: str = "qwen3-8b",
    timeout: float = 120.0,
    bind_host: str = "127.0.0.1",
    allow_remote: bool = False,
) -> dict[str, Any]:
    """POST a tiny chat completion; require token + validated endpoint."""
    token = token if token is not None else os.environ.get(API_TOKEN_ENV, "")
    try:
        if not allow_remote:
            assert_loopback_bind(bind_host, allow_non_loopback=False)
        endpoint = validate_endpoint(base_url, token=token, require_token=True)
        if not allow_remote and not endpoint.is_loopback:
            raise EndpointError(
                f"Smoke base_url must be loopback unless allow_remote=True, got {base_url}"
            )
    except EndpointError as exc:
        raise AdmitError(str(exc)) from exc

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        "max_tokens": 16,
        "temperature": 0,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            f"{endpoint.base_url.rstrip('/')}/v1/chat/completions",
            headers=headers,
            json=payload,
        )
    body: Any
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:500]}
    ok = resp.status_code == 200 and isinstance(body, dict) and "choices" in body
    return {
        "ok": ok,
        "status_code": resp.status_code,
        "body": body,
        "base_url": endpoint.base_url,
        "model": model,
        "is_loopback": endpoint.is_loopback,
    }


def sha256_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def model_tree_digest(model_dir: Path) -> str:
    """Stable digest over sorted relative paths + file sha256 (for lock records)."""
    if not model_dir.is_dir():
        raise FileNotFoundError(f"Model path not found: {model_dir}")
    lines: list[str] = []
    for path in sorted(model_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(model_dir).as_posix()
            lines.append(f"{rel}:{sha256_file(path)}")
    blob = "\n".join(lines).encode()
    return hashlib.sha256(blob).hexdigest()


def lock_runtime(
    *,
    root: Path | None = None,
    model_dir: Path | None = None,
    require_smoke_ok: bool = True,
    smoke_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Write admitted digest + model tree SHA into records after successful smoke.

    Reads ``records/admit.latest.json``. Refuses to lock if smoke did not pass.
    """
    root = root or data_root()
    admit = None
    latest = root / "records" / "admit.latest.json"
    if latest.exists():
        admit = json.loads(latest.read_text(encoding="utf-8"))
    if not admit:
        raise AdmitError("No admit.latest.json — run admit before lock")

    if require_smoke_ok:
        if not smoke_result or not smoke_result.get("ok"):
            raise AdmitError("Refusing lock: smoke has not passed on this box")

    model_dir = model_dir or (root / "models" / "qwen3-8b")
    model_sha = model_tree_digest(model_dir) if model_dir.exists() else None
    if model_sha is None:
        raise AdmitError(f"Model directory missing for lock: {model_dir}")

    payload = {
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "image": admit["image"],
        "digest": admit["digest"],
        "model_dir": str(model_dir),
        "model_tree_sha256": model_sha,
        "candidate_source": admit.get("candidate_source"),
        "candidate_inspected_at": admit.get("candidate_inspected_at"),
        "smoke": {
            "ok": True,
            "status_code": (smoke_result or {}).get("status_code"),
            "base_url": (smoke_result or {}).get("base_url"),
        },
        "locked": True,
        "compatibility_claim": (
            "Smoke passed on this host for the locked digest+model. "
            "Hardware-specific production claims remain operator-owned."
        ),
    }
    path = write_lock_record(payload, root=root)
    payload["lock_path"] = str(path)
    return payload


def current_lock(root: Path | None = None) -> dict[str, Any] | None:
    return read_lock_record(root=root)
