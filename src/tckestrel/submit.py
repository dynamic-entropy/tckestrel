"""Render cells and submit Condor jobs (or write dry-run .sub files)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tckestrel.cache import PrefixCache
from tckestrel.condor import (
    LOG_DIR,
    WRAPPER_NAME,
    CondorBackend,
    CondorError,
    LiveCondor,
    SubmitResult,
    SubmitSpec,
    proxy_path,
    submit_text,
)
from tckestrel.config import Config
from tckestrel.payload import Payload, PayloadError, ensure_payload, payload_arch_for_dest
from tckestrel.plan import build_plan
from tckestrel.render import RenderError, RenderedJob, link_id, render_cell, validate_workload
from tckestrel.resolve import ResolveError, cache_file
from tckestrel.rucio_backend import RucioBackend


class SubmitError(RuntimeError):
    """Job could not be rendered or submitted."""


@dataclass(frozen=True)
class SubmittedJob:
    rendered: RenderedJob
    spec: SubmitSpec
    submit_file: Path
    payload: Payload
    result: SubmitResult | None


def default_condor(
    config: Config | None = None,
    pool: str | None = None,
    schedd: str | None = None,
) -> CondorBackend:
    chosen_pool = pool or (config.condor_pool if config else None)
    chosen_schedd = schedd or (config.condor_schedd if config else None)
    return LiveCondor(pool=chosen_pool, schedd=chosen_schedd)


def packaged_wrapper() -> Path:
    return Path(__file__).resolve().parent / WRAPPER_NAME


def install_wrapper(job_dir: Path) -> Path:
    dest = job_dir / WRAPPER_NAME
    dest.write_bytes(packaged_wrapper().read_bytes())
    dest.chmod(0o755)
    return dest


def make_spec(
    config: Config,
    rendered: RenderedJob,
    executable: Path,
    payload: Path,
) -> SubmitSpec:
    return SubmitSpec(
        executable=executable.resolve(),
        job_dir=rendered.job_json.parent.resolve(),
        dest=rendered.dest,
        campaign_id=config.campaign_id,
        source=rendered.source,
        run_id=rendered.run_id,
        job_id=rendered.job_id,
        proxy=proxy_path(),
        required_os=config.required_os,
        request_cpus=config.request_cpus,
        request_memory_mb=config.request_memory_mb,
        request_disk_mb=config.request_disk_mb,
        event_log=(
            config.filelists_dir / ".tckestrel" / "condor.log"
            if config.filelists_dir is not None
            else None
        ),
        payload=payload.resolve(),
        cmssw=config.cmssw,
        keep_claim_idle_s=config.keep_claim_idle_s,
    )


def submit_cell(
    config: Config,
    source: str,
    dest: str,
    *,
    job_id: str | None = None,
    out_dir: Path | None = None,
    backend: RucioBackend | None = None,
    cache: PrefixCache | None = None,
    site_map: Path | None = None,
    condor: CondorBackend | None = None,
    payload: Payload | None = None,
    validate: bool = False,
    submit: bool = False,
) -> SubmittedJob:
    try:
        binary = payload or ensure_payload(config, payload_arch_for_dest(dest))
        rendered = render_cell(
            config,
            source,
            dest,
            job_id=job_id,
            out_dir=out_dir,
            backend=backend,
            cache=cache if cache is not None else PrefixCache(cache_file(config)),
            site_map=site_map,
            validate=validate_workload if validate else None,
            xrdhover=binary.path if validate else None,
        )
        wrapper = install_wrapper(rendered.job_json.parent)
        spec = make_spec(config, rendered, wrapper, binary.path)
        (spec.job_dir / LOG_DIR).mkdir(parents=True, exist_ok=True)
        if spec.event_log is not None:
            spec.event_log.parent.mkdir(parents=True, exist_ok=True)
        submit_file = rendered.job_json.parent / "job.sub"
        submit_file.write_text(submit_text(spec), encoding="utf-8")
        result = None
        if submit:
            client = condor if condor is not None else default_condor()
            result = client.submit(spec)
    except (CondorError, SubmitError, RenderError, PayloadError, ResolveError):
        raise
    except Exception as exc:
        raise SubmitError(str(exc)) from exc
    return SubmittedJob(
        rendered=rendered,
        spec=spec,
        submit_file=submit_file,
        payload=binary,
        result=result,
    )


def submit_plan(
    config: Config,
    *,
    job_id: str | None = None,
    out_dir: Path | None = None,
    backend: RucioBackend | None = None,
    cache: PrefixCache | None = None,
    site_map: Path | None = None,
    condor: CondorBackend | None = None,
    payload: Payload | None = None,
    validate: bool = False,
    submit: bool = False,
) -> list[SubmittedJob]:
    """Submit ``N`` jobs per matrix cell. Each holds ``job_rate_gbps = R / N``.

    The matrix is the cell selector. ``--job-id`` / ``--out`` apply only when
    the plan is a single cell with ``N = 1``.
    """
    store = cache if cache is not None else PrefixCache(cache_file(config))
    rows = build_plan(config)
    if not rows:
        raise SubmitError("plan has no cells to submit")
    missing = [f"{row.source},{row.dest}" for row in rows if row.missing]
    if missing:
        raise SubmitError(f"no links.csv row or sidecar for {', '.join(missing)}")

    binary = payload or ensure_payload(config, payload_arch_for_dest(rows[0].dest))
    single = len(rows) == 1 and rows[0].n_jobs == 1
    jobs: list[SubmittedJob] = []
    for row in rows:
        for index in range(row.n_jobs):
            if row.n_jobs == 1:
                issued = job_id if single else None
            else:
                # Distinct sinks.job_id → Pushgateway replica. Same run_id/src_dst
                # for the cell. Do not reuse one job_id across N or they clobber.
                issued = f"{link_id(row.source, row.dest)}__{index}"
            jobs.append(
                submit_cell(
                    config,
                    row.source,
                    row.dest,
                    job_id=issued,
                    out_dir=out_dir if single else None,
                    backend=backend,
                    cache=store,
                    site_map=site_map,
                    condor=condor,
                    payload=binary,
                    validate=validate,
                    submit=submit,
                )
            )
    return jobs
