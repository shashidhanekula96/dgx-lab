## Summary

-

## Host profile tested

```text
# paste: uv run dgxlab check-host
```

## Test plan

- [ ] `uv sync --frozen --group dev`
- [ ] `uv run pytest -q`
- [ ] `uv run ruff check src tests && uv run ruff format --check src tests`
- [ ] `uv run dgxlab credits` shows Shashikanth Dhanekula
- [ ] No secrets / tokens committed

## Checklist

- [ ] First-party files keep the copyright + SPDX header
- [ ] No Spark/aarch64 hardcoded as a global requirement
- [ ] Endpoint changes respect loopback-http / remote-https rules (`--no-auth` loopback only)
- [ ] `CHANGELOG.md` updated under *Unreleased*
