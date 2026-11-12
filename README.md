# dgx-lab

**Author:** Shashikanth Dhanekula · **License:** MIT

Config-as-code comparison harness for OpenAI-compatible LLM runtimes. Run locally
on Linux, macOS, or Windows; point evals at a loopback server or a secure cluster
HTTPS endpoint. NVIDIA DGX Spark is an **optional** runtime profile—not a hard
requirement for the CLI.

## Install (any OS)

```bash
# Requires Python 3.11+ and uv (https://docs.astral.sh/uv/)
uv sync --group dev
uv run dgxlab credits
uv run dgxlab check-host
uv run pytest -q
```

Windows users can run the same `uv` commands from PowerShell or cmd. The
`./scripts/phase1` helper is a Linux/macOS convenience wrapper around the same
Python CLI.

## Quick start

```bash
export DGX_LAB_ROOT="${DGX_LAB_ROOT:-$HOME/dgx-lab}"   # optional override
uv run dgxlab run configs/experiments/baseline-qwen3-8b.yaml
uv run dgxlab status
uv run dgxlab compare <run_a> <run_b>
```

Each run record stores:

- frozen experiment config
- **operator** (`DGX_LAB_OPERATOR` or the local username)
- **host** profile (OS, arch, CPU count, memory, GPU/Docker capabilities)

Tokens are never written into run JSON.

## Endpoints (security)

| Target | Allowed URL | Token |
|--------|-------------|-------|
| Local loopback | `http://127.0.0.1:8000` / `http://localhost:8000` / `http://[::1]:8000` | Required (`DGX_LAB_API_TOKEN` or `--token`) |
| Cluster / remote | `https://your-cluster.example/...` | Required |
| Plain `http://` to a LAN/public host | **Rejected** | — |

Example against a remote OpenAI-compatible gateway:

```bash
export DGX_LAB_API_TOKEN='…'
uv run dgxlab run configs/experiments/baseline-qwen3-8b.yaml \
  --execute \
  --base-url 'https://your-cluster.example/v1' \
  --token "$DGX_LAB_API_TOKEN"
```

## Optional GPU serve (Docker + NVIDIA)

```bash
# Linux/macOS helper — generates ~/dgx-lab layout + API token
./scripts/phase1 init
./scripts/phase1 check-host

# Digest-pin from a candidate config (Spark profile is optional)
export VLLM_IMAGE='vllm/vllm-openai@sha256:<64hex>'
export DGX_LAB_API_TOKEN="$(cat ~/dgx-lab/.api_token)"
# export HF_TOKEN=...   # only if the HF repo is gated

./scripts/phase1 download-model
# For Spark-only candidate requirements, keep the default CANDIDATE_CFG.
# On other hosts, point CANDIDATE_CFG at a candidate that matches your machine.
./scripts/phase1 admit
./scripts/phase1 serve    # publishes 127.0.0.1 only by default
./scripts/phase1 smoke
./scripts/phase1 lock     # only after smoke OK
./scripts/phase1 run-baseline
```

Non-loopback compose publish requires an explicit opt-in:

```bash
export ALLOW_NON_LOOPBACK_BIND=1
export SERVE_BIND_HOST=10.0.0.5   # specific interface — not 0.0.0.0
```

## Data root

Created by `init` / first CLI use:

```
~/dgx-lab/{models,datasets,adapters,evals,records,logs}
```

Override with `DGX_LAB_ROOT`.

## Docs

- [Project context](docs/project-context.md)
- [Lab architecture](docs/lab-architecture.md)
- [Spark profile notes](docs/spark-lab-plan.md)
- [Phase 1 status](docs/phase1-status.md)

## Credits

```bash
uv run dgxlab credits
```

```
dgx-lab 0.1.0
Copyright (c) 2026 Shashikanth Dhanekula
Author: Shashikanth Dhanekula
License: MIT (SPDX-License-Identifier: MIT)
```

Public repository: https://github.com/shashidhanekula96/dgx-lab

If this project helps you, please star the repository.
