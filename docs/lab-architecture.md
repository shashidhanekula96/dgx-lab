# Lab architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Operator (Linux / macOS / Windows)                         │
│    ./scripts/phase1  →  uv run dgxlab / Python modules      │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  configs/        │ │  $DGX_LAB_ROOT/  │ │  endpoint        │
│  experiments     │ │  records/runs    │ │  validate        │
│  kpis            │ │  models, logs    │ │  loopback|https  │
│  runtime-cand.   │ │  (+ host meta)   │ │  + bearer token  │
└────────┬─────────┘ └────────▲─────────┘ └────────▲─────────┘
         │                    │                    │
         ▼                    │                    │
┌──────────────────┐          │           ┌────────┴─────────┐
│  dgx_lab         │──────────┘           │  Local vLLM or   │
│  host / runtime  │                      │  cluster gateway │
│  evals / kpis    │                      └──────────────────┘
│  tracking / cli  │
└──────────────────┘
```

| Module | Role |
|--------|------|
| `host` | Multi-OS profile (arch, CPU, RAM, optional NVIDIA/Docker) |
| `endpoint` | Secure base URL rules (loopback http / remote https + token, `--no-auth` loopback only), `/v1` normalization |
| `runtime` | Admit / smoke / lock for digest-pinned images |
| `evals` | Golden JSONL scoring |
| `kpis` | Threshold gates |
| `tracking` | Local run registry + host/operator provenance |
| `cli` | `dgxlab run\|rerun\|compare\|status\|check-endpoint\|init-config\|credits\|check-host` |

Experiments use an `extends` overlay (see `configs/experiments/baseline-qwen3-8b.yaml` → `base.yaml`). `dgxlab run` freezes the merged config into the run record and attaches the detected host profile.

Run settings resolve as **CLI flag > env var > experiment YAML > bundled default**.
Bundled defaults (golden set, KPI gates, starter experiment) ship inside the wheel
under `dgx_lab/_data/`; in a source checkout the repository copies are used.
