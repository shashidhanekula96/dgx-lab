# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Golden eval scoring for smoke / baseline runs."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from dgx_lab.endpoint import Endpoint, auth_headers, validate_endpoint

DEFAULT_MAX_TOKENS = 64
REASONING_STORE_CHARS = 4000  # cap stored reasoning per case so run records stay small

# Reasoning models (Qwen3, DeepSeek-R1, QwQ, ...) wrap their chain of thought in tags.
_REASONING_TAGS = "think|thinking|reasoning"
_REASONING_BLOCK = re.compile(rf"<({_REASONING_TAGS})>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_REASONING_OPEN = re.compile(rf"<({_REASONING_TAGS})>", re.IGNORECASE)
_REASONING_CLOSE = re.compile(rf"</({_REASONING_TAGS})>", re.IGNORECASE)
TRUNCATED_REASONING_HINT = (
    "reply ended inside the reasoning block before any answer; raise max_tokens "
    "or disable thinking (e.g. add /no_think to the prompt for Qwen3)"
)


def _short_body(resp: httpx.Response, limit: int = 200) -> str:
    """Server error text collapsed to one line (HTML error pages get noisy)."""
    text = re.sub(r"<[^>]+>", " ", resp.text or "")
    return " ".join(text.split())[:limit]


@dataclass
class EvalCase:
    id: str
    messages: list[dict[str, str]]
    expect_contains: list[str] = field(default_factory=list)
    expect_regex: list[str] = field(default_factory=list)
    expect_json_keys: list[str] = field(default_factory=list)
    max_tokens: int | None = None  # None -> experiment default


@dataclass
class Reply:
    """One chat completion, normalised across OpenAI-compatible servers."""

    text: str
    completion_tokens: int | None = None
    prompt_tokens: int | None = None
    reasoning: str = ""  # server-separated reasoning (reasoning_content / reasoning)
    finish_reason: str | None = None


@dataclass
class CaseResult:
    id: str
    ok: bool
    latency_ms: float
    completion_tokens: int | None
    prompt_tokens: int | None
    text: str
    errors: list[str] = field(default_factory=list)
    reasoning: str = ""
    finish_reason: str | None = None


@dataclass
class EvalReport:
    cases: list[CaseResult]
    success_rate: float
    mean_latency_ms: float
    tokens_per_second: float
    format_validity_rate: float
    reasoning_cases: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success_rate": self.success_rate,
            "mean_latency_ms": self.mean_latency_ms,
            "tokens_per_second": self.tokens_per_second,
            "format_validity_rate": self.format_validity_rate,
            "reasoning_cases": self.reasoning_cases,
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
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in golden file {path}:{line_no}: {exc}") from exc
            try:
                cases.append(
                    EvalCase(
                        id=str(raw["id"]),
                        messages=list(raw["messages"]),
                        expect_contains=list(raw.get("expect_contains") or []),
                        expect_regex=list(raw.get("expect_regex") or []),
                        expect_json_keys=list(raw.get("expect_json_keys") or []),
                        max_tokens=int(raw["max_tokens"]) if raw.get("max_tokens") else None,
                    )
                )
            except (KeyError, TypeError) as exc:
                raise ValueError(f"Invalid golden case at {path}:{line_no}: missing {exc}") from exc
    if not cases:
        raise ValueError(f"Golden file has no cases: {path}")
    return cases


def split_reasoning(text: str) -> tuple[str, str, bool]:
    """
    Separate a reasoning model's chain of thought from its answer.

    Returns ``(answer, reasoning, truncated)``. Handles complete ``<think>...</think>``
    blocks, a closing tag with no opening tag (chat templates that put ``<think>`` in the
    prompt), and an opening tag that is never closed (output cut off mid-reasoning, in
    which case ``truncated`` is True and everything after the tag counts as reasoning).
    """
    parts: list[str] = []

    def _take(match: re.Match[str]) -> str:
        parts.append(match.group(2).strip())
        return ""

    answer = _REASONING_BLOCK.sub(_take, text)
    closes = list(_REASONING_CLOSE.finditer(answer))
    if closes:
        last = closes[-1]
        parts.insert(0, _REASONING_CLOSE.sub("", answer[: last.start()]).strip())
        answer = answer[last.end() :]
    truncated = False
    opened = _REASONING_OPEN.search(answer)
    if opened:
        parts.append(answer[opened.end() :].strip())
        answer = answer[: opened.start()]
        truncated = True
    reasoning = "\n\n".join(p for p in parts if p)
    return answer.strip(), reasoning, truncated


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
    token: str | None = None,
    model: str = "qwen3-8b",
    timeout: float = 120.0,
    temperature: float = 0.0,
    default_max_tokens: int = DEFAULT_MAX_TOKENS,
    allow_no_auth: bool = False,
    strip_reasoning: bool = True,
    client_factory: Callable[[], httpx.Client] | None = None,
    responder: Callable[[EvalCase], Reply | tuple[str, int | None, int | None]] | None = None,
) -> EvalReport:
    """
    Run golden cases against a local or cluster OpenAI-compatible server.

    ``responder`` may be injected for unit tests: it returns a :class:`Reply` or a
    ``(text, completion_tokens, prompt_tokens)`` tuple.
    ``strip_reasoning`` scores only a reasoning model's answer, not its ``<think>`` block.
    Endpoint rules: loopback may use http://; remote/cluster requires https:// + token.
    ``allow_no_auth`` permits a token-less loopback server (Ollama, LM Studio, ...).
    """
    endpoint: Endpoint | None = None
    if responder is None:
        endpoint = validate_endpoint(base_url, token=token, require_token=True, allow_no_auth=allow_no_auth)

    cases = load_golden_jsonl(golden_path)
    results: list[CaseResult] = []
    format_flags: list[bool] = []

    def _default_call(case: EvalCase) -> Reply:
        assert endpoint is not None
        payload = {
            "model": model,
            "messages": case.messages,
            "max_tokens": case.max_tokens or default_max_tokens,
            "temperature": temperature,
        }
        factory = client_factory or (lambda: httpx.Client(timeout=timeout))
        with factory() as client:
            resp = client.post(
                endpoint.api_url("chat/completions"),
                headers=auth_headers(token),
                json=payload,
            )
            if resp.status_code >= 400:
                # Short, token-free error: status + first part of the server message.
                raise RuntimeError(f"HTTP {resp.status_code}: {_short_body(resp)}")
            data = resp.json()
        choice = data["choices"][0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        return Reply(
            text=message.get("content") or "",
            completion_tokens=usage.get("completion_tokens"),
            prompt_tokens=usage.get("prompt_tokens"),
            # vLLM/SGLang reasoning parsers use reasoning_content; Ollama/OpenRouter use reasoning.
            reasoning=message.get("reasoning_content") or message.get("reasoning") or "",
            finish_reason=choice.get("finish_reason"),
        )

    def call(case: EvalCase) -> Reply:
        if responder is None:
            return _default_call(case)
        out = responder(case)
        return out if isinstance(out, Reply) else Reply(*out)

    total_completion_tokens = 0
    total_latency_s = 0.0
    reasoning_cases = 0

    for case in cases:
        t0 = time.perf_counter()
        reasoning, finish_reason = "", None
        try:
            reply = call(case)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            text, ctok, ptok = reply.text, reply.completion_tokens, reply.prompt_tokens
            reasoning, finish_reason = reply.reasoning, reply.finish_reason
            truncated = False
            if strip_reasoning:
                text, inline, truncated = split_reasoning(text)
                reasoning = "\n\n".join(p for p in (reasoning, inline) if p)
            if reasoning:
                reasoning_cases += 1
            if strip_reasoning and not text and (truncated or (reasoning and finish_reason == "length")):
                ok, errors, format_valid = False, [TRUNCATED_REASONING_HINT], False
            else:
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
                reasoning=reasoning[:REASONING_STORE_CHARS],
                finish_reason=finish_reason,
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
        reasoning_cases=reasoning_cases,
    )


def list_models(
    endpoint: Endpoint,
    *,
    token: str | None = None,
    timeout: float = 15.0,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> list[str]:
    """GET ``/v1/models`` and return model ids (connectivity + auth check)."""
    factory = client_factory or (lambda: httpx.Client(timeout=timeout))
    with factory() as client:
        resp = client.get(endpoint.api_url("models"), headers=auth_headers(token))
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"HTTP {resp.status_code}: endpoint rejected the credentials (check DGX_LAB_API_TOKEN / --token)"
        )
    if resp.status_code in (404, 405, 501):
        raise RuntimeError(
            f"HTTP {resp.status_code}: server does not implement GET /v1/models "
            "(check the base URL; some servers only expose /v1/chat/completions)"
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {_short_body(resp)}")
    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else None
    return [str(m.get("id")) for m in (items or []) if isinstance(m, dict) and m.get("id")]
