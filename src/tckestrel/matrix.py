"""Melt a source×dest Gbps matrix into cells."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

RSE_DEST = re.compile(r"_(Disk|Tape|Buffer)$")


class MatrixError(ValueError):
    """Invalid rate matrix."""


@dataclass(frozen=True)
class Cell:
    source: str
    dest: str
    rate_gbps: float


def _parse_rate(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        rate = float(text)
    except ValueError as exc:
        raise MatrixError(f"non-numeric matrix cell: {raw!r}") from exc
    if rate <= 0:
        return None
    return rate


def load_cells(path: str | Path) -> list[Cell]:
    matrix_path = Path(path)
    if not matrix_path.is_file():
        raise MatrixError(f"matrix not found: {matrix_path}")

    with matrix_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or reader.fieldnames[0] != "source":
            raise MatrixError("matrix first column must be 'source'")
        dests = [name for name in reader.fieldnames[1:] if name]
        rse_dests = [name for name in dests if RSE_DEST.search(name)]
        if rse_dests:
            raise MatrixError(
                "dest headers must be CMS sites, not RSEs: " + ", ".join(rse_dests)
            )

        cells: list[Cell] = []
        for row in reader:
            source = (row.get("source") or "").strip()
            if not source:
                continue
            for dest in dests:
                rate = _parse_rate(row.get(dest))
                if rate is None or source == dest:
                    continue
                cells.append(Cell(source=source, dest=dest, rate_gbps=rate))
    return cells
