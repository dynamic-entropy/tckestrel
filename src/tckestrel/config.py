"""Load and validate controller YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_XRDHOVER_VERSION = "latest"
DEFAULT_CMSSW = "CMSSW_20_1_0_pre2"
DEFAULT_KEEP_CLAIM_IDLE_S = 600
# Per-file session cap (pattern.max_bytes). Small vs target_rate so the
# token bucket sees many sessions, not one PREMIX-sized read.
DEFAULT_SESSION_MAX_BYTES = 32_000_000
# One XRootD Read() / pattern.read_size. Not the LFN-pool slice.
DEFAULT_READ_SIZE_BYTES = 8_000_000
MAX_READ_SIZE_BYTES = 8_000_000

# CLI-aligned YAML sections. Keys may also sit at the top level (cmscon).
SECTIONS = frozenset({"plan", "payload", "submit", "loop"})

REQUIRED = (
    ("campaign_id", None),
    ("matrix", None),
    ("max_rate_per_job_gbps", "plan"),
    ("default_inflight", "plan"),
    ("prom_url", "submit"),
)


class ConfigError(ValueError):
    """Invalid or incomplete controller YAML."""


@dataclass(frozen=True)
class LoopConfig:
    """Outer-loop safety (dev_plan step 7). Loaded, not actuated yet."""

    idle_cap_per_cell: int = 4
    max_idle_per_dest: int = 20
    max_jobs_per_dest: int = 50
    max_jobs_global: int = 200
    submits_per_minute: int = 10
    min_job_lifetime_s: int = 120
    deadband_frac: float = 0.05
    ramp_jobs_per_tick: int = 1


@dataclass(frozen=True)
class Config:
    campaign_id: str
    matrix: Path
    filelists_dir: Path | None
    max_rate_per_job_gbps: float
    default_inflight: int
    prom_url: str
    chunk_bytes: int = DEFAULT_READ_SIZE_BYTES
    job_duration_s: int = 7200
    recycle_after_s: int = 7200
    max_bytes: int = DEFAULT_SESSION_MAX_BYTES
    snapshot_interval_s: int = 15
    site_map: Path | None = None
    xrdhover: Path | None = None
    xrdhover_dir: Path | None = None
    xrdhover_version: str = DEFAULT_XRDHOVER_VERSION
    required_os: str = "rhel9"
    request_cpus: int = 1
    request_memory_mb: int = 2048
    request_disk_mb: int = 2048
    condor_pool: str | None = None
    condor_schedd: str | None = None
    cmssw: str = DEFAULT_CMSSW
    keep_claim_idle_s: int = DEFAULT_KEEP_CLAIM_IDLE_S
    target_rate_sum_gbps: float | None = None
    proxy_min_ttl_s: int | None = None
    loop: LoopConfig = field(default_factory=LoopConfig)
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


def _section(raw: dict, name: str) -> dict:
    value = raw.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _get(raw: dict, key: str, section: str | None, default: object = None) -> object:
    """Prefer ``section.key``; fall back to a top-level key (live cmscon YAML)."""
    if section is not None:
        nested = _section(raw, section)
        if key in nested and nested[key] not in (None, ""):
            return nested[key]
    if key in raw and raw[key] not in (None, "") and key not in SECTIONS:
        return raw[key]
    return default


def _optional_positive_float(name: str, value: object) -> float | None:
    if value in (None, ""):
        return None
    return _require_positive_float(name, value)


def _require_positive_float(name: str, value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if number <= 0:
        raise ConfigError(f"{name} must be > 0")
    return number


def _require_frac(name: str, value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if number < 0 or number > 1:
        raise ConfigError(f"{name} must be between 0 and 1")
    return number


def _optional_host(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _require_os(value: object) -> str:
    text = str(value).strip()
    if not text:
        raise ConfigError("required_os must be non-empty")
    return text


def _require_cmssw(value: object) -> str:
    text = str(value).strip()
    if not text.startswith("CMSSW_"):
        raise ConfigError("cmssw must be a CMSSW_ release name")
    return text


def _require_int(
    name: str, value: object, *, minimum: int, maximum: int | None = None
) -> int:
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
    if maximum is not None and number > maximum:
        raise ConfigError(f"{name} must be <= {maximum}")
    return number


def _optional_path(raw: dict, key: str, section: str | None, config_dir: Path) -> Path | None:
    value = _get(raw, key, section)
    if value in (None, ""):
        return None
    return resolve_path(str(value), config_dir)


def load_config(path: str | Path) -> Config:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise ConfigError(f"config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("controller YAML must be a mapping")
    missing = [
        key if section is None else f"{section}.{key}"
        for key, section in REQUIRED
        if _get(raw, key, section) in (None, "")
    ]
    if missing:
        raise ConfigError(f"missing required fields: {', '.join(missing)}")

    config_dir = config_path.parent
    matrix = resolve_path(str(_get(raw, "matrix", None)), config_dir)
    filelists_dir = _optional_path(raw, "filelists_dir", None, config_dir)
    site_map = _optional_path(raw, "site_map", None, config_dir)
    xrdhover = _optional_path(raw, "xrdhover", "payload", config_dir)
    xrdhover_dir = _optional_path(raw, "xrdhover_dir", "payload", config_dir)
    version_raw = _get(raw, "xrdhover_version", "payload", DEFAULT_XRDHOVER_VERSION)
    xrdhover_version = str(version_raw).strip()
    if xrdhover_version.lower() == "latest":
        xrdhover_version = "latest"
    else:
        xrdhover_version = xrdhover_version.lstrip("v")
    if not xrdhover_version:
        raise ConfigError("xrdhover_version must be non-empty")

    proxy_raw = _get(raw, "proxy_min_ttl_s", "submit")
    proxy_min_ttl_s = (
        None
        if proxy_raw in (None, "")
        else _require_int("proxy_min_ttl_s", proxy_raw, minimum=1)
    )

    return Config(
        campaign_id=str(_get(raw, "campaign_id", None)),
        matrix=matrix,
        filelists_dir=filelists_dir,
        max_rate_per_job_gbps=_require_positive_float(
            "max_rate_per_job_gbps", _get(raw, "max_rate_per_job_gbps", "plan")
        ),
        default_inflight=_require_int(
            "default_inflight", _get(raw, "default_inflight", "plan"), minimum=1
        ),
        chunk_bytes=_require_int(
            "chunk_bytes",
            _get(raw, "chunk_bytes", "plan", DEFAULT_READ_SIZE_BYTES),
            minimum=1,
            maximum=MAX_READ_SIZE_BYTES,
        ),
        prom_url=str(_get(raw, "prom_url", "submit")),
        job_duration_s=_require_int(
            "job_duration_s",
            _get(raw, "job_duration_s", "plan", 7200),
            minimum=1,
        ),
        recycle_after_s=_require_int(
            "recycle_after_s",
            _get(raw, "recycle_after_s", "loop", 7200),
            minimum=1,
        ),
        max_bytes=_require_int(
            "max_bytes",
            _get(raw, "max_bytes", "plan", DEFAULT_SESSION_MAX_BYTES),
            minimum=1,
        ),
        snapshot_interval_s=_require_int(
            "snapshot_interval_s",
            _get(raw, "snapshot_interval_s", "submit", 15),
            minimum=1,
        ),
        site_map=site_map,
        xrdhover=xrdhover,
        xrdhover_dir=xrdhover_dir,
        xrdhover_version=xrdhover_version,
        required_os=_require_os(_get(raw, "required_os", "payload", "rhel9")),
        request_cpus=_require_int(
            "request_cpus", _get(raw, "request_cpus", "submit", 1), minimum=1
        ),
        request_memory_mb=_require_int(
            "request_memory_mb",
            _get(raw, "request_memory_mb", "submit", 2048),
            minimum=1,
        ),
        request_disk_mb=_require_int(
            "request_disk_mb",
            _get(raw, "request_disk_mb", "submit", 2048),
            minimum=1,
        ),
        condor_pool=_optional_host(_get(raw, "condor_pool", "submit")),
        condor_schedd=_optional_host(_get(raw, "condor_schedd", "submit")),
        cmssw=_require_cmssw(_get(raw, "cmssw", "payload", DEFAULT_CMSSW)),
        keep_claim_idle_s=_require_int(
            "keep_claim_idle",
            _get(raw, "keep_claim_idle", "submit", DEFAULT_KEEP_CLAIM_IDLE_S),
            minimum=0,
        ),
        target_rate_sum_gbps=_optional_positive_float(
            "target_rate_sum_gbps", _get(raw, "target_rate_sum_gbps", "plan")
        ),
        proxy_min_ttl_s=proxy_min_ttl_s,
        loop=LoopConfig(
            idle_cap_per_cell=_require_int(
                "idle_cap_per_cell",
                _get(raw, "idle_cap_per_cell", "loop", 4),
                minimum=0,
            ),
            max_idle_per_dest=_require_int(
                "max_idle_per_dest",
                _get(raw, "max_idle_per_dest", "loop", 20),
                minimum=0,
            ),
            max_jobs_per_dest=_require_int(
                "max_jobs_per_dest",
                _get(raw, "max_jobs_per_dest", "loop", 50),
                minimum=1,
            ),
            max_jobs_global=_require_int(
                "max_jobs_global",
                _get(raw, "max_jobs_global", "loop", 200),
                minimum=1,
            ),
            submits_per_minute=_require_int(
                "submits_per_minute",
                _get(raw, "submits_per_minute", "loop", 10),
                minimum=1,
            ),
            min_job_lifetime_s=_require_int(
                "min_job_lifetime_s",
                _get(raw, "min_job_lifetime_s", "loop", 120),
                minimum=0,
            ),
            deadband_frac=_require_frac(
                "deadband_frac", _get(raw, "deadband_frac", "loop", 0.05)
            ),
            ramp_jobs_per_tick=_require_int(
                "ramp_jobs_per_tick",
                _get(raw, "ramp_jobs_per_tick", "loop", 1),
                minimum=1,
            ),
        ),
        source_path=config_path,
    )
