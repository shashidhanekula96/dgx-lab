# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Secure endpoint validation for local loopback and remote cluster URLs."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

# Query keys that look like credentials. Tokens belong in the Authorization
# header, never in the URL (URLs end up in logs, shell history and run records).
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "key",
        "api_key",
        "api-key",
        "apikey",
        "token",
        "access_token",
        "auth",
        "password",
        "secret",
        "sig",
        "signature",
    }
)

# Suffixes users commonly paste as part of the base URL. We strip them so that
# both ``http://host:8000`` and ``http://host:8000/v1`` work.
_API_SUFFIXES = ("/v1/chat/completions", "/v1/models", "/v1")


class EndpointError(ValueError):
    """Raised when a base URL or bind host violates lab security rules."""


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    scheme: str
    host: str
    port: int | None
    is_loopback: bool
    auth: bool = True

    def api_url(self, path: str) -> str:
        """Build an OpenAI-compatible API URL, e.g. ``api_url('chat/completions')``."""
        base, _, query = self.base_url.partition("?")
        url = f"{base}/v1/{path.lstrip('/')}"
        return f"{url}?{query}" if query else url


def _normalize_host(host: str | None) -> str:
    if not host:
        return ""
    h = host.strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return h


def is_loopback_host(host: str) -> bool:
    h = _normalize_host(host)
    if h in {"localhost", "::1"} or h in LOOPBACK_HOSTS:
        return True
    try:
        # Covers the whole 127.0.0.0/8 range and IPv6 ::1.
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def assert_loopback_bind(bind_host: str, *, allow_non_loopback: bool = False) -> None:
    """Serve/bind must stay on loopback unless the operator opts in."""
    if is_loopback_host(bind_host):
        return
    if allow_non_loopback:
        if bind_host.strip() in {"0.0.0.0", "::", "[::]"}:
            raise EndpointError(
                f"Refusing wildcard bind {bind_host!r}. Bind a specific interface or use 127.0.0.1."
            )
        return
    raise EndpointError(
        f"Refusing bind host {bind_host!r}; loopback only (127.0.0.1 / localhost / ::1). "
        "Pass an explicit opt-in for non-loopback binds."
    )


def _strip_api_suffix(path: str) -> str:
    path = path.rstrip("/")
    for suffix in _API_SUFFIXES:
        if path.endswith(suffix):
            return path[: -len(suffix)].rstrip("/")
    return path


def validate_endpoint(
    base_url: str,
    *,
    token: str | None = None,
    require_token: bool = True,
    allow_no_auth: bool = False,
) -> Endpoint:
    """
    Validate an OpenAI-compatible base URL.

    Rules:
    - scheme must be http or https
    - credentials/userinfo in the URL are rejected
    - credential-looking query parameters (``?api_key=``) are rejected
    - loopback may use http://
    - non-loopback (cluster/remote) requires https:// and a bearer token
    - 0.0.0.0 / wildcard hosts are rejected
    - ``allow_no_auth`` skips the token requirement, but only for loopback hosts
      (Ollama, LM Studio, llama.cpp servers usually run without auth)

    The returned ``base_url`` has any trailing ``/v1`` removed; use
    :meth:`Endpoint.api_url` to build request URLs.
    """
    raw = (base_url or "").strip()
    if not raw:
        raise EndpointError("base_url is required")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise EndpointError(f"Unsupported URL scheme {scheme!r}; use http or https")

    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise EndpointError(
            "Do not embed credentials in the URL; pass a bearer token via --token or DGX_LAB_API_TOKEN"
        )

    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS:
            raise EndpointError(
                f"Do not embed credentials in the URL query ({key!r}); pass a bearer "
                "token via --token or DGX_LAB_API_TOKEN"
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

    has_token = bool((token or "").strip())
    if allow_no_auth and not loopback:
        raise EndpointError(
            "--no-auth is only allowed for loopback endpoints (127.0.0.1 / localhost / ::1). "
            "Remote endpoints require https:// and a bearer token."
        )
    if require_token and not has_token and not allow_no_auth:
        hint = (
            " For a local server without auth (Ollama, LM Studio, llama.cpp) pass --no-auth."
            if loopback
            else ""
        )
        raise EndpointError(
            "API token required. Set DGX_LAB_API_TOKEN or pass --token "
            "(never put the token in the URL)." + hint
        )

    path = _strip_api_suffix(parsed.path)
    clean = f"{scheme}://{parsed.netloc}{path}"
    if parsed.query:
        clean = f"{clean}?{parsed.query}"

    return Endpoint(
        base_url=clean,
        scheme=scheme,
        host=host,
        port=parsed.port,
        is_loopback=loopback,
        auth=has_token,
    )


def auth_headers(token: str | None) -> dict[str, str]:
    """Return request headers; omit Authorization when no token is configured."""
    headers = {"Content-Type": "application/json"}
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def redact_secrets(text: str, token: str | None = None) -> str:
    """Remove a known token from log-ish text."""
    if not text:
        return text
    out = text
    if token:
        out = out.replace(token, "***")
    return out
