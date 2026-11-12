# Spark lab plan (optional profile)

The DGX Spark candidate is **optional**. Day-to-day CLI usage works on any OS.

When targeting Spark specifically:

1. **init** — create `$DGX_LAB_ROOT` layout, `uv sync`, generate API token.
2. **check-host** — record OS/arch/CPU/RAM/GPU (Spark hosts typically report aarch64 + NVIDIA).
3. **download-model** — `Qwen/Qwen3-8B` → `$DGX_LAB_ROOT/models/qwen3-8b` (HF hub; `HF_TOKEN` if gated).
4. **admit** — require digest-pinned `VLLM_IMAGE`, enforce candidate `requires` (aarch64 + linux/arm64), Buildx platform preflight, write admit record (**no lock**).
5. **serve** — compose up on `127.0.0.1:8000`, mount model, require `DGX_LAB_API_TOKEN`.
6. **smoke** — loopback chat completion.
7. **lock** — write admitted digest + model tree SHA into `$DGX_LAB_ROOT/records/runtime.lock.json` only after smoke OK.
8. **run-baseline** — freeze config, golden eval, KPI gates.

## Done means

- Config was frozen (`dgxlab run`) so reruns are reproducible.
- Host + operator provenance is on the run record.
- Smoke passed before any lock/compatibility statement.

## Fallback

If vLLM cannot smoke on Spark, operators may evaluate **llama.cpp + GGUF** manually. That path is **not** automated in `./scripts/phase1`.
