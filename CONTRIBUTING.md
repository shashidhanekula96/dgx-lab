# Contributing

Copyright (c) 2026 Shashikanth Dhanekula. SPDX-License-Identifier: MIT.

Thanks for helping improve **dgx-lab**.

## Setup

```bash
# Linux / macOS / Windows (PowerShell or cmd)
uv sync --group dev
uv run pytest -q
uv run dgxlab credits
uv run dgxlab check-host
```

## Rules

1. Keep first-party files under `src/`, `tests/`, and `scripts/phase1` headed with:

   ```text
   Copyright (c) 2026 Shashikanth Dhanekula
   SPDX-License-Identifier: MIT
   ```

2. Do not hardcode DGX Spark / aarch64 as a global requirement. Spark-specific
   constraints belong in a runtime candidate `requires:` block.
3. Endpoint security: loopback may use `http://`; remote/cluster must use
   `https://` + bearer token. Never log tokens.
4. Prefer `uv sync --frozen --group dev` in CI.
5. Add or update tests for behavioral changes.

## Pull requests

- Describe the host profile you tested on (`uv run dgxlab check-host`).
- Include pytest output.
- Do not commit `.env`, `.api_token`, model weights, or lab data under `~/dgx-lab`.
