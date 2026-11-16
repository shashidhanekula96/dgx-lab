# Security Policy

Copyright (c) 2026 Shashikanth Dhanekula. SPDX-License-Identifier: MIT.

## Supported versions

Only the latest release / `main` branch receives security fixes while the project
is in alpha.

## Reporting a vulnerability

**Please do not open a public issue.** Report privately through GitHub:

1. Go to the repository's **Security** tab → **Report a vulnerability**
   (<https://github.com/shashidhanekula96/dgx-lab/security/advisories/new>).
2. Include affected version/commit, reproduction steps, and impact.
3. Never include real API tokens, private endpoints, or model weights — redact them.

You can expect an acknowledgement within 7 days. Fixes are coordinated through
the private advisory and credited in the release notes unless you prefer otherwise.

## In scope

- Token/secret leakage (logs, run records, process lists, URLs)
- Bypasses of endpoint rules (plain HTTP to non-loopback, `--no-auth` off loopback)
- Unsafe defaults in `deployments/` or `scripts/phase1` (e.g. non-loopback publish)

Out of scope: vulnerabilities in vLLM, Docker, model weights, or the servers you
connect to — report those upstream.

## Hardening defaults in this lab

- Non-loopback endpoints must use **HTTPS** and a bearer token; `--no-auth` is
  accepted only for loopback (`127.0.0.0/8`, `localhost`, `::1`).
- Tokens are sent only in the `Authorization` header; credentials in URLs
  (userinfo or `?api_key=`-style query params) are rejected.
- Experiment configs containing literal secrets are refused before a run record
  is written; use `serve.api_key_env` to name an env var instead.
- Local compose publishes **loopback** (`127.0.0.1`) by default; non-loopback
  requires `ALLOW_NON_LOOPBACK_BIND=1` and a specific interface (never `0.0.0.0`).
- The vLLM token is passed via `VLLM_API_KEY` env (not argv), and
  `--trust-remote-code` is not enabled.
- Admit requires digest-pinned container images (`image@sha256:…`).
