# dgx-lab

[![CI](https://github.com/shashidhanekula96/dgx-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/shashidhanekula96/dgx-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

**Config-as-code eval harness for OpenAI-compatible LLM endpoints.** Point it at
vLLM, SGLang, Ollama, LM Studio, llama.cpp, or a remote HTTPS gateway. It runs a
golden test set, applies KPI gates, and saves a reproducible run record you can
diff against later runs.

- **Bring your own endpoint.** Local loopback or remote HTTPS, on Linux, macOS, or Windows.
- **Reproducible.** Each run freezes the merged config, host profile, and metrics on disk.
- **Secure by default.** Plain HTTP only on loopback, tokens only in headers, secrets never stored.
- **Optional GPU serving.** Includes a digest-pinned vLLM workflow (NVIDIA DGX Spark profile included).

> Status: **alpha (0.2.1)**. The CLI and run-record format may still change.

**Author:** Shashikanth Dhanekula · **License:** MIT

---

## Install

Requires Python 3.11+.

```bash
# Option A: install the CLI from PyPI
uv tool install dgx-lab
# or: pipx install dgx-lab   ·   or: pip install dgx-lab
# (latest unreleased main: uv tool install git+https://github.com/shashidhanekula96/dgx-lab)

# Option B: work from a clone (needed for scripts/phase1 and editing configs)
git clone https://github.com/shashidhanekula96/dgx-lab && cd dgx-lab
uv sync --group dev
uv run dgxlab --version        # prefix commands with `uv run` in a clone
```

## Quick start (5 minutes)

```bash
dgxlab init-config -o my-exp.yaml          # writes a starter experiment
# edit serve.base_url + serve.model_name in my-exp.yaml
dgxlab check-endpoint --config my-exp.yaml  # verifies URL, auth, and model id
dgxlab run my-exp.yaml --execute            # golden eval + KPI gates
dgxlab status                               # list runs
dgxlab compare <run_a> <run_b>              # diff config + metrics
```

Local server with no API key (Ollama, LM Studio, llama.cpp)? Add `--no-auth`.
It's only accepted for loopback addresses.

**Step-by-step recipes for each backend, SSH tunnels, and gateways:
[docs/connecting.md](docs/connecting.md).**

Exit codes: `0` KPI gates passed · `1` gates failed · `2` config/connection error.

## Configuration

Experiments are YAML files and can `extends:` a base file. See
[`configs/experiments/local-example.yaml`](configs/experiments/local-example.yaml).

```yaml
serve:
  base_url: http://127.0.0.1:8000     # with or without /v1
  model_name: your-model-name
  api_key_env: OPENAI_API_KEY         # optional: NAME of the env var holding the token
  max_tokens: 64
  temperature: 0
resources:
  timeout_s: 120
eval:
  golden: evals/golden/smoke.jsonl    # relative to cwd, then the config's folder upwards
kpis:
  config: configs/kpis/default.yaml
```

Precedence is **CLI flag > environment variable > YAML > built-in default**.

| Setting | Flag | Env var |
|---------|------|---------|
| Endpoint | `--base-url` | `DGX_LAB_BASE_URL` |
| Token | `--token` | `DGX_LAB_API_TOKEN` (or `serve.api_key_env`) |
| Model | `--model` | — |
| Local server without auth | `--no-auth` | — |
| Golden set / KPI file | `--golden` / `--kpi-config` | — |
| Data root | — | `DGX_LAB_ROOT` (default `~/dgx-lab`) |
| Operator name on records | — | `DGX_LAB_OPERATOR` |
| Full tracebacks | — | `DGX_LAB_DEBUG=1` |

### Your own eval cases

A golden file is JSONL, one case per line:

```json
{"id": "math", "messages": [{"role": "user", "content": "2+2? Number only."}], "expect_regex": ["\\b4\\b"], "max_tokens": 16}
```

Checks: `expect_contains` (case-insensitive substrings), `expect_regex`, and
`expect_json_keys` (the reply must contain a JSON object with those keys).

### KPI gates

[`configs/kpis/default.yaml`](configs/kpis/default.yaml) sets `min` / `max` on
`success_rate`, `format_validity_rate`, `mean_latency_ms`, and `tokens_per_second`.
Tune these for your hardware. The defaults are smoke-test floors, not benchmarks.

## Security model

| Target | Allowed | Token |
|--------|---------|-------|
| Loopback (`127.0.0.0/8`, `localhost`, `::1`) | `http://` or `https://` | Required, unless you pass `--no-auth` |
| LAN / cluster / cloud | `https://` only | Always required |

- Credentials in URLs (`user:pass@`, `?api_key=`) are rejected.
- Configs that contain literal secrets (`token:`, `api_key:`, ...) are refused before anything is written.
- The bundled vLLM compose file publishes on `127.0.0.1` only, passes the token via env (not argv), and doesn't enable `--trust-remote-code`.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## What's stored in a run record

Runs live under `$DGX_LAB_ROOT/records/runs/<run_id>/`:

- `config.frozen.yaml`: the merged config (with `extends` resolved), so `dgxlab rerun` reproduces it
- `meta.json`: status, timestamps, resolved endpoint/model (**no token**), **operator**, and a
  **host profile** (OS, arch, CPU, RAM, GPU/Docker, **hostname**)
- `metrics.json`: per-case outputs, latency, token counts, and KPI results

Everything stays on your disk. There's no telemetry. Before you share a record
publicly, check it for hostnames, usernames, and model outputs. Set
`DGX_LAB_OPERATOR` to control the operator name.

## Optional: serve a model on your own GPU (Docker + NVIDIA)

`scripts/phase1` (Linux/macOS) wraps a digest-pinned vLLM workflow:
`init → check-host → download-model → admit → serve → smoke → lock → run-baseline`.

```bash
./scripts/phase1 init
export DGX_LAB_API_TOKEN="$(cat ~/dgx-lab/.api_token)"
export VLLM_IMAGE='vllm/vllm-openai@sha256:<64hex>'   # digest pin required
./scripts/phase1 download-model
./scripts/phase1 admit && ./scripts/phase1 serve && ./scripts/phase1 smoke
./scripts/phase1 lock && ./scripts/phase1 run-baseline
```

The included runtime candidate targets **NVIDIA DGX Spark (aarch64)**. On other
hardware, copy `configs/runtime-candidates/qwen3-8b-spark.yaml`, adjust
`requires:` and the image digest, and point `CANDIDATE_CFG` at it. Publishing on
a non-loopback interface requires `ALLOW_NON_LOOPBACK_BIND=1` and a specific IP
(not `0.0.0.0`). See `./scripts/phase1 --help`, [docs/spark-lab-plan.md](docs/spark-lab-plan.md),
and [docs/phase1-status.md](docs/phase1-status.md).

## Docs

- [Connecting to your environment](docs/connecting.md)
- [Lab architecture](docs/lab-architecture.md)
- [Project context](docs/project-context.md)
- [Spark profile notes](docs/spark-lab-plan.md)

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). CI runs ruff and pytest on Linux, macOS,
and Windows across Python 3.11–3.13.

## Credits

```text
$ dgxlab credits
dgx-lab 0.2.1
Copyright (c) 2026 Shashikanth Dhanekula
Author: Shashikanth Dhanekula
License: MIT (SPDX-License-Identifier: MIT)
```

If this project helps you, please star the repository.
