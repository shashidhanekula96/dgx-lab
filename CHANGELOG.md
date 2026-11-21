# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Manual `Release` workflow (Actions → Release → Run workflow) that tags `main`, builds, and publishes a GitHub Release from CHANGELOG notes.
- `Publish to PyPI` workflow (Trusted Publishing); the Release workflow triggers it, so new versions install with `pip install dgx-lab`.

## [0.2.0] - 2026-11-16

Public-readiness release: works from a plain `pip install`, connects to any
OpenAI-compatible backend, and hardens defaults.

### Added

- `dgxlab check-endpoint`: verifies URL, auth, and model id via `GET /v1/models`.
- `dgxlab init-config`: writes a starter experiment (`configs/experiments/local-example.yaml`).
- `--no-auth` for token-less **loopback** servers (Ollama, LM Studio, llama.cpp); rejected for remote hosts.
- `--model` flag, `DGX_LAB_BASE_URL` env var, and `serve.api_key_env` (name of the env var holding the token).
- Default golden set, KPI gates and starter config are bundled in the wheel.
- `docs/connecting.md` with per-backend recipes, SSH-tunnel pattern and troubleshooting.
- GitHub Actions CI (ruff + pytest on Linux/macOS/Windows × Python 3.11–3.13, wheel smoke test).
- Code of Conduct, issue templates, end-to-end tests against a real local HTTP server.

### Changed

- `dgxlab run` now reads `serve.base_url`, `serve.model_name`, `serve.max_tokens`,
  `serve.temperature`, `resources.timeout_s`, `eval.golden` and `kpis.config` from the
  experiment YAML (precedence: CLI flag > env > YAML > default).
- Clean one-line errors with exit code 2 instead of tracebacks (`DGX_LAB_DEBUG=1` restores them).
- Development status set to Alpha.
- Removed unused `promotion`, `resources.max_concurrent_requests` and `tracking` keys from `base.yaml`.

### Fixed

- Installed (non-editable) package crashed on `run --execute` because default eval files were not found.
- Base URLs ending in `/v1` produced `/v1/v1/chat/completions` requests.
- Failed executions left runs stuck in `running`; they are now marked `failed` with a note.
- `scripts/phase1` loopback check treated `1` or `:` as loopback (unquoted glob `[::1]`).

### Security

- Reject credential-like query parameters (`?api_key=`, `?token=`, …) in base URLs.
- Refuse to record experiment configs containing literal secrets.
- Treat all of `127.0.0.0/8` as loopback.
- Compose: token passed via `VLLM_API_KEY` env instead of `--api-key` argv; `--trust-remote-code` removed;
  `VLLM_IMAGE` / `DGX_LAB_API_TOKEN` now required at compose time.
- SECURITY.md now points to GitHub private vulnerability reporting.

## [0.1.0] - 2026-11-12

### Added

- Multi-OS host profile detection (`dgxlab check-host`) with CPU / memory / GPU / Docker capability recording.
- Secure endpoint validation for loopback HTTP and remote HTTPS + bearer token.
- Run provenance: each run stores `operator` and `host` profile (no secrets).
- Mandatory author credits (`dgxlab credits`) and SPDX headers.
- MIT license, security policy, contributing guide, and GitHub Actions CI.

### Changed

- DGX Spark / ARM64 constraints moved into the optional Spark runtime candidate.
- Compose publish host is configurable; defaults remain loopback-only.
