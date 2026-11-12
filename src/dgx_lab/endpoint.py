# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Secure endpoint validation for local loopback and remote cluster URLs."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


class EndpointError(ValueError):
    """Raised when a base URL or bind host violates lab security rules."""


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    scheme: str
    host: str
    port: int | None
    is_loopback: bool


def _normalize_host(host: str | None) -> str:
    if not host:
        return ""
    h = host.strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return h


def is_loopback_host(host: str) -> bool:
    h = _normalize_host(host)
    return h in {"127.0.0.1", "localhost", "::1"} or h in LOOPBACK_HOSTS


def assert_loopback_bind(bind_host: str, *, allow_non_loopback: bool = False) -> None:
    """Serve/bind must stay on loopback unless the operator opts in."""
    if is_loopback_host(bind_host):
        return
    if allow_non_loopback:
        if bind_host.strip() in {"0.0.0.0", "::", "[::]"}:
            raise EndpointError(
                f"Refusing wildcard bind {bind_host!r}. "
                "Bind a specific interface or use 127.0.0.1."
            )
        return
    raise EndpointError(
        f"Refusing bind host {bind_host!r}; loopback only (127.0.0.1 / localhost / ::1). "
        "Pass an explicit opt-in for non-loopback binds."
    )


def validate_endpoint(
    base_url: str,
    *,
    token: str | None = None,
    require_token: bool = True,
) -> Endpoint:
    """
    Validate an OpenAI-compatible base URL.

    Rules:
    - scheme must be http or https
    - credentials/userinfo in the URL are rejected
    - loopback may use http://
    - non-loopback (cluster/remote) requires https:// and a bearer token
    - 0.0.0.0 / wildcard hosts are rejected
    """
    raw = (base_url or "").strip()
    if not raw:
        raise EndpointError("base_url is required")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise EndpointError(f"Unsupported URL scheme {scheme!r}; use http or https")

    if parsed.username is not None or parsed.password is not None:
        raise EndpointError(
            "Do not embed credentials in the URL; pass a bearer token via "
            "--token or DGX_LAB_API_TOKEN"
        )

    host = _normalize_host(parsed.hostname)
    if not host:
        raise EndpointError(f"URL missing host: {base_url!r}")
    if host in {"0.0.0.0", "::"}:
        raise EndpointError(f"Refusing wildcard host in base_url: {base_url!r}")

    loopback = is_loopback_host(host)
    if not loopback and scheme != "https":
        raise EndpointError(
            f"Non-loopback endpoints must use https:// (got {base_url!r}). "
            "Use http://127.0.0.1 for local serve, or https:// for cluster/remote."
        )

    if require_token and not (token or "").strip():
        raise EndpointError(
            "API token required. Set DGX_LAB_API_TOKEN or pass --token "
            "(never put the token in the URL)."
        )

    # Rebuild a clean base without fragments / userinfo
    netloc = parsed.netloc
    if "@" in netloc:
        raise EndpointError("Do not embed credentials in the URL")
    path = parsed.path.rstrip("/")
    clean = f"{scheme}://{netloc}{path}"
    if parsed.query:
        clean = f"{clean}?{parsed.query}"

    return Endpoint(
        base_url=clean,
        scheme=scheme,
        host=host,
        port=parsed.port,
        is_loopback=loopback,
    )


def redact_secrets(text: str, token: str | None = None) -> str:
    """Remove a known token from log-ish text."""
    if not text:
        return text
    out = text
    if token:
        out = out.replace(token, "***")
    return out
