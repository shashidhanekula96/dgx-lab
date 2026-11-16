# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""``dgxlab`` CLI — run | rerun | compare | status | check-endpoint | init-config | credits | check-host."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from dgx_lab import API_TOKEN_ENV, AUTHOR, COPYRIGHT, __version__, credits
from dgx_lab.endpoint import EndpointError, validate_endpoint
from dgx_lab.evals import DEFAULT_MAX_TOKENS, list_models, run_golden_eval
from dgx_lab.host import check_host
from dgx_lab.kpis import evaluate_kpis, load_kpi_config
from dgx_lab.paths import bundled_default, data_root, ensure_data_layout, load_config, resolve_resource
from dgx_lab.tracking import (
    compare_runs,
    create_run,
    list_runs,
    load_run,
    update_run_status,
    write_json,
)

BASE_URL_ENV = "DGX_LAB_BASE_URL"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_S = 120.0
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CliError(Exception):
    """User-facing error: printed as one line, exit code 2."""


@dataclass
class RunSettings:
    """Resolved settings for executing a run. Never persisted with the token."""

    base_url: str
    model: str
    token: str
    no_auth: bool
    golden: Path
    kpi_config: Path
    timeout_s: float
    max_tokens: int
    temperature: float

    def public(self) -> dict[str, Any]:
        """Token-free view stored on the run record."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "auth": "none" if self.no_auth and not self.token else "bearer",
            "golden": str(self.golden),
            "kpi_config": str(self.kpi_config),
            "timeout_s": self.timeout_s,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }


def _section(cfg: dict[str, Any], key: str) -> dict[str, Any]:
    value = cfg.get(key)
    return value if isinstance(value, dict) else {}


def _resolve_token(args: argparse.Namespace, serve: dict[str, Any]) -> str:
    """--token > env var named by serve.api_key_env > DGX_LAB_API_TOKEN."""
    if getattr(args, "token", None):
        return str(args.token).strip()
    env_name = serve.get("api_key_env")
    if env_name:
        if not isinstance(env_name, str) or not ENV_NAME_RE.match(env_name):
            raise CliError(
                "serve.api_key_env must be the NAME of an environment variable "
                "(e.g. OPENAI_API_KEY), not the token itself"
            )
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return os.environ.get(API_TOKEN_ENV, "").strip()


def resolve_run_settings(
    cfg: dict[str, Any],
    args: argparse.Namespace,
    *,
    config_origin: Path | None,
) -> RunSettings:
    """Merge CLI flags > environment > experiment YAML > defaults."""
    serve = _section(cfg, "serve")
    model_cfg = _section(cfg, "model")
    resources = _section(cfg, "resources")

    base_url = (
        getattr(args, "base_url", None)
        or os.environ.get(BASE_URL_ENV, "").strip()
        or serve.get("base_url")
        or DEFAULT_BASE_URL
    )
    model = getattr(args, "model", None) or serve.get("model_name") or model_cfg.get("served_name")
    if not model:
        raise CliError("No model configured. Set serve.model_name in the experiment or pass --model")

    golden_value = getattr(args, "golden", None) or _section(cfg, "eval").get("golden")
    kpi_value = getattr(args, "kpi_config", None) or _section(cfg, "kpis").get("config")
    golden = (
        resolve_resource(golden_value, relative_to=config_origin)
        if golden_value
        else bundled_default("golden")
    )
    kpi_config = (
        resolve_resource(kpi_value, relative_to=config_origin) if kpi_value else bundled_default("kpis")
    )

    try:
        timeout_s = float(resources.get("timeout_s") or DEFAULT_TIMEOUT_S)
        max_tokens = int(serve.get("max_tokens") or DEFAULT_MAX_TOKENS)
        temperature = float(serve.get("temperature") or 0.0)
    except (TypeError, ValueError) as exc:
        raise CliError(f"Invalid numeric value in experiment config: {exc}") from exc

    return RunSettings(
        base_url=str(base_url),
        model=str(model),
        token=_resolve_token(args, serve),
        no_auth=bool(getattr(args, "no_auth", False)),
        golden=golden,
        kpi_config=kpi_config,
        timeout_s=timeout_s,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def cmd_run(args: argparse.Namespace) -> int:
    ensure_data_layout()
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        raise CliError(f"Experiment config not found: {args.config}")
    run_id, dest = create_run(config_path, extra_meta={"cli": "run"})
    print(f"created run {run_id}")
    print(f"  path: {dest}")
    if args.execute:
        return _execute_run(run_id, args)
    return 0


def cmd_rerun(args: argparse.Namespace) -> int:
    ensure_data_layout()
    prior = load_run(args.run_id)
    frozen_path = prior["path"] / "config.frozen.yaml"
    origin = prior["meta"].get("origin_config") or prior["meta"].get("source_config")
    run_id, dest = create_run(
        frozen_path,
        extra_meta={"cli": "rerun", "rerun_of": args.run_id, "origin_config": origin},
    )
    print(f"rerun of {args.run_id} -> {run_id}")
    print(f"  path: {dest}")
    if args.execute:
        return _execute_run(run_id, args)
    return 0


def _execute_run(run_id: str, args: argparse.Namespace) -> int:
    run = load_run(run_id)
    origin = run["meta"].get("origin_config") or run["meta"].get("source_config")
    try:
        settings = resolve_run_settings(run["config"], args, config_origin=Path(origin) if origin else None)
        endpoint = validate_endpoint(
            settings.base_url,
            token=settings.token,
            require_token=True,
            allow_no_auth=settings.no_auth,
        )
        update_run_status(run_id, "running", extra={"execution": settings.public()})
        report = run_golden_eval(
            settings.golden,
            base_url=endpoint.base_url,
            token=settings.token or None,
            model=settings.model,
            timeout=settings.timeout_s,
            temperature=settings.temperature,
            default_max_tokens=settings.max_tokens,
            allow_no_auth=settings.no_auth,
        )
        metrics = report.to_dict()
        kpi_report = evaluate_kpis(metrics, load_kpi_config(settings.kpi_config))
    except Exception as exc:
        # Never leave a run stuck in "running": record the failure, then surface it.
        update_run_status(run_id, "failed", notes=f"{type(exc).__name__}: {exc}")
        raise

    metrics["kpi"] = kpi_report.to_dict()
    write_json(run["path"] / "metrics.json", metrics)
    status = "passed" if kpi_report.ok else "failed_kpi"
    update_run_status(run_id, status, metrics=metrics)
    print(json.dumps({"run_id": run_id, "status": status, "kpi": kpi_report.to_dict()}, indent=2))

    failed = [c for c in metrics["cases"] if not c["ok"]]
    if failed:
        print(f"\n{len(failed)}/{metrics['n']} golden cases failed:", file=sys.stderr)
        for case in failed[:5]:
            print(f"  - {case['id']}: {'; '.join(case['errors'])[:200]}", file=sys.stderr)
        if len(failed) == metrics["n"]:
            print(
                "  hint: every case failed — run `dgxlab check-endpoint` to verify the "
                "URL, token and model name",
                file=sys.stderr,
            )
    return 0 if kpi_report.ok else 1


def cmd_check_endpoint(args: argparse.Namespace) -> int:
    """Connectivity + auth check: GET /v1/models and confirm the model exists."""
    cfg: dict[str, Any] = {}
    config_origin = None
    if args.config:
        config_origin = Path(args.config).expanduser().resolve()
        if not config_origin.is_file():
            raise CliError(f"Experiment config not found: {args.config}")
        cfg = load_config(config_origin)
    serve = _section(cfg, "serve")
    base_url = (
        args.base_url or os.environ.get(BASE_URL_ENV, "").strip() or serve.get("base_url") or DEFAULT_BASE_URL
    )
    token = _resolve_token(args, serve)
    endpoint = validate_endpoint(base_url, token=token, require_token=True, allow_no_auth=args.no_auth)
    auth = "bearer token" if token else "none"
    print(f"endpoint: {endpoint.api_url('models')}  (auth: {auth})")
    models = list_models(endpoint, token=token or None)
    print(f"reachable: yes — {len(models)} model(s) served")
    for model_id in models:
        print(f"  - {model_id}")
    wanted = args.model or serve.get("model_name")
    if wanted:
        if models and wanted not in models:
            print(f"WARNING: model {wanted!r} is not in the served list", file=sys.stderr)
            return 1
        print(f"model {wanted!r}: OK")
    return 0


def cmd_init_config(args: argparse.Namespace) -> int:
    """Write a starter experiment YAML the user can edit."""
    dest = Path(args.output).expanduser()
    if dest.exists() and not args.force:
        raise CliError(f"{dest} already exists (use --force to overwrite)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundled_default("experiment"), dest)
    print(f"wrote {dest}")
    print("next: edit serve.base_url / serve.model_name, then run")
    print(f"  dgxlab check-endpoint --config {dest}")
    print(f"  dgxlab run {dest} --execute")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    diff = compare_runs(args.left, args.right)
    print(json.dumps(diff, indent=2, default=str))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ensure_data_layout()
    if args.run_id:
        run = load_run(args.run_id)
        payload: dict[str, Any] = {
            "meta": run["meta"],
            "config_keys": sorted(run["config"].keys()),
            "path": str(run["path"]),
        }
        metrics_path = run["path"] / "metrics.json"
        if metrics_path.exists():
            payload["metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
        print(json.dumps(payload, indent=2, default=str))
        return 0
    runs = list_runs()
    print(json.dumps({"data_root": str(data_root()), "runs": runs}, indent=2, default=str))
    return 0


def cmd_credits(_args: argparse.Namespace) -> int:
    print(credits(), end="")
    return 0


def cmd_check_host(args: argparse.Namespace) -> int:
    report = check_host(
        probe_docker_gpu=bool(args.probe_docker_gpu),
        preferred_disk_gb=float(args.preferred_disk_gb),
    )
    print(report.summary())
    if args.json and report.profile is not None:
        print(json.dumps(report.profile.to_dict(), indent=2, default=str))
    return 0


def _add_endpoint_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--token", default=None, help=f"Bearer token (default: ${API_TOKEN_ENV})")
    p.add_argument(
        "--base-url",
        default=None,
        help=f"OpenAI-compatible base URL, with or without /v1 (default: ${BASE_URL_ENV}, "
        f"then serve.base_url, then {DEFAULT_BASE_URL})",
    )
    p.add_argument("--model", default=None, help="Model id (default: serve.model_name)")
    p.add_argument(
        "--no-auth",
        action="store_true",
        help="Allow a loopback server without a token (Ollama, LM Studio, llama.cpp). "
        "Rejected for remote endpoints.",
    )


def _add_eval_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--execute", action="store_true", help="Also run golden eval + KPI gates")
    _add_endpoint_args(p)
    p.add_argument("--kpi-config", type=Path, default=None, help="KPI YAML (default: kpis.config)")
    p.add_argument("--golden", type=Path, default=None, help="Golden JSONL (default: eval.golden)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dgxlab",
        description=(
            f"Config-as-code eval harness for OpenAI-compatible LLM endpoints ({AUTHOR}). {COPYRIGHT}."
        ),
    )
    parser.add_argument("--version", action="version", version=f"dgx-lab {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Freeze experiment config into a new run id")
    p_run.add_argument("config", type=Path, help="Experiment YAML path")
    _add_eval_args(p_run)
    p_run.set_defaults(func=cmd_run)

    p_rerun = sub.add_parser("rerun", help="Create a new run from a prior frozen config")
    p_rerun.add_argument("run_id")
    _add_eval_args(p_rerun)
    p_rerun.set_defaults(func=cmd_rerun)

    p_ep = sub.add_parser("check-endpoint", help="Verify URL, auth and model against GET /v1/models")
    p_ep.add_argument("--config", default=None, help="Read serve.* from this experiment YAML")
    _add_endpoint_args(p_ep)
    p_ep.set_defaults(func=cmd_check_endpoint)

    p_init = sub.add_parser("init-config", help="Write a starter experiment YAML")
    p_init.add_argument("-o", "--output", default="dgx-lab.yaml", help="Destination (default: dgx-lab.yaml)")
    p_init.add_argument("--force", action="store_true", help="Overwrite an existing file")
    p_init.set_defaults(func=cmd_init_config)

    p_cmp = sub.add_parser("compare", help="Diff two run configs and metrics")
    p_cmp.add_argument("left")
    p_cmp.add_argument("right")
    p_cmp.set_defaults(func=cmd_compare)

    p_st = sub.add_parser("status", help="Show run status or list runs")
    p_st.add_argument("run_id", nargs="?", default=None)
    p_st.set_defaults(func=cmd_status)

    p_cr = sub.add_parser("credits", help="Print author signature and license credits")
    p_cr.set_defaults(func=cmd_credits)

    p_host = sub.add_parser("check-host", help="Detect OS/arch/CPU/memory/GPU profile")
    p_host.add_argument(
        "--probe-docker-gpu",
        action="store_true",
        help="Run a Docker GPU probe (may pull an image)",
    )
    p_host.add_argument(
        "--preferred-disk-gb",
        type=float,
        default=0.0,
        help="Advisory free-disk preference in GiB (0 = report only)",
    )
    p_host.add_argument("--json", action="store_true", help="Also print JSON profile")
    p_host.set_defaults(func=cmd_check_host)

    return parser


# Errors we expect from bad input / unreachable servers: show one clean line.
_USER_ERRORS = (
    CliError,
    EndpointError,
    FileNotFoundError,
    ValueError,
    yaml.YAMLError,
    httpx.HTTPError,
    RuntimeError,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except _USER_ERRORS as exc:
        if isinstance(exc, httpx.ConnectError):
            print(f"error: could not connect to the endpoint ({exc})", file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        if os.environ.get("DGX_LAB_DEBUG") == "1":
            raise
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
