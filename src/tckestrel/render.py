"""Write per-job xrdhover workload JSON and PFN filelist."""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tckestrel.cache import PrefixCache
from tckestrel.config import Config
from tckestrel.plan import PlannedCell, build_plan
from tckestrel.resolve import ResolvedSlice, cache_file, resolve_cell
from tckestrel.rucio_backend import RucioBackend

FILELIST_NAME = "files.txt"
WORKLOAD_NAME = "job.json"
Validator = Callable[[Path, Path], None]


class RenderError(ValueError):
    """job.json / files.txt could not be written."""


@dataclass(frozen=True)
class RenderedJob:
    source: str
    dest: str
    rse: str
    endpoint: str
    job_id: str
    run_id: str
    job_json: Path
    files_txt: Path
    workload: dict[str, object]


def format_si_bit_rate(gbps: float) -> str:
    bits = gbps * 1e9
    if bits <= 0:
        raise RenderError("job_rate_gbps must be > 0")
    for unit, scale in (("Gbps", 1e9), ("Mbps", 1e6), ("kbps", 1e3)):
        value = bits / scale
        if value >= 1 and abs(value - round(value)) < 1e-6:
            return f"{int(round(value))}{unit}"
    return f"{int(round(bits))}bps"


def format_duration(seconds: int) -> str:
    if seconds < 1:
        raise RenderError("job_duration_s must be >= 1")
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def format_size(n: int) -> str:
    if n < 1:
        raise RenderError("max_bytes / chunk_bytes must be >= 1")
    for unit, scale in (
        ("GiB", 1024**3),
        ("GB", 10**9),
        ("MiB", 1024**2),
        ("MB", 10**6),
        ("KiB", 1024),
        ("KB", 10**3),
    ):
        if n >= scale and n % scale == 0:
            return f"{n // scale}{unit}"
    return str(n)


def run_id_for(campaign_id: str, source: str, dest: str) -> str:
    return f"{campaign_id}/{source}__{dest}"


def pattern_max_bytes(config: Config) -> int:
    if config.max_bytes > 0:
        return config.max_bytes
    return config.chunk_bytes


def default_out_dir(config: Config, source: str, dest: str, job_id: str) -> Path:
    if config.filelists_dir is None:
        raise RenderError("filelists_dir is required to render a job")
    return config.filelists_dir / ".tckestrel" / "jobs" / f"{source}__{dest}" / job_id


def find_planned_cell(config: Config, source: str, dest: str) -> PlannedCell:
    for row in build_plan(config):
        if row.source == source and row.dest == dest:
            if row.missing:
                raise RenderError(f"no links.csv row or sidecar for {source},{dest}")
            return row
    raise RenderError(f"no matrix cell {source},{dest}")


def build_workload(
    config: Config,
    cell: PlannedCell,
    resolved: ResolvedSlice,
    job_id: str,
) -> dict[str, object]:
    if not resolved.endpoint.startswith("root://"):
        raise RenderError(f"endpoint is not root:// : {resolved.endpoint}")
    rate = format_si_bit_rate(cell.job_rate_gbps)
    size = format_size(pattern_max_bytes(config))
    if size == "auto":
        raise RenderError("pattern.max_bytes must not be auto")
    name = f"{resolved.source}__{resolved.dest}"
    return {
        "schema_version": 1,
        "run_id": run_id_for(config.campaign_id, resolved.source, resolved.dest),
        "duration": format_duration(config.job_duration_s),
        "seed": 1,
        "auth": {"mode": "x509"},
        "targets": [
            {
                "name": name,
                "endpoint": resolved.endpoint,
                "filelist": FILELIST_NAME,
                "target_rate": rate,
                "max_inflight": 16,
                "pattern": {
                    "type": "sequential",
                    "read_size": "1MiB",
                    "max_bytes": size,
                },
            }
        ],
        "client_tuning": {
            "session_timeout": "60s",
            "connection_window": 15,
            "connection_retry": 2,
            "request_timeout": 60,
        },
        "sinks": {
            "results_dir": "results",
            "snapshot_interval": format_duration(config.snapshot_interval_s),
            "job_id": job_id,
            "write_results": True,
            "pushgateway": {
                "url": config.prom_url,
                "job": "xrdhover",
                "keep": False,
            },
        },
    }


def write_filelist(path: Path, resolved: ResolvedSlice) -> None:
    if not resolved.pfns:
        raise RenderError("resolved slice has no PFNs")
    lines = [pfn.path for pfn in resolved.pfns]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_workload(job_json: Path, binary: Path) -> None:
    try:
        proc = subprocess.run(
            [str(binary), "validate", str(job_json)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RenderError(f"xrdhover validate failed: {exc}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RenderError(f"xrdhover validate failed ({proc.returncode}): {err}")


def render_cell(
    config: Config,
    source: str,
    dest: str,
    *,
    limit: int = 3,
    job_id: str | None = None,
    out_dir: Path | None = None,
    backend: RucioBackend | None = None,
    cache: PrefixCache | None = None,
    site_map: Path | None = None,
    validate: Validator | None = None,
    xrdhover: Path | None = None,
) -> RenderedJob:
    cell = find_planned_cell(config, source, dest)
    store = cache if cache is not None else PrefixCache(cache_file(config))
    resolved = resolve_cell(
        config,
        source,
        dest,
        limit=limit,
        backend=backend,
        cache=store,
        site_map=site_map,
    )
    issued = job_id or uuid.uuid4().hex
    dest_dir = out_dir if out_dir is not None else default_out_dir(config, source, dest, issued)
    dest_dir.mkdir(parents=True, exist_ok=True)
    workload = build_workload(config, cell, resolved, issued)
    job_json = dest_dir / WORKLOAD_NAME
    files_txt = dest_dir / FILELIST_NAME
    write_filelist(files_txt, resolved)
    job_json.write_text(json.dumps(workload, indent=2) + "\n", encoding="utf-8")
    if validate is not None:
        if xrdhover is None:
            raise RenderError("xrdhover binary is required to validate")
        validate(job_json, xrdhover)
    return RenderedJob(
        source=resolved.source,
        dest=resolved.dest,
        rse=resolved.rse,
        endpoint=resolved.endpoint,
        job_id=issued,
        run_id=str(workload["run_id"]),
        job_json=job_json,
        files_txt=files_txt,
        workload=workload,
    )
