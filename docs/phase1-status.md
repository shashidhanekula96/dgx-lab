# Phase 1 status

| Item | Status |
|------|--------|
| Repo scaffold + docs | Done |
| Multi-OS host profile | Done (`dgxlab check-host`) |
| Secure endpoints | Done (loopback http / remote https + token) |
| Digest-pinned admit | Done (requires `VLLM_IMAGE=@sha256:…`) |
| Compose loopback serve | Done (`deployments/qwen3-8b-vllm.compose.yaml`) |
| Golden eval + KPI gates | Done |
| Spark profile `requires` | Done (optional candidate only) |
| Smoke on operator hardware | **Pending operator run** |
| Runtime lock | **Blocked on smoke** |
| Hardware-specific compatibility claim | **Not claimed** until smoke OK |

## Candidate image (Spark profile — not locked)

```
vllm/vllm-openai@sha256:4864d46625cbc3307623e29ac742030655e27249feba7b97ec925ce4cc4dfb56
```

- Source: `vllm/vllm-openai:latest` linux/arm64 platform manifest
- Inspected: 2026-09-28 via `docker buildx imagetools inspect`
- Alternate track: CUDA 13 nightly arm64 tags may be admitted later after local smoke

## Blockers (serve path only)

- Hugging Face auth (`HF_TOKEN`) if `Qwen/Qwen3-8B` is gated for the account
- First image pull of the digest-pinned vLLM image (large)
- Smoke must succeed before `lock` and before any compatibility statements
