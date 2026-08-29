"""tckestrel command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pathlib import Path

from tckestrel.cache import PrefixCache
from tckestrel.campaign import CampaignError
from tckestrel.condor import CondorError, CondorJob, campaign_constraint
from tckestrel.config import ConfigError, load_config
from tckestrel.matrix import MatrixError
from tckestrel.payload import (
    DEFAULT_ARCH,
    Payload,
    PayloadError,
    ensure_payload,
    payload_arch_for_dest,
)
from tckestrel.plan import PlanError, PlannedCell, build_plan, has_missing
from tckestrel.render import RenderError, RenderedJob, render_cell, validate_workload
from tckestrel.resolve import (
    ResolveError,
    ResolvedSlice,
    cache_file,
    default_backend,
    parse_cell,
    resolve_cell,
)
from tckestrel.submit import SubmitError, SubmittedJob, default_condor, submit_cell

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


def format_resolve(result: ResolvedSlice) -> str:
    lines = [
        f"source    {result.source}",
        f"dest      {result.dest}",
        f"rse       {result.rse}",
        f"endpoint  {result.endpoint}",
        f"cache     {'hit' if result.cache_hit else 'miss'}",
        "",
    ]
    lines.extend(pfn.path for pfn in result.pfns)
    return "\n".join(lines)


def _cmd_resolve(
    config_path: str,
    cell: str,
    limit: int,
    site_map: str | None,
) -> int:
    try:
        config = load_config(config_path)
        source, dest = parse_cell(cell)
        result = resolve_cell(
            config,
            source,
            dest,
            limit=limit,
            backend=default_backend(),
            cache=PrefixCache(cache_file(config)),
            site_map=Path(site_map) if site_map else None,
        )
    except (ConfigError, MatrixError, CampaignError, PlanError, ResolveError) as exc:
        print(f"tckestrel resolve: {exc}", file=sys.stderr)
        return 1
    print(format_resolve(result))
    return 0


def format_payload(result: Payload) -> str:
    return "\n".join(
        [
            f"arch      {result.arch}",
            f"version   {result.version}",
            f"path      {result.path}",
            f"fetched   {'true' if result.fetched else 'false'}",
        ]
    )


def _cmd_payload(config_path: str, arch: str | None, dest: str | None) -> int:
    try:
        config = load_config(config_path)
        chosen = arch or (payload_arch_for_dest(dest) if dest else DEFAULT_ARCH)
        result = ensure_payload(config, chosen)
    except (ConfigError, PayloadError) as exc:
        print(f"tckestrel payload: {exc}", file=sys.stderr)
        return 1
    print(format_payload(result))
    return 0


def format_render(result: RenderedJob) -> str:
    return "\n".join(
        [
            f"source    {result.source}",
            f"dest      {result.dest}",
            f"rse       {result.rse}",
            f"endpoint  {result.endpoint}",
            f"run_id    {result.run_id}",
            f"job_id    {result.job_id}",
            f"job.json  {result.job_json}",
            f"files.txt {result.files_txt}",
        ]
    )


def _cmd_render(
    config_path: str,
    cell: str,
    limit: int,
    site_map: str | None,
    out: str | None,
    job_id: str | None,
    validate: bool,
) -> int:
    try:
        config = load_config(config_path)
        source, dest = parse_cell(cell)
        xrdhover = None
        validator = None
        if validate:
            xrdhover = ensure_payload(config, payload_arch_for_dest(dest)).path
            validator = validate_workload
        result = render_cell(
            config,
            source,
            dest,
            limit=limit,
            job_id=job_id,
            out_dir=Path(out) if out else None,
            backend=default_backend(),
            cache=PrefixCache(cache_file(config)),
            site_map=Path(site_map) if site_map else None,
            validate=validator,
            xrdhover=xrdhover,
        )
    except (
        ConfigError,
        MatrixError,
        CampaignError,
        PlanError,
        ResolveError,
        RenderError,
        PayloadError,
    ) as exc:
        print(f"tckestrel render: {exc}", file=sys.stderr)
        return 1
    print(format_render(result))
    return 0


def format_submit(result: SubmittedJob) -> str:
    lines = [
        f"source    {result.rendered.source}",
        f"dest      {result.rendered.dest}",
        f"run_id    {result.rendered.run_id}",
        f"job_id    {result.rendered.job_id}",
        f"executable {result.spec.executable}",
        f"job.sub   {result.submit_file}",
        f"job.json  {result.rendered.job_json}",
    ]
    if result.result is None:
        lines.append("submitted false")
    else:
        lines.append(f"submitted {result.result.cluster_proc}")
    return "\n".join(lines)


def _cmd_submit(
    config_path: str,
    cell: str,
    limit: int,
    site_map: str | None,
    out: str | None,
    job_id: str | None,
    validate: bool,
    do_submit: bool,
    pool: str | None,
    schedd: str | None,
) -> int:
    try:
        config = load_config(config_path)
        source, dest = parse_cell(cell)
        result = submit_cell(
            config,
            source,
            dest,
            limit=limit,
            job_id=job_id,
            out_dir=Path(out) if out else None,
            backend=default_backend(),
            cache=PrefixCache(cache_file(config)),
            site_map=Path(site_map) if site_map else None,
            condor=default_condor(config, pool=pool, schedd=schedd) if do_submit else None,
            validate=validate,
            submit=do_submit,
        )
    except (
        ConfigError,
        MatrixError,
        CampaignError,
        PlanError,
        ResolveError,
        RenderError,
        PayloadError,
        SubmitError,
        CondorError,
    ) as exc:
        print(f"tckestrel submit: {exc}", file=sys.stderr)
        return 1
    print(format_submit(result))
    return 0


def format_jobs(rows: list[CondorJob]) -> str:
    headers = ("cluster", "status", "source", "dest", "job_id")
    body = [
        [
            f"{row.cluster}.{row.proc}",
            row.status,
            row.source,
            row.dest,
            row.job_id,
        ]
        for row in rows
    ]
    widths = [len(h) for h in headers]
    for fields in body:
        for i, field in enumerate(fields):
            widths[i] = max(widths[i], len(field))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    for fields in body:
        lines.append("  ".join(fields[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def _cmd_jobs(
    config_path: str,
    cell: str | None,
    pool: str | None,
    schedd: str | None,
) -> int:
    try:
        config = load_config(config_path)
        source = dest = None
        if cell:
            source, dest = parse_cell(cell)
        rows = default_condor(config, pool=pool, schedd=schedd).query(
            config.campaign_id, source, dest
        )
    except (ConfigError, ResolveError, CondorError) as exc:
        print(f"tckestrel jobs: {exc}", file=sys.stderr)
        return 1
    print(format_jobs(rows))
    return 0


def _cmd_rm(
    config_path: str,
    cell: str | None,
    pool: str | None,
    schedd: str | None,
) -> int:
    try:
        config = load_config(config_path)
        source = dest = None
        if cell:
            source, dest = parse_cell(cell)
        removed = default_condor(config, pool=pool, schedd=schedd).remove(
            config.campaign_id, source, dest
        )
    except (ConfigError, ResolveError, CondorError) as exc:
        print(f"tckestrel rm: {exc}", file=sys.stderr)
        return 1
    print(f"removed {removed}  {campaign_constraint(config.campaign_id, source, dest)}")
    return 0


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
    resolve = sub.add_parser("resolve", help="stamp a cell's LFNs with root:// PFNs")
    resolve.add_argument("--config", required=True, help="path to controller YAML")
    resolve.add_argument("--cell", required=True, help="SOURCE,DEST")
    resolve.add_argument("--limit", type=int, default=3, help="LFNs to resolve (default 3)")
    resolve.add_argument("--site-map", dest="site_map", help="site_map.csv when the sidecar has no rse column")
    payload = sub.add_parser("payload", help="ensure the xrdhover release binary is on disk")
    payload.add_argument("--config", required=True, help="path to controller YAML")
    payload.add_argument("--arch", help="release arch (default linux-amd64)")
    payload.add_argument("--dest", help="CMS dest site; selects arch when --arch is omitted")
    render = sub.add_parser("render", help="write job.json and files.txt for a cell")
    render.add_argument("--config", required=True, help="path to controller YAML")
    render.add_argument("--cell", required=True, help="SOURCE,DEST")
    render.add_argument("--limit", type=int, default=3, help="LFNs to stamp (default 3)")
    render.add_argument("--site-map", dest="site_map", help="site_map.csv when the sidecar has no rse column")
    render.add_argument("--out", help="directory for job.json and files.txt")
    render.add_argument("--job-id", dest="job_id", help="sinks.job_id (default: new UUID)")
    render.add_argument(
        "--validate",
        action="store_true",
        help="run xrdhover validate on the written job.json",
    )
    submit = sub.add_parser("submit", help="write a Condor submit file; --submit to queue it")
    submit.add_argument("--config", required=True, help="path to controller YAML")
    submit.add_argument("--cell", required=True, help="SOURCE,DEST")
    submit.add_argument("--limit", type=int, default=3, help="LFNs to stamp (default 3)")
    submit.add_argument("--site-map", dest="site_map", help="site_map.csv when the sidecar has no rse column")
    submit.add_argument("--out", help="directory for job.json, files.txt, and job.sub")
    submit.add_argument("--job-id", dest="job_id", help="sinks.job_id (default: new UUID)")
    submit.add_argument("--validate", action="store_true", help="run xrdhover validate before submit")
    submit.add_argument(
        "--submit",
        action="store_true",
        dest="do_submit",
        help="contact the schedd (default is dry-run)",
    )
    submit.add_argument("--pool", help="HTCondor collector (condor_submit -pool)")
    submit.add_argument("--schedd", help="remote schedd name (optional; adds -remote)")
    jobs = sub.add_parser("jobs", help="query campaign jobs on the schedd")
    jobs.add_argument("--config", required=True, help="path to controller YAML")
    jobs.add_argument("--cell", help="SOURCE,DEST")
    jobs.add_argument("--pool", help="HTCondor collector")
    jobs.add_argument("--schedd", help="remote schedd name")
    rm = sub.add_parser("rm", help="condor_rm by campaign ClassAd")
    rm.add_argument("--config", required=True, help="path to controller YAML")
    rm.add_argument("--cell", help="SOURCE,DEST")
    rm.add_argument("--pool", help="HTCondor collector")
    rm.add_argument("--schedd", help="remote schedd name")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "plan":
        return _cmd_plan(args.config)
    if args.command == "resolve":
        return _cmd_resolve(args.config, args.cell, args.limit, args.site_map)
    if args.command == "payload":
        return _cmd_payload(args.config, args.arch, args.dest)
    if args.command == "render":
        return _cmd_render(
            args.config,
            args.cell,
            args.limit,
            args.site_map,
            args.out,
            args.job_id,
            args.validate,
        )
    if args.command == "submit":
        return _cmd_submit(
            args.config,
            args.cell,
            args.limit,
            args.site_map,
            args.out,
            args.job_id,
            args.validate,
            args.do_submit,
            args.pool,
            args.schedd,
        )
    if args.command == "jobs":
        return _cmd_jobs(args.config, args.cell, args.pool, args.schedd)
    if args.command == "rm":
        return _cmd_rm(args.config, args.cell, args.pool, args.schedd)
    parser.error(f"unknown command: {args.command}")
    return 2
