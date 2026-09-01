"""tckestrel command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pathlib import Path

from tckestrel.cache import PrefixCache
from tckestrel.campaign import CampaignError
from tckestrel.condor import LOG_DIR, CondorError, CondorJob, campaign_constraint
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
from tckestrel.render import RenderError, RenderedJob, link_id, render_cell, validate_workload
from tckestrel.resolve import (
    ResolveError,
    ResolvedSlice,
    cache_file,
    default_backend,
    resolve_plan,
)
from tckestrel.submit import SubmitError, SubmittedJob, default_condor, submit_plan

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
    site_map: str | None,
) -> int:
    try:
        config = load_config(config_path)
        results = resolve_plan(
            config,
            backend=default_backend(),
            cache=PrefixCache(cache_file(config)),
            site_map=Path(site_map) if site_map else None,
        )
    except (ConfigError, MatrixError, CampaignError, PlanError, ResolveError) as exc:
        print(f"tckestrel resolve: {exc}", file=sys.stderr)
        return 1
    print("\n\n".join(format_resolve(result) for result in results))
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


def _cmd_payload(config_path: str, arch: str | None) -> int:
    try:
        config = load_config(config_path)
        result = ensure_payload(config, arch or DEFAULT_ARCH)
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
    site_map: str | None,
    out: str | None,
    job_id: str | None,
    validate: bool,
) -> int:
    try:
        config = load_config(config_path)
        rows = build_plan(config)
        if not rows:
            raise RenderError("plan has no cells to render")
        missing = [f"{row.source},{row.dest}" for row in rows if row.missing]
        if missing:
            raise RenderError(f"no links.csv row or sidecar for {', '.join(missing)}")
        xrdhover = None
        validator = None
        if validate:
            xrdhover = ensure_payload(config, payload_arch_for_dest(rows[0].dest)).path
            validator = validate_workload
        single = len(rows) == 1 and rows[0].n_jobs == 1
        results = []
        for row in rows:
            for index in range(row.n_jobs):
                if row.n_jobs == 1:
                    issued = job_id if single else None
                else:
                    issued = f"{link_id(row.source, row.dest)}__{index}"
                results.append(
                    render_cell(
                        config,
                        row.source,
                        row.dest,
                        job_id=issued,
                        out_dir=Path(out) if out and single else None,
                        backend=default_backend(),
                        cache=PrefixCache(cache_file(config)),
                        site_map=Path(site_map) if site_map else None,
                        validate=validator,
                        xrdhover=xrdhover,
                    )
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
    print("\n\n".join(format_render(result) for result in results))
    return 0


def format_submit(result: SubmittedJob) -> str:
    lines = [
        f"source    {result.rendered.source}",
        f"dest      {result.rendered.dest}",
        f"run_id    {result.rendered.run_id}",
        f"job_id    {result.rendered.job_id}",
        f"executable {result.spec.executable}",
        f"cmssw     {result.spec.cmssw}",
        f"job.sub   {result.submit_file}",
        f"job.json  {result.rendered.job_json}",
        f"logs      {result.spec.job_dir / LOG_DIR}",
    ]
    if result.spec.event_log is not None:
        lines.append(f"event_log {result.spec.event_log}")
    if result.result is None:
        lines.append("submitted false")
    else:
        lines.append(f"submitted {result.result.cluster_proc}")
    return "\n".join(lines)


def _cmd_submit(
    config_path: str,
    site_map: str | None,
    out: str | None,
    job_id: str | None,
    validate: bool,
    dry_run: bool,
    pool: str | None,
    schedd: str | None,
) -> int:
    do_submit = not dry_run
    try:
        config = load_config(config_path)
        jobs = submit_plan(
            config,
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
    print("\n".join(format_submit(job) for job in jobs))
    queued = sum(1 for job in jobs if job.result is not None)
    print(f"queued {queued}  written {len(jobs)}")
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
    pool: str | None,
    schedd: str | None,
) -> int:
    try:
        config = load_config(config_path)
        rows = default_condor(config, pool=pool, schedd=schedd).query(config.campaign_id)
    except (ConfigError, CondorError) as exc:
        print(f"tckestrel jobs: {exc}", file=sys.stderr)
        return 1
    print(format_jobs(rows))
    return 0


def _cmd_rm(
    config_path: str,
    pool: str | None,
    schedd: str | None,
) -> int:
    try:
        config = load_config(config_path)
        removed = default_condor(config, pool=pool, schedd=schedd).remove(config.campaign_id)
    except (ConfigError, CondorError) as exc:
        print(f"tckestrel rm: {exc}", file=sys.stderr)
        return 1
    print(f"removed {removed}  {campaign_constraint(config.campaign_id)}")
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
    parser = argparse.ArgumentParser(
        prog="tckestrel",
        description="Fleet controller for xrdhover WAN-hold jobs on HTCondor.",
        epilog=(
            "Workflow: plan → payload → resolve → render → submit → jobs / rm. "
            "submit already resolves and renders; resolve/render are preflight. "
            "The matrix selects cells. YAML holds pool/schedd/site_map."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    config = argparse.ArgumentParser(add_help=False)
    config.add_argument("-c", "--config", required=True, help="controller YAML")

    site_map = argparse.ArgumentParser(add_help=False)
    site_map.add_argument(
        "--site-map",
        dest="site_map",
        help="site_map.csv if the sidecar has no rse column (else YAML / filelists_dir)",
    )

    condor = argparse.ArgumentParser(add_help=False)
    condor.add_argument("--pool", help="collector (-pool); default YAML submit.condor_pool")
    condor.add_argument(
        "--schedd", help="remote schedd (-remote); default YAML submit.condor_schedd"
    )

    job_files = argparse.ArgumentParser(add_help=False)
    job_files.add_argument(
        "--out",
        help="write job files here (single-cell N=1 plan only; default under filelists_dir)",
    )
    job_files.add_argument(
        "--job-id",
        dest="job_id",
        help="sinks.job_id / Pushgateway replica (single-cell N=1 only; default SOURCE__DEST)",
    )
    job_files.add_argument(
        "--validate",
        action="store_true",
        help="run xrdhover validate on job.json",
    )

    sub.add_parser(
        "plan",
        parents=[config],
        help="print cells, N, job rate, and file counts",
    )
    sub.add_parser(
        "resolve",
        parents=[config, site_map],
        help="stamp planned LFNs with root:// PFNs",
    )
    payload = sub.add_parser(
        "payload",
        parents=[config],
        help="fetch the xrdhover release binary if missing",
    )
    payload.add_argument("--arch", default=DEFAULT_ARCH, help=f"release arch (default {DEFAULT_ARCH})")
    sub.add_parser(
        "render",
        parents=[config, site_map, job_files],
        help="write job.json and files.txt for every planned cell",
    )
    submit = sub.add_parser(
        "submit",
        parents=[config, site_map, job_files, condor],
        help="queue N jobs per cell (resolves and renders first)",
    )
    submit.add_argument(
        "--dry-run",
        action="store_true",
        help="write job.sub without contacting the schedd",
    )
    sub.add_parser(
        "jobs",
        parents=[config, condor],
        help="query campaign jobs on the schedd",
    )
    sub.add_parser(
        "rm",
        parents=[config, condor],
        help="condor_rm the campaign",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "plan":
        return _cmd_plan(args.config)
    if args.command == "resolve":
        return _cmd_resolve(args.config, args.site_map)
    if args.command == "payload":
        return _cmd_payload(args.config, args.arch)
    if args.command == "render":
        return _cmd_render(
            args.config,
            args.site_map,
            args.out,
            args.job_id,
            args.validate,
        )
    if args.command == "submit":
        return _cmd_submit(
            args.config,
            args.site_map,
            args.out,
            args.job_id,
            args.validate,
            args.dry_run,
            args.pool,
            args.schedd,
        )
    if args.command == "jobs":
        return _cmd_jobs(args.config, args.pool, args.schedd)
    if args.command == "rm":
        return _cmd_rm(args.config, args.pool, args.schedd)
    parser.error(f"unknown command: {args.command}")
    return 2
