# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Golden eval scoring for smoke / baseline runs."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from dgx_lab.endpoint import validate_endpoint


@dataclass
class EvalCase:
    id: str
    messages: list[dict[str, str]]
    expect_contains: list[str] = field(default_factory=list)
    expect_regex: list[str] = field(default_factory=list)
    expect_json_keys: list[str] = field(default_factory=list)
    max_tokens: int = 64


@dataclass
class CaseResult:
    id: str
    ok: bool
    latency_ms: float
    completion_tokens: int | None
    prompt_tokens: int | None
    text: str
    errors: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    cases: list[CaseResult]
    success_rate: float
    mean_latency_ms: float
    tokens_per_second: float
    format_validity_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "success_rate": self.success_rate,
            "mean_latency_ms": self.mean_latency_ms,
            "tokens_per_second": self.tokens_per_second,
            "format_validity_rate": self.format_validity_rate,
            "n": len(self.cases),
            "cases": [asdict(c) for c in self.cases],
        }


def load_golden_jsonl(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            try:
                cases.append(
                    EvalCase(
                        id=str(raw["id"]),
                        messages=list(raw["messages"]),
                        expect_contains=list(raw.get("expect_contains") or []),
                        expect_regex=list(raw.get("expect_regex") or []),
                        expect_json_keys=list(raw.get("expect_json_keys") or []),
                        max_tokens=int(raw.get("max_tokens") or 64),
                    )
                )
            except KeyError as exc:
                raise ValueError(f"Invalid golden case at {path}:{line_no}: {exc}") from exc
    return cases


def score_text(case: EvalCase, text: str) -> tuple[bool, list[str], bool]:
    """Return (ok, errors, format_valid)."""
    errors: list[str] = []
    format_valid = True
    for needle in case.expect_contains:
        if needle.lower() not in text.lower():
            errors.append(f"missing substring: {needle!r}")
    for pattern in case.expect_regex:
        if not re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            errors.append(f"regex not matched: {pattern!r}")
    if case.expect_json_keys:
        format_valid = False
        try:
            # Allow fenced json or raw object
            blob = text
            fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if fence:
                blob = fence.group(1)
            else:
                start = text.find("{")
                end = text.rfind("}")
                if start >= 0 and end > start:
                    blob = text[start : end + 1]
            parsed = json.loads(blob)
            if not isinstance(parsed, dict):
                errors.append("expected JSON object")
            else:
                missing = [k for k in case.expect_json_keys if k not in parsed]
                if missing:
                    errors.append(f"missing JSON keys: {missing}")
                else:
                    format_valid = True
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON: {exc}")
    ok = not errors
    if not case.expect_json_keys:
        format_valid = ok
    return ok, errors, format_valid


def run_golden_eval(
    golden_path: Path,
    *,
    base_url: str = "http://127.0.0.1:8000",
    token: str,
    model: str = "qwen3-8b",
    timeout: float = 120.0,
    client_factory: Callable[[], httpx.Client] | None = None,
    responder: Callable[[EvalCase], tuple[str, int | None, int | None]] | None = None,
) -> EvalReport:
    """
    Run golden cases against a local or cluster OpenAI-compatible server.

    ``responder`` may be injected for unit tests (returns text, completion_tokens, prompt_tokens).
    Endpoint rules: loopback may use http://; remote/cluster requires https:// + token.
    """
    endpoint = None
    if responder is None:
        endpoint = validate_endpoint(base_url, token=token, require_token=True)
        resolved_base = endpoint.base_url
    else:
        resolved_base = base_url

    cases = load_golden_jsonl(golden_path)
    results: list[CaseResult] = []
    format_flags: list[bool] = []

    def _default_call(case: EvalCase) -> tuple[str, int | None, int | None]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": case.messages,
            "max_tokens": case.max_tokens,
            "temperature": 0,
        }
        factory = client_factory or (lambda: httpx.Client(timeout=timeout))
        with factory() as client:
            resp = client.post(
                f"{resolved_base.rstrip('/')}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        return text, usage.get("completion_tokens"), usage.get("prompt_tokens")

    call = responder or _default_call

    total_completion_tokens = 0
    total_latency_s = 0.0

    for case in cases:
        t0 = time.perf_counter()
        try:
            text, ctok, ptok = call(case)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            ok, errors, format_valid = score_text(case, text)
        except Exception as exc:  # noqa: BLE001 — collect per-case failures
            latency_ms = (time.perf_counter() - t0) * 1000.0
            text, ctok, ptok = "", None, None
            ok, errors, format_valid = False, [str(exc)], False
        total_latency_s += latency_ms / 1000.0
        if ctok:
            total_completion_tokens += int(ctok)
        format_flags.append(format_valid)
        results.append(
            CaseResult(
                id=case.id,
                ok=ok,
                latency_ms=latency_ms,
                completion_tokens=ctok,
                prompt_tokens=ptok,
                text=text,
                errors=errors,
            )
        )

    n = len(results) or 1
    success_rate = sum(1 for r in results if r.ok) / n
    mean_latency = sum(r.latency_ms for r in results) / n
    tps = (total_completion_tokens / total_latency_s) if total_latency_s > 0 else 0.0
    format_rate = sum(1 for f in format_flags if f) / n
    return EvalReport(
        cases=results,
        success_rate=success_rate,
        mean_latency_ms=mean_latency,
        tokens_per_second=tps,
        format_validity_rate=format_rate,
    )
