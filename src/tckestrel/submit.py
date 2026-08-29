"""Render a cell and submit one Condor job (or write a dry-run .sub)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tckestrel.cache import PrefixCache
from tckestrel.condor import (
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
from tckestrel.render import RenderError, RenderedJob, render_cell, validate_workload
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


def default_condor() -> CondorBackend:
    return LiveCondor()


def make_spec(
    config: Config,
    rendered: RenderedJob,
    executable: Path,
    *,
    any_site: bool = False,
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
        desired_sites="" if any_site else None,
    )


def submit_cell(
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
    condor: CondorBackend | None = None,
    payload: Payload | None = None,
    validate: bool = False,
    submit: bool = False,
    any_site: bool = False,
) -> SubmittedJob:
    try:
        binary = payload or ensure_payload(config, payload_arch_for_dest(dest))
        rendered = render_cell(
            config,
            source,
            dest,
            limit=limit,
            job_id=job_id,
            out_dir=out_dir,
            backend=backend,
            cache=cache if cache is not None else PrefixCache(cache_file(config)),
            site_map=site_map,
            validate=validate_workload if validate else None,
            xrdhover=binary.path if validate else None,
        )
        spec = make_spec(config, rendered, binary.path, any_site=any_site)
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
