# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""End-to-end and regression tests for connecting to user environments."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from dgx_lab.cli import main
from dgx_lab.endpoint import EndpointError, validate_endpoint
from dgx_lab.paths import bundled_default, resolve_resource

REPO_ROOT = Path(__file__).resolve().parents[1]
GOOD_ANSWER = 'hello 4 pong {"status": "ok", "value": 1}'


class _FakeOpenAI(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible server recording paths and auth headers."""

    seen: list[tuple[str, str, str | None]] = []
    required_token: str | None = None

    def _authorized(self) -> bool:
        if self.required_token is None:
            return True
        return self.headers.get("Authorization") == f"Bearer {self.required_token}"

    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        type(self).seen.append(("GET", self.path, self.headers.get("Authorization")))
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        if self.path == "/v1/models":
            return self._send(200, {"data": [{"id": "test-model"}]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        type(self).seen.append(("POST", self.path, self.headers.get("Authorization")))
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": "not found"})
        return self._send(
            200,
            {
                "choices": [{"message": {"content": GOOD_ANSWER}}],
                "usage": {"completion_tokens": 8, "prompt_tokens": 4},
            },
        )

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture()
def fake_server():
    _FakeOpenAI.seen = []
    _FakeOpenAI.required_token = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def lab_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "lab"
    monkeypatch.setenv("DGX_LAB_ROOT", str(root))
    monkeypatch.delenv("DGX_LAB_API_TOKEN", raising=False)
    monkeypatch.delenv("DGX_LAB_BASE_URL", raising=False)
    return root


def _experiment(tmp_path: Path, **serve) -> Path:
    cfg = tmp_path / "exp.yaml"
    cfg.write_text(
        yaml.safe_dump({"name": "e2e", "serve": {"model_name": "test-model", **serve}}),
        encoding="utf-8",
    )
    return cfg


def _last_meta(root: Path) -> dict:
    runs = sorted((root / "records" / "runs").iterdir())
    return json.loads((runs[-1] / "meta.json").read_text(encoding="utf-8"))


# --- URL handling -----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8000/",
        "http://127.0.0.1:8000/v1",
        "http://127.0.0.1:8000/v1/",
        "http://127.0.0.1:8000/v1/chat/completions",
    ],
)
def test_base_url_with_or_without_v1(url):
    ep = validate_endpoint(url, token="t")
    assert ep.api_url("chat/completions") == "http://127.0.0.1:8000/v1/chat/completions"


def test_gateway_path_prefix_is_kept():
    ep = validate_endpoint("https://gw.example/openai/v1", token="t")
    assert ep.api_url("models") == "https://gw.example/openai/v1/models"


def test_rejects_token_in_query_but_allows_api_version():
    with pytest.raises(EndpointError, match="query"):
        validate_endpoint("https://gw.example/v1?api_key=abc", token="t")
    ep = validate_endpoint("https://gw.example/v1?api-version=2024-10-21", token="t")
    assert ep.api_url("chat/completions").endswith("/v1/chat/completions?api-version=2024-10-21")


def test_whole_127_range_is_loopback():
    assert validate_endpoint("http://127.0.0.2:8000", token="t").is_loopback


def test_no_auth_only_for_loopback():
    ep = validate_endpoint("http://localhost:11434", token="", allow_no_auth=True)
    assert ep.is_loopback and not ep.auth
    with pytest.raises(EndpointError, match="only allowed for loopback"):
        validate_endpoint("https://gw.example/v1", token="", allow_no_auth=True)
    with pytest.raises(EndpointError, match="--no-auth"):
        validate_endpoint("http://127.0.0.1:11434", token="")


# --- End-to-end against a real HTTP server -----------------------------------


def test_e2e_no_auth_local_server(fake_server, lab_root, tmp_path, capsys):
    _, url = fake_server
    cfg = _experiment(tmp_path)
    code = main(["run", str(cfg), "--execute", "--no-auth", "--base-url", f"{url}/v1"])
    assert code == 0, capsys.readouterr().err
    posts = [s for s in _FakeOpenAI.seen if s[0] == "POST"]
    assert posts and all(p[1] == "/v1/chat/completions" for p in posts)  # no /v1/v1
    assert all(p[2] is None for p in posts)  # no Authorization header sent
    meta = _last_meta(lab_root)
    assert meta["status"] == "passed"
    assert meta["execution"]["auth"] == "none"


def test_e2e_token_from_env_and_base_url_from_yaml(fake_server, lab_root, tmp_path, monkeypatch, capsys):
    _, url = fake_server
    _FakeOpenAI.required_token = "s3cret-token"
    monkeypatch.setenv("DGX_LAB_API_TOKEN", "s3cret-token")
    cfg = _experiment(tmp_path, base_url=url)  # no --base-url flag: YAML must be used
    assert main(["run", str(cfg), "--execute"]) == 0, capsys.readouterr().err
    assert all(s[2] == "Bearer s3cret-token" for s in _FakeOpenAI.seen)
    run_dir = sorted((lab_root / "records" / "runs").iterdir())[-1]
    for f in run_dir.iterdir():
        assert "s3cret-token" not in f.read_text(encoding="utf-8"), f"token leaked into {f.name}"


def test_e2e_api_key_env(fake_server, lab_root, tmp_path, monkeypatch, capsys):
    _, url = fake_server
    _FakeOpenAI.required_token = "from-custom-env"
    monkeypatch.setenv("MY_GATEWAY_KEY", "from-custom-env")
    cfg = _experiment(tmp_path, base_url=url, api_key_env="MY_GATEWAY_KEY")
    assert main(["run", str(cfg), "--execute"]) == 0, capsys.readouterr().err


def test_env_base_url_overrides_yaml(fake_server, lab_root, tmp_path, monkeypatch, capsys):
    _, url = fake_server
    monkeypatch.setenv("DGX_LAB_BASE_URL", url)
    cfg = _experiment(tmp_path, base_url="http://127.0.0.1:1")  # would fail if used
    assert main(["run", str(cfg), "--execute", "--no-auth"]) == 0, capsys.readouterr().err


def test_check_endpoint_lists_models(fake_server, lab_root, capsys):
    _, url = fake_server
    assert main(["check-endpoint", "--base-url", url, "--no-auth", "--model", "test-model"]) == 0
    out = capsys.readouterr().out
    assert "test-model" in out and "OK" in out
    assert main(["check-endpoint", "--base-url", url, "--no-auth", "--model", "missing"]) == 1


def test_check_endpoint_reports_bad_token(fake_server, lab_root, capsys):
    _, url = fake_server
    _FakeOpenAI.required_token = "right"
    assert main(["check-endpoint", "--base-url", url, "--token", "wrong"]) == 2
    assert "401" in capsys.readouterr().err


# --- Failure handling ---------------------------------------------------------


def test_failed_run_is_not_left_running(lab_root, tmp_path, capsys):
    cfg = tmp_path / "exp.yaml"
    cfg.write_text(
        yaml.safe_dump({"name": "x", "serve": {"model_name": "m"}, "eval": {"golden": "nope.jsonl"}}),
        encoding="utf-8",
    )
    assert main(["run", str(cfg), "--execute", "--no-auth"]) == 2
    assert "nope.jsonl" in capsys.readouterr().err
    assert _last_meta(lab_root)["status"] == "failed"


def test_unreachable_server_is_clean_error(lab_root, tmp_path, capsys):
    cfg = _experiment(tmp_path, base_url="http://127.0.0.1:1")
    assert main(["run", str(cfg), "--execute", "--no-auth"]) == 1  # KPI gates fail
    err = capsys.readouterr().err
    assert "check-endpoint" in err
    assert "Traceback" not in err


def test_bad_run_id_is_clean_error(lab_root, capsys):
    assert main(["status", "nope"]) == 2
    assert "Invalid run id" in capsys.readouterr().err


def test_inline_secret_in_config_is_refused(lab_root, tmp_path, capsys):
    cfg = tmp_path / "exp.yaml"
    cfg.write_text(yaml.safe_dump({"name": "x", "serve": {"token": "sk-live-123"}}), encoding="utf-8")
    assert main(["run", str(cfg)]) == 2
    assert "serve.token" in capsys.readouterr().err
    assert not (lab_root / "records" / "runs").exists() or not any((lab_root / "records" / "runs").iterdir())


def test_api_key_env_must_be_a_name(lab_root, tmp_path, capsys):
    cfg = _experiment(tmp_path, api_key_env="sk-not-a-name")
    assert main(["run", str(cfg), "--execute"]) == 2
    assert "NAME of an environment variable" in capsys.readouterr().err


# --- Packaged defaults ------------------------------------------------------------


def test_bundled_defaults_exist():
    for kind in ("golden", "kpis", "experiment"):
        assert bundled_default(kind).is_file()


def test_resolve_resource_from_config_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not the repo root
    cfg = REPO_ROOT / "configs" / "experiments" / "baseline-qwen3-8b.yaml"
    assert resolve_resource("evals/golden/smoke.jsonl", relative_to=cfg).is_file()


def test_init_config_roundtrip(lab_root, tmp_path, fake_server, capsys):
    _, url = fake_server
    dest = tmp_path / "mine.yaml"
    assert main(["init-config", "-o", str(dest)]) == 0
    assert main(["init-config", "-o", str(dest)]) == 2  # refuses overwrite
    data = yaml.safe_load(dest.read_text(encoding="utf-8"))
    data["serve"].update(base_url=url, model_name="test-model")
    dest.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert main(["run", str(dest), "--execute", "--no-auth"]) == 0, capsys.readouterr().err


# --- Shell helper -------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="bash helper")
@pytest.mark.parametrize("host", ["1", ":"])
def test_phase1_serve_rejects_glob_lookalike_bind(host, tmp_path):
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "VLLM_IMAGE": "x@sha256:" + "a" * 64,
        "DGX_LAB_API_TOKEN": "t",
        "SERVE_BIND_HOST": host,
    }
    proc = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "phase1"), "serve"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "Refusing to publish" in proc.stderr
