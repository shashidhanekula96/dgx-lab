# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""``dgxlab`` CLI — run | rerun | compare | status | credits | check-host."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dgx_lab import API_TOKEN_ENV, AUTHOR, COPYRIGHT, __version__, credits
from dgx_lab.endpoint import EndpointError, validate_endpoint
from dgx_lab.evals import run_golden_eval
from dgx_lab.host import check_host
from dgx_lab.kpis import evaluate_kpis, load_kpi_config
from dgx_lab.paths import data_root, ensure_data_layout
from dgx_lab.tracking import (
    compare_runs,
    create_run,
    list_runs,
    load_run,
    update_run_status,
    write_json,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cmd_run(args: argparse.Namespace) -> int:
    ensure_data_layout()
    config_path = Path(args.config).resolve()
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
    run_id, dest = create_run(
        frozen_path,
        extra_meta={"cli": "rerun", "rerun_of": args.run_id},
    )
    print(f"rerun of {args.run_id} -> {run_id}")
    print(f"  path: {dest}")
    if args.execute:
        ns = argparse.Namespace(
            run_id=run_id,
            token=args.token,
            base_url=args.base_url,
            kpi_config=args.kpi_config,
            golden=args.golden,
        )
        return _execute_run(run_id, ns)
    return 0


def _execute_run(run_id: str, args: argparse.Namespace) -> int:
    run = load_run(run_id)
    cfg = run["config"]
    model = ((cfg.get("serve") or {}).get("model_name")) or (
        (cfg.get("model") or {}).get("served_name")
    ) or "qwen3-8b"
    golden = Path(args.golden) if getattr(args, "golden", None) else None
    if golden is None:
        golden = _repo_root() / "evals" / "golden" / "smoke.jsonl"
    kpi_path = Path(args.kpi_config) if getattr(args, "kpi_config", None) else (
        _repo_root() / "configs" / "kpis" / "default.yaml"
    )
    token = getattr(args, "token", None) or os.environ.get(API_TOKEN_ENV, "")
    base_url = getattr(args, "base_url", None) or "http://127.0.0.1:8000"
    try:
        endpoint = validate_endpoint(base_url, token=token, require_token=True)
    except EndpointError as exc:
        print(str(exc), file=sys.stderr)
        update_run_status(run_id, "failed", notes=str(exc))
        return 2

    update_run_status(run_id, "running")
    report = run_golden_eval(
        golden,
        base_url=endpoint.base_url,
        token=token,
        model=model,
    )
    metrics = report.to_dict()
    kpi_cfg = load_kpi_config(kpi_path)
    kpi_report = evaluate_kpis(metrics, kpi_cfg)
    metrics["kpi"] = kpi_report.to_dict()
    write_json(run["path"] / "metrics.json", metrics)
    status = "passed" if kpi_report.ok else "failed_kpi"
    update_run_status(run_id, status, metrics=metrics)
    print(json.dumps({"run_id": run_id, "status": status, "kpi": kpi_report.to_dict()}, indent=2))
    return 0 if kpi_report.ok else 1


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dgxlab",
        description=(
            f"Multi-OS config-as-code lab CLI ({AUTHOR}). "
            f"{COPYRIGHT}."
        ),
    )
    parser.add_argument("--version", action="version", version=f"dgx-lab {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Freeze experiment config into a new run id")
    p_run.add_argument("config", type=Path, help="Experiment YAML path")
    p_run.add_argument("--execute", action="store_true", help="Also run golden eval + KPI gates")
    p_run.add_argument("--token", default=None, help="Bearer token (or DGX_LAB_API_TOKEN)")
    p_run.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="OpenAI-compatible base URL (loopback http or remote https)",
    )
    p_run.add_argument("--kpi-config", type=Path, default=None)
    p_run.add_argument("--golden", type=Path, default=None)
    p_run.set_defaults(func=cmd_run)

    p_rerun = sub.add_parser("rerun", help="Create a new run from a prior frozen config")
    p_rerun.add_argument("run_id")
    p_rerun.add_argument("--execute", action="store_true")
    p_rerun.add_argument("--token", default=None)
    p_rerun.add_argument("--base-url", default="http://127.0.0.1:8000")
    p_rerun.add_argument("--kpi-config", type=Path, default=None)
    p_rerun.add_argument("--golden", type=Path, default=None)
    p_rerun.set_defaults(func=cmd_rerun)

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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
