# Security Policy

Copyright (c) 2026 Shashikanth Dhanekula. SPDX-License-Identifier: MIT.

## Supported versions

dgx-lab is in **alpha**. Only the latest release receives security fixes.

| Version | Supported |
|---------|-----------|
| 0.2.x (latest) | ✅ |
| < 0.2 | ❌ Upgrade with `uv tool upgrade dgx-lab` or `pip install -U dgx-lab` |

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for a security problem.**
Report it privately through GitHub:

1. Open the repository's **Security** tab → **Report a vulnerability**
   (<https://github.com/shashidhanekula96/dgx-lab/security/advisories/new>).
2. Include the affected version or commit, the steps to reproduce, and the impact.
3. **Redact secrets.** Never include real API tokens, private endpoint URLs, hostnames
   you don't want shared, or model weights.

What to expect:

| Step | Target |
|------|--------|
| Acknowledgement | within 7 days |
| Initial assessment (valid / not valid, severity) | within 14 days |
| Fix or mitigation for confirmed high/critical issues | as soon as practical, normally within 30 days |

Fixes are coordinated in the private advisory, released as a new version, and
published as a GitHub Security Advisory. You're credited in the advisory and
release notes unless you'd rather not be. Please give us a reasonable chance to
ship a fix before disclosing publicly.

## Scope

**In scope**

- Token or secret leakage: logs, error messages, run records, process lists, URLs
- Bypasses of the endpoint rules: plain HTTP to a non-loopback host, `--no-auth` off loopback,
  credentials accepted in URLs
- A config containing a literal secret being written to disk
- Unsafe defaults in `deployments/` or `scripts/phase1`, e.g. publishing on a non-loopback interface
- The release and publishing pipeline: workflows in `.github/workflows/`

**Out of scope.** Report these upstream:

- Vulnerabilities in vLLM, SGLang, Ollama, LM Studio, llama.cpp, Docker or a hosted API
- Model behaviour: jailbreaks, harmful or incorrect outputs, prompt injection *of the model*
- Issues that need an attacker who already controls your machine or your `DGX_LAB_ROOT`

## Security model

dgx-lab is a client. It sends the prompts in your golden set to an endpoint **you**
configure, scores the replies, and writes a run record to your disk.

### Endpoints and credentials

| Target | Allowed scheme | Token |
|--------|----------------|-------|
| Loopback (`127.0.0.0/8`, `localhost`, `::1`) | `http://` or `https://` | Required unless you pass `--no-auth` |
| Anything else (LAN, cluster, cloud) | `https://` only | Always required |

- Tokens are sent only in the `Authorization` header. Credentials in URLs (`user:pass@`,
  `?api_key=`) are rejected.
- Tokens come from `--token`, `DGX_LAB_API_TOKEN`, or the env var *named* by `serve.api_key_env`.
  Experiment configs that contain a literal secret (`token:`, `api_key:`, ...) are refused before
  anything is written.
- Tokens are never stored in run records, never logged, and never put on a command line.

### Model output is treated as untrusted data

Replies are matched against substrings, regular expressions and `json.loads`, and stored as
text. They are never executed, rendered as HTML, or passed to a shell. Configs are parsed with
`yaml.safe_load`, and helper commands (`nvidia-smi`, `docker`) run without a shell.

### What a run record contains

Records live under `$DGX_LAB_ROOT/records/runs/<run_id>/` (default `~/dgx-lab`). They
contain **no tokens**, but they do contain:

- the prompts from your golden set and the model's replies, including reasoning text
  (capped at 4,000 characters per case);
- the endpoint URL and model name;
- the operator name (`DGX_LAB_OPERATOR`, else your OS username) and a host profile
  (OS, CPU, RAM, GPU, **hostname**).

There is no telemetry: nothing is sent anywhere except to the endpoint you configured.
**Review a record before sharing it.** Don't put confidential data in a golden set you
send to a third-party API.

### Optional GPU serving (`scripts/phase1`, `deployments/`)

- The vLLM compose file publishes on **`127.0.0.1`** by default. Any other interface
  requires `ALLOW_NON_LOOPBACK_BIND=1` and a specific IP. `0.0.0.0` is refused.
- The vLLM token is passed through the `VLLM_API_KEY` env var, not argv.
  `--trust-remote-code` is not enabled.
- `admit` only accepts digest-pinned images (`image@sha256:…`), so a tag can't be
  silently replaced underneath you.

## Supply chain

How releases are produced, so you can judge what you install:

- **PyPI publishing uses Trusted Publishing (OIDC).** No PyPI token exists in the
  repository or its secrets. Only the `publish-pypi.yml` workflow, running from `main`
  in the `pypi` environment, can publish. It checks that the tag is a published GitHub
  Release on `main` and matches `pyproject.toml`, and runs the test suite first.
- **Provenance.** Releases uploaded this way carry PyPI digital attestations, which tie
  each file to the exact workflow run that built it. They are shown on the file's page
  on pypi.org.
- **Locked, minimal dependencies.** The runtime needs only `httpx`, `pydantic` and `pyyaml`.
  Development and CI use the hash-locked `uv.lock` (`uv sync --frozen`).
- **Pinned actions.** The publishing workflow pins every action to a full commit SHA.
- **Automated checks.** Dependabot (dependency and Actions updates, security alerts),
  GitHub secret scanning with push protection, and CodeQL code scanning are enabled.
- **Protected branches and tags.** `main` only changes through pull requests that pass
  CI on Linux, macOS and Windows. Release tags (`v*`) can't be moved or deleted.

## Hardening checklist for operators

- Prefer an **SSH tunnel** to a remote GPU box over exposing its port. See
  [docs/connecting.md](docs/connecting.md).
- Keep tokens in a git-ignored `.env` file or your shell, never in experiment YAML.
- Use a dedicated, revocable API key for evals, scoped to the minimum needed.
- Set `DGX_LAB_OPERATOR` if you don't want your OS username on records.
- Pin a version (`dgx-lab==0.2.1`) in automation, and upgrade deliberately.
