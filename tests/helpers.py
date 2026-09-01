"""Write nested controller YAML for tests."""

from __future__ import annotations

from pathlib import Path

import yaml


def dump_controller(
    path: Path,
    *,
    matrix: Path | str,
    campaign_id: str = "x",
    filelists_dir: Path | str | None = None,
    site_map: Path | str | None = None,
    plan: dict | None = None,
    payload: dict | None = None,
    submit: dict | None = None,
    loop: dict | None = None,
) -> Path:
    body: dict = {
        "campaign_id": campaign_id,
        "matrix": str(matrix),
        "plan": {
            "max_job_rate_gbps": 0.1,
            "min_jobs_per_cell": 1,
            **(plan or {}),
        },
        "submit": {
            "pushgateway_url": "http://127.0.0.1:9091",
            **(submit or {}),
        },
    }
    if filelists_dir is not None:
        body["filelists_dir"] = str(filelists_dir)
    if site_map is not None:
        body["site_map"] = str(site_map)
    if payload:
        body["payload"] = payload
    if loop:
        body["loop"] = loop
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path
