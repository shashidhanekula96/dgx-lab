# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for runtime admit / smoke / lock helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from dgx_lab.runtime import (
    AdmitError,
    assert_loopback_only,
    lock_runtime,
    parse_image_pin,
    require_vllm_image_env,
    smoke_chat,
)


def test_parse_image_pin_ok():
    digest = "sha256:" + ("a" * 64)
    ref, dig = parse_image_pin(f"vllm/vllm-openai@{digest}")
    assert ref == "vllm/vllm-openai"
    assert dig == digest


def test_parse_image_pin_rejects_tag():
    with pytest.raises(AdmitError):
        parse_image_pin("vllm/vllm-openai:latest")


def test_require_vllm_image_env():
    digest = "sha256:" + ("b" * 64)
    img = f"vllm/vllm-openai@{digest}"
    assert require_vllm_image_env({"VLLM_IMAGE": img}) == img
    with pytest.raises(AdmitError):
        require_vllm_image_env({})


def test_assert_loopback_only():
    assert_loopback_only("127.0.0.1")
    with pytest.raises(AdmitError):
        assert_loopback_only("0.0.0.0")


def test_smoke_rejects_plain_http_remote():
    with pytest.raises(AdmitError):
        smoke_chat(base_url="http://192.168.1.1:8000", token="x", bind_host="127.0.0.1")


def test_smoke_ok_mocked():
    class FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResp()

    with patch("dgx_lab.runtime.httpx.Client", FakeClient):
        result = smoke_chat(token="secret", bind_host="127.0.0.1")
    assert result["ok"] is True


def test_smoke_https_remote_mocked():
    class FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResp()

    with patch("dgx_lab.runtime.httpx.Client", FakeClient):
        result = smoke_chat(
            base_url="https://cluster.example/v1",
            token="secret",
            bind_host="127.0.0.1",
            allow_remote=True,
        )
    assert result["ok"] is True
    assert result["is_loopback"] is False


def test_lock_requires_smoke(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DGX_LAB_ROOT", str(tmp_path))
    records = tmp_path / "records"
    records.mkdir(parents=True)
    digest = "sha256:" + ("c" * 64)
    (records / "admit.latest.json").write_text(
        '{"image": "vllm/vllm-openai@%s", "digest": "%s"}' % (digest, digest),
        encoding="utf-8",
    )
    model = tmp_path / "models" / "qwen3-8b"
    model.mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AdmitError, match="smoke"):
        lock_runtime(root=tmp_path, model_dir=model, smoke_result={"ok": False})

    payload = lock_runtime(
        root=tmp_path,
        model_dir=model,
        smoke_result={"ok": True, "status_code": 200, "base_url": "http://127.0.0.1:8000"},
    )
    assert payload["locked"] is True
    assert payload["model_tree_sha256"]
    assert (records / "runtime.lock.json").exists()


def test_admit_image_mismatch(tmp_path: Path, monkeypatch):
    from dgx_lab.runtime import admit_candidate

    monkeypatch.setenv("DGX_LAB_ROOT", str(tmp_path))
    digest_a = "sha256:" + ("a" * 64)
    digest_b = "sha256:" + ("b" * 64)
    cfg = tmp_path / "cand.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "candidate": {"source": "test", "inspected_at": "2026-09-28"},
                "runtime": {"image": f"vllm/vllm-openai@{digest_a}"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AdmitError, match="does not match"):
        admit_candidate(
            cfg,
            env={"VLLM_IMAGE": f"vllm/vllm-openai@{digest_b}"},
            root=tmp_path,
        )


def test_admit_rejects_spark_requires_on_x86(tmp_path: Path, monkeypatch):
    from dgx_lab.runtime import admit_candidate

    monkeypatch.setenv("DGX_LAB_ROOT", str(tmp_path))
    digest = "sha256:" + ("d" * 64)
    cfg = tmp_path / "cand.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "candidate": {"source": "test", "inspected_at": "2026-09-28"},
                "requires": {"arch": ["aarch64", "arm64"], "nvidia": True},
                "runtime": {"image": f"vllm/vllm-openai@{digest}"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AdmitError, match="requires"):
        admit_candidate(
            cfg,
            env={"VLLM_IMAGE": f"vllm/vllm-openai@{digest}"},
            root=tmp_path,
        )
