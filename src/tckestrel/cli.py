"""tckestrel command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tckestrel.campaign import CampaignError
from tckestrel.config import ConfigError, load_config
from tckestrel.matrix import MatrixError
from tckestrel.plan import PlanError, PlannedCell, build_plan, has_missing

HEADERS = (
    "source",
    "dest",
    "rate_gbps",
    "N",
    "job_rate_gbps",
    "rse",
    "n_files",
    "shortfall",
)


def _cell_fields(row: PlannedCell) -> list[str]:
    if row.missing:
        rse = "MISSING"
        n_files = ""
        shortfall = "MISSING"
    else:
        rse = row.rse or ""
        n_files = "" if row.n_files is None else str(row.n_files)
        if row.shortfall is None:
            shortfall = ""
        else:
            shortfall = "true" if row.shortfall else "false"
    return [
        row.source,
        row.dest,
        f"{row.rate_gbps:.12g}",
        str(row.n_jobs),
        f"{row.job_rate_gbps:.12g}",
        rse,
        n_files,
        shortfall,
    ]


def format_table(rows: list[PlannedCell]) -> str:
    body = [_cell_fields(row) for row in rows]
    widths = [len(h) for h in HEADERS]
    for fields in body:
        for i, field in enumerate(fields):
            widths[i] = max(widths[i], len(field))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(HEADERS))]
    for fields in body:
        lines.append("  ".join(fields[i].ljust(widths[i]) for i in range(len(HEADERS))))
    return "\n".join(lines)


def _cmd_plan(config_path: str) -> int:
    try:
        config = load_config(config_path)
        rows = build_plan(config)
    except (ConfigError, MatrixError, CampaignError, PlanError) as exc:
        print(f"tckestrel plan: {exc}", file=sys.stderr)
        return 1
    print(format_table(rows))
    if has_missing(rows):
        print(
            "tckestrel plan: one or more cells have no links.csv row or sidecar",
            file=sys.stderr,
        )
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tckestrel")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="print cells, N, job rate, and file counts")
    plan.add_argument("--config", required=True, help="path to controller YAML")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "plan":
        return _cmd_plan(args.config)
    parser.error(f"unknown command: {args.command}")
    return 2
