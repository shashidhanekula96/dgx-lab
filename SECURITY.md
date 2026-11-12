# Security Policy

Copyright (c) 2026 Shashikanth Dhanekula. SPDX-License-Identifier: MIT.

## Supported versions

Report security issues against the latest `main` branch of this repository.

## Reporting a vulnerability

Please open a private security advisory on the repository host (GitHub / Origin)
or email the maintainer listed in `pyproject.toml` / `dgxlab credits`.

Do **not** open a public issue that includes secrets, API tokens, or private model
endpoints.

## Hardening defaults in this lab

- Local compose publishes **loopback** (`127.0.0.1`) by default.
- Non-loopback serve requires an explicit `ALLOW_NON_LOOPBACK_BIND=1` opt-in and
  still requires `DGX_LAB_API_TOKEN`.
- Remote / cluster eval endpoints must use **HTTPS** plus a bearer token.
- Never put tokens in URLs, git commits, screenshots, or run JSON.
- Prefer digest-pinned container images (`image@sha256:…`) for admit/lock.
