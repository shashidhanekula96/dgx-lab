# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for dgxlab CLI."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from dgx_lab.cli import main


def test_cli_run_status_compare(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("DGX_LAB_ROOT", str(tmp_path))
    cfg = tmp_path / "exp.yaml"
    cfg.write_text(yaml.safe_dump({"name": "cli-exp", "serve": {"model_name": "m"}}), encoding="utf-8")

    assert main(["run", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "created run" in out
    run_id = out.split("created run", 1)[1].strip().splitlines()[0].strip()

    assert main(["status", run_id]) == 0
    status_out = capsys.readouterr().out
    payload = json.loads(status_out)
    assert payload["meta"]["run_id"] == run_id
    assert "host" in payload["meta"]
    assert "operator" in payload["meta"]

    cfg2 = tmp_path / "exp2.yaml"
    cfg2.write_text(yaml.safe_dump({"name": "cli-exp-2", "serve": {"model_name": "m"}}), encoding="utf-8")
    assert main(["run", str(cfg2)]) == 0
    run_id2 = capsys.readouterr().out.split("created run", 1)[1].strip().splitlines()[0].strip()

    assert main(["compare", run_id, run_id2]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["left"] == run_id
    assert "name" in diff["config_diff"]

    assert main(["rerun", run_id]) == 0
    assert "rerun of" in capsys.readouterr().out

    assert main(["status"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert len(listing["runs"]) >= 2


def test_cli_version():
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_cli_check_host(capsys):
    assert main(["check-host"]) == 0
    out = capsys.readouterr().out
    assert "HOST PROFILE: OK" in out or "os=" in out


def test_resolve_run_settings_strip_reasoning(tmp_path: Path):
    import argparse

    import pytest

    from dgx_lab.cli import CliError, resolve_run_settings

    args = argparse.Namespace()
    base = {"serve": {"model_name": "m"}}
    assert resolve_run_settings(base, args, config_origin=None).strip_reasoning is True

    off = {**base, "eval": {"strip_reasoning": False}}
    settings = resolve_run_settings(off, args, config_origin=None)
    assert settings.strip_reasoning is False
    assert settings.public()["strip_reasoning"] is False

    with pytest.raises(CliError, match="strip_reasoning"):
        resolve_run_settings({**base, "eval": {"strip_reasoning": "no"}}, args, config_origin=None)
