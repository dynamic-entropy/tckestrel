"""Load Spark campaign links.csv and verify LFN sidecars."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

LINKS_COLUMNS = (
    "source",
    "dest",
    "rate_gbps",
    "rse",
    "file_list",
    "n_files",
    "selected_bytes",
    "target_bytes",
    "shortfall",
)
SIDECAR_COLUMNS = ("lfn", "bytes", "rse")


class CampaignError(ValueError):
    """Invalid Spark campaign directory."""


@dataclass(frozen=True)
class Link:
    source: str
    dest: str
    rate_gbps: float
    rse: str
    file_list: str
    n_files: int
    selected_bytes: int
    target_bytes: int
    shortfall: bool
    sidecar: Path


def _as_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes"}


def _sidecar_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
    if header is None:
        return False
    return tuple(name.strip() for name in header) == SIDECAR_COLUMNS


def load_links(filelists_dir: str | Path) -> dict[tuple[str, str], Link]:
    campaign = Path(filelists_dir)
    if not campaign.is_dir():
        raise CampaignError(f"filelists_dir not found: {campaign}")
    links_path = campaign / "links.csv"
    if not links_path.is_file():
        raise CampaignError(f"links.csv not found: {links_path}")

    with links_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise CampaignError("links.csv has no header")
        missing = [col for col in LINKS_COLUMNS if col not in reader.fieldnames]
        if missing:
            raise CampaignError(f"links.csv missing columns: {', '.join(missing)}")

        links: dict[tuple[str, str], Link] = {}
        for row in reader:
            source = row["source"].strip()
            dest = row["dest"].strip()
            file_list = row["file_list"].strip()
            sidecar = (campaign / file_list).resolve()
            links[(source, dest)] = Link(
                source=source,
                dest=dest,
                rate_gbps=float(row["rate_gbps"]),
                rse=row["rse"].strip(),
                file_list=file_list,
                n_files=int(row["n_files"]),
                selected_bytes=int(row["selected_bytes"]),
                target_bytes=int(row["target_bytes"]),
                shortfall=_as_bool(row["shortfall"]),
                sidecar=sidecar,
            )
    return links


def sidecar_exists(link: Link) -> bool:
    return _sidecar_ok(link.sidecar)
