"""Load and validate controller YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_XRDHOVER_VERSION = "latest"

REQUIRED = (
    "campaign_id",
    "matrix",
    "max_rate_per_job_gbps",
    "default_inflight",
    "chunk_bytes",
    "prom_url",
)


class ConfigError(ValueError):
    """Invalid or incomplete controller YAML."""


@dataclass(frozen=True)
class Config:
    campaign_id: str
    matrix: Path
    filelists_dir: Path | None
    max_rate_per_job_gbps: float
    default_inflight: int
    chunk_bytes: int
    prom_url: str
    job_duration_s: int = 7200
    recycle_after_s: int = 7200
    max_bytes: int = 0
    site_map: Path | None = None
    xrdhover: Path | None = None
    xrdhover_dir: Path | None = None
    xrdhover_version: str = DEFAULT_XRDHOVER_VERSION
    source_path: Path | None = None


def resolve_path(raw: str, config_dir: Path) -> Path:
    """Resolve a YAML path relative to the config file, then cwd.

    Expands ``$HOME``, ``${HOME}``, and ``~``.
    """
    path = Path(os.path.expanduser(os.path.expandvars(raw)))
    if path.is_absolute():
        return path
    config_rel = (config_dir / path).resolve()
    if config_rel.exists():
        return config_rel
    cwd_rel = (Path.cwd() / path).resolve()
    if cwd_rel.exists():
        return cwd_rel
    return config_rel


def _require_positive_float(name: str, value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if number <= 0:
        raise ConfigError(f"{name} must be > 0")
    return number


def _require_int(name: str, value: object, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        try:
            as_float = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{name} must be an integer") from exc
        if as_float != int(as_float):
            raise ConfigError(f"{name} must be an integer")
        number = int(as_float)
    if number < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return number


def load_config(path: str | Path) -> Config:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise ConfigError(f"config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("controller YAML must be a mapping")
    missing = [key for key in REQUIRED if key not in raw or raw[key] in (None, "")]
    if missing:
        raise ConfigError(f"missing required fields: {', '.join(missing)}")

    config_dir = config_path.parent
    matrix = resolve_path(str(raw["matrix"]), config_dir)
    filelists_raw = raw.get("filelists_dir")
    filelists_dir = (
        resolve_path(str(filelists_raw), config_dir) if filelists_raw else None
    )
    site_map_raw = raw.get("site_map")
    site_map = resolve_path(str(site_map_raw), config_dir) if site_map_raw else None
    xrdhover_raw = raw.get("xrdhover")
    xrdhover = resolve_path(str(xrdhover_raw), config_dir) if xrdhover_raw else None
    xrdhover_dir_raw = raw.get("xrdhover_dir")
    xrdhover_dir = (
        resolve_path(str(xrdhover_dir_raw), config_dir) if xrdhover_dir_raw else None
    )
    version_raw = raw.get("xrdhover_version", DEFAULT_XRDHOVER_VERSION)
    xrdhover_version = str(version_raw).strip()
    if xrdhover_version.lower() == "latest":
        xrdhover_version = "latest"
    else:
        xrdhover_version = xrdhover_version.lstrip("v")
    if not xrdhover_version:
        raise ConfigError("xrdhover_version must be non-empty")

    return Config(
        campaign_id=str(raw["campaign_id"]),
        matrix=matrix,
        filelists_dir=filelists_dir,
        max_rate_per_job_gbps=_require_positive_float(
            "max_rate_per_job_gbps", raw["max_rate_per_job_gbps"]
        ),
        default_inflight=_require_int(
            "default_inflight", raw["default_inflight"], minimum=1
        ),
        chunk_bytes=_require_int("chunk_bytes", raw["chunk_bytes"], minimum=1),
        prom_url=str(raw["prom_url"]),
        job_duration_s=_require_int(
            "job_duration_s", raw.get("job_duration_s", 7200), minimum=1
        ),
        recycle_after_s=_require_int(
            "recycle_after_s", raw.get("recycle_after_s", 7200), minimum=1
        ),
        max_bytes=_require_int("max_bytes", raw.get("max_bytes", 0), minimum=0),
        site_map=site_map,
        xrdhover=xrdhover,
        xrdhover_dir=xrdhover_dir,
        xrdhover_version=xrdhover_version,
        source_path=config_path,
    )
