"""Build the per-cell plan: N, job rate, and optional Spark join."""

from __future__ import annotations

import math
from dataclasses import dataclass

from tckestrel.campaign import CampaignError, Link, load_links, sidecar_exists
from tckestrel.config import Config
from tckestrel.matrix import Cell, load_cells


class PlanError(ValueError):
    """Plan could not be built."""


@dataclass(frozen=True)
class PlannedCell:
    source: str
    dest: str
    rate_gbps: float
    n_jobs: int
    job_rate_gbps: float
    rse: str | None
    n_files: int | None
    shortfall: bool | None
    missing: bool = False

    @property
    def n(self) -> int:
        return self.n_jobs


def derive_n(rate_gbps: float, max_rate_per_job_gbps: float, default_inflight: int) -> int:
    if max_rate_per_job_gbps <= 0:
        raise PlanError("max_rate_per_job_gbps must be > 0")
    return max(default_inflight, math.ceil(rate_gbps / max_rate_per_job_gbps))


def derive_job_rate(rate_gbps: float, n_jobs: int) -> float:
    if n_jobs < 1:
        raise PlanError("N must be >= 1")
    return rate_gbps / n_jobs


def scale_cells(cells: list[Cell], target_sum_gbps: float | None) -> list[Cell]:
    """Uniformly scale matrix rates so they sum to ``target_sum_gbps``."""
    if target_sum_gbps is None:
        return cells
    current = sum(cell.rate_gbps for cell in cells)
    if current <= 0:
        raise PlanError("matrix rate sum must be > 0 to scale")
    factor = target_sum_gbps / current
    return [
        Cell(source=cell.source, dest=cell.dest, rate_gbps=cell.rate_gbps * factor)
        for cell in cells
    ]


def _from_cell(cell: Cell, config: Config, link: Link | None, *, missing: bool) -> PlannedCell:
    n_jobs = derive_n(
        cell.rate_gbps, config.max_rate_per_job_gbps, config.default_inflight
    )
    job_rate = derive_job_rate(cell.rate_gbps, n_jobs)
    if missing or link is None:
        return PlannedCell(
            source=cell.source,
            dest=cell.dest,
            rate_gbps=cell.rate_gbps,
            n_jobs=n_jobs,
            job_rate_gbps=job_rate,
            rse=None,
            n_files=None,
            shortfall=None,
            missing=missing,
        )
    return PlannedCell(
        source=cell.source,
        dest=cell.dest,
        rate_gbps=cell.rate_gbps,
        n_jobs=n_jobs,
        job_rate_gbps=job_rate,
        rse=link.rse,
        n_files=link.n_files,
        shortfall=link.shortfall,
        missing=False,
    )


def build_plan(config: Config) -> list[PlannedCell]:
    cells = scale_cells(load_cells(config.matrix), config.target_rate_sum_gbps)
    if config.filelists_dir is None:
        return [_from_cell(cell, config, None, missing=False) for cell in cells]

    try:
        links = load_links(config.filelists_dir)
    except CampaignError as exc:
        raise PlanError(str(exc)) from exc

    planned: list[PlannedCell] = []
    for cell in cells:
        link = links.get((cell.source, cell.dest))
        missing = link is None or not sidecar_exists(link)
        planned.append(_from_cell(cell, config, link, missing=missing))
    return planned


def has_missing(rows: list[PlannedCell]) -> bool:
    return any(row.missing for row in rows)
