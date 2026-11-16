# Contributing

Copyright (c) 2026 Shashikanth Dhanekula. SPDX-License-Identifier: MIT.

Thanks for helping improve **dgx-lab**! By participating you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Setup

```bash
# Linux / macOS / Windows (PowerShell or cmd)
uv sync --group dev
uv run pytest -q
uv run ruff check src tests && uv run ruff format --check src tests
uv run dgxlab check-host
```

## Rules

1. Keep the header on first-party files under `src/`, `tests/`, and `scripts/phase1`
   (CI checks for it):

   ```text
   Copyright (c) 2026 Shashikanth Dhanekula
   SPDX-License-Identifier: MIT
   ```

   For substantial new files you may add your own line below it, e.g.
   `Copyright (c) 2026 Your Name`. Contributions are licensed under MIT.
2. Don't hardcode DGX Spark / aarch64 as a global requirement. Spark-specific
   constraints belong in a runtime candidate `requires:` block.
3. Endpoint security: loopback may use `http://` (and `--no-auth`); remote/cluster
   must use `https://` + bearer token. Never log or persist tokens.
4. Use `uv sync --frozen --group dev` in CI; update `uv.lock` when changing deps.
5. Add or update tests for behavioral changes. Tests must not need a GPU, Docker,
   or network access (use the fake server in `tests/test_connectivity.py`).
6. Sign off your commits (`git commit -s`) to certify the
   [Developer Certificate of Origin](https://developercertificate.org/).

## Pull requests

- Describe the host profile you tested on (`uv run dgxlab check-host`) and, if
  relevant, which backend (vLLM, Ollama, gateway, …).
- Include pytest output.
- Do not commit `.env`, `.api_token`, model weights, run records, or lab data
  under `~/dgx-lab`.
- Add a line to `CHANGELOG.md` under *Unreleased*.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml` and `src/dgx_lab/__init__.py`, move *Unreleased*
   notes under a new `## [x.y.z] - YYYY-MM-DD` heading in `CHANGELOG.md`, merge to `main`.
2. Actions → **Release** → *Run workflow* on `main` → enter `x.y.z`.
   It tests, builds, tags `vx.y.z`, and publishes the GitHub Release with wheel + sdist.
