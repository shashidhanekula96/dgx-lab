# Project context

**Author:** Shashikanth Dhanekula · **License:** MIT

This lab is a durable, multi-OS comparison harness for OpenAI-compatible LLM
runtimes. Operators may run the CLI on any Linux, macOS, or Windows machine,
attach host memory/CPU/GPU metadata to each experiment, and evaluate against:

1. a local loopback server (`http://127.0.0.1:…`), or
2. a remote/cluster gateway over **HTTPS** with a bearer token.

NVIDIA DGX Spark (aarch64 / GB10) remains a supported **optional** profile via
`configs/runtime-candidates/qwen3-8b-spark.yaml`. Those constraints apply only
when that candidate is admitted—not to everyday CLI use.

## Design goals

1. Config-as-code experiments with frozen run records.
2. Secure endpoints (no tokens in URLs; no open `0.0.0.0` by default).
3. Host provenance (OS, arch, CPU, RAM, GPU/Docker) on every run.
4. Digest-pinned container images when admitting a serve runtime.
5. Mandatory author credits in first-party source and tests.
