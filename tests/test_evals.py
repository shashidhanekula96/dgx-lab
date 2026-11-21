# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for golden eval scoring."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from dgx_lab.endpoint import EndpointError
from dgx_lab.evals import (
    TRUNCATED_REASONING_HINT,
    EvalCase,
    Reply,
    load_golden_jsonl,
    run_golden_eval,
    score_text,
    split_reasoning,
)


def test_score_contains_and_regex():
    case = EvalCase(
        id="t1",
        messages=[{"role": "user", "content": "hi"}],
        expect_contains=["hello"],
        expect_regex=[r"\bworld\b"],
    )
    ok, errors, fmt = score_text(case, "Hello World!")
    assert ok and not errors and fmt


def test_score_json_keys():
    case = EvalCase(
        id="j",
        messages=[],
        expect_json_keys=["status", "value"],
    )
    ok, errors, fmt = score_text(case, 'Here: {"status": "ok", "value": 1}')
    assert ok and fmt and not errors
    ok2, errors2, fmt2 = score_text(case, "not json")
    assert not ok2 and not fmt2 and errors2


def test_load_and_run_golden(tmp_path: Path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id":"a","messages":[{"role":"user","content":"x"}],"expect_contains":["ok"]}\n'
        '{"id":"b","messages":[{"role":"user","content":"y"}],"expect_contains":["nope"]}\n',
        encoding="utf-8",
    )
    cases = load_golden_jsonl(golden)
    assert len(cases) == 2

    def responder(case: EvalCase):
        text = "ok" if case.id == "a" else "fail"
        return text, 1, 1

    report = run_golden_eval(golden, token="t", responder=responder)
    assert report.success_rate == 0.5
    assert len(report.cases) == 2


def test_eval_rejects_insecure_remote_without_https(tmp_path: Path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id":"a","messages":[{"role":"user","content":"x"}],"expect_contains":["ok"]}\n',
        encoding="utf-8",
    )
    with pytest.raises(EndpointError, match="https"):
        run_golden_eval(golden, base_url="http://evil.example", token="t")


# --- reasoning models (<think> blocks) -------------------------------------------------


def test_split_reasoning_complete_block():
    answer, reasoning, truncated = split_reasoning("<think>2+2 is 4</think>\n\n4")
    assert answer == "4" and reasoning == "2+2 is 4" and not truncated


def test_split_reasoning_close_tag_only():
    # Chat templates that inject <think> into the prompt return only the closing tag.
    answer, reasoning, truncated = split_reasoning("let me think...</think>hello")
    assert answer == "hello" and reasoning == "let me think..." and not truncated


def test_split_reasoning_unclosed_is_truncated():
    answer, reasoning, truncated = split_reasoning("<think>still going and going")
    assert answer == "" and reasoning == "still going and going" and truncated


def test_split_reasoning_plain_text_untouched():
    assert split_reasoning("  hello  ") == ("hello", "", False)


def _golden(tmp_path: Path, line: str) -> Path:
    golden = tmp_path / "g.jsonl"
    golden.write_text(line + "\n", encoding="utf-8")
    return golden


def test_reasoning_is_not_scored(tmp_path: Path):
    # "hello" appears only in the reasoning; the answer itself is wrong -> must fail.
    golden = _golden(tmp_path, '{"id":"a","messages":[],"expect_contains":["hello"]}')
    report = run_golden_eval(
        golden, token="t", responder=lambda c: ("<think>user wants hello</think>goodbye", 5, 1)
    )
    assert report.success_rate == 0.0
    assert report.cases[0].text == "goodbye"
    assert report.cases[0].reasoning == "user wants hello"
    assert report.reasoning_cases == 1


def test_json_answer_after_reasoning_passes(tmp_path: Path):
    golden = _golden(tmp_path, '{"id":"j","messages":[],"expect_json_keys":["status"]}')
    text = '<think>I should return {"draft": true}</think>{"status": "ok"}'
    report = run_golden_eval(golden, token="t", responder=lambda c: (text, 5, 1))
    assert report.success_rate == 1.0 and report.format_validity_rate == 1.0


def test_truncated_reasoning_gets_hint(tmp_path: Path):
    golden = _golden(tmp_path, '{"id":"a","messages":[],"expect_contains":["4"]}')
    report = run_golden_eval(golden, token="t", responder=lambda c: ("<think>hmm, 2+2", 16, 1))
    assert not report.cases[0].ok
    assert report.cases[0].errors == [TRUNCATED_REASONING_HINT]


def test_server_separated_reasoning(tmp_path: Path):
    # vLLM --reasoning-parser: content holds only the answer, reasoning_content the thoughts.
    golden = _golden(tmp_path, '{"id":"a","messages":[],"expect_contains":["4"]}')
    reply = Reply(text="", completion_tokens=64, reasoning="2+2...", finish_reason="length")
    report = run_golden_eval(golden, token="t", responder=lambda c: reply)
    assert report.cases[0].errors == [TRUNCATED_REASONING_HINT]
    assert report.cases[0].finish_reason == "length" and report.reasoning_cases == 1


def test_strip_reasoning_off_scores_raw_text(tmp_path: Path):
    golden = _golden(tmp_path, '{"id":"a","messages":[],"expect_contains":["hello"]}')
    report = run_golden_eval(
        golden,
        token="t",
        strip_reasoning=False,
        responder=lambda c: ("<think>hello</think>bye", 5, 1),
    )
    assert report.success_rate == 1.0 and report.reasoning_cases == 0


def test_default_call_reads_reasoning_content(tmp_path: Path):
    golden = _golden(tmp_path, '{"id":"a","messages":[],"expect_contains":["4"]}')

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "4", "reasoning_content": "two plus two"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"completion_tokens": 3, "prompt_tokens": 2},
            },
        )

    report = run_golden_eval(
        golden,
        token="t",
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    case = report.cases[0]
    assert case.ok and case.reasoning == "two plus two" and case.finish_reason == "stop"
