"""CMS site → default disk RSE from Spark site_map.csv."""

from __future__ import annotations

import csv
from pathlib import Path


class SiteMapError(ValueError):
    """site_map.csv missing or has no default disk RSE."""


def load_default_rse(site_map: str | Path, cms_site: str) -> str:
    path = Path(site_map)
    if not path.is_file():
        raise SiteMapError(f"site_map.csv not found: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SiteMapError("site_map.csv has no header")
        site_key = "cms_site" if "cms_site" in reader.fieldnames else "pnn"
        if site_key not in reader.fieldnames:
            raise SiteMapError("site_map.csv needs cms_site or pnn")
        if "disk_rses" not in reader.fieldnames:
            raise SiteMapError("site_map.csv needs disk_rses")
        for row in reader:
            if (row.get(site_key) or "").strip() != cms_site:
                continue
            raw = row.get("disk_rses") or ""
            disks = [part.strip() for part in raw.replace(",", ";").split(";") if part.strip()]
            if not disks:
                raise SiteMapError(f"no disk_rses for {cms_site}")
            return disks[0]
    raise SiteMapError(f"no site_map row for {cms_site}")
