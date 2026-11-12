# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for golden eval scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from dgx_lab.endpoint import EndpointError
from dgx_lab.evals import EvalCase, load_golden_jsonl, run_golden_eval, score_text


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
