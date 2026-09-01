"""Load and validate controller YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_XRDHOVER_VERSION = "latest"
DEFAULT_CMSSW = "CMSSW_20_1_0_pre2"
DEFAULT_KEEP_CLAIM_IDLE_S = 600
DEFAULT_SESSION_MAX_BYTES = 32_000_000
DEFAULT_READ_SIZE_BYTES = 8_000_000
MAX_READ_SIZE_BYTES = 8_000_000


class ConfigError(ValueError):
    """Invalid or incomplete controller YAML."""


@dataclass(frozen=True)
class PlanConfig:
    max_job_rate_gbps: float
    min_jobs_per_cell: int
    read_size_bytes: int = DEFAULT_READ_SIZE_BYTES
    max_bytes_per_file: int = DEFAULT_SESSION_MAX_BYTES
    job_duration_s: int = 7200
    target_rate_sum_gbps: float | None = None


@dataclass(frozen=True)
class PayloadConfig:
    xrdhover_version: str = DEFAULT_XRDHOVER_VERSION
    cache_dir: Path | None = None
    binary: Path | None = None
    cmssw: str = DEFAULT_CMSSW
    required_os: str = "rhel9"


@dataclass(frozen=True)
class SubmitConfig:
    pushgateway_url: str
    snapshot_interval_s: int = 15
    request_cpus: int = 1
    request_memory_mb: int = 2048
    request_disk_mb: int = 2048
    condor_pool: str | None = None
    condor_schedd: str | None = None
    keep_claim_idle_s: int = DEFAULT_KEEP_CLAIM_IDLE_S
    proxy_min_ttl_s: int | None = None


@dataclass(frozen=True)
class LoopConfig:
    """Outer-loop safety (dev_plan step 7). Loaded, not actuated yet."""

    max_idle_jobs_per_cell: int = 4
    max_idle_jobs_per_dest: int = 20
    max_jobs_per_dest: int = 50
    max_jobs_global: int = 200
    submits_per_minute: int = 10
    min_job_lifetime_s: int = 120
    recycle_lfn_after_s: int = 7200
    rate_deadband_frac: float = 0.05
    ramp_jobs_per_tick: int = 1


@dataclass(frozen=True)
class Config:
    campaign_id: str
    matrix: Path
    plan: PlanConfig
    submit: SubmitConfig
    filelists_dir: Path | None = None
    site_map: Path | None = None
    payload: PayloadConfig = field(default_factory=PayloadConfig)
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


def _section(raw: dict, name: str, *, required: bool = False) -> dict:
    if name not in raw or raw[name] in (None, ""):
        if required:
            raise ConfigError(f"missing required section: {name}")
        return {}
    value = raw[name]
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _need(section: dict, key: str, path: str) -> object:
    value = section.get(key)
    if value in (None, ""):
        raise ConfigError(f"missing required field: {path}")
    return value


def _opt(section: dict, key: str, default: object = None) -> object:
    value = section.get(key, default)
    if value in (None, ""):
        return default
    return value


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
        raise ConfigError("payload.required_os must be non-empty")
    return text


def _require_cmssw(value: object) -> str:
    text = str(value).strip()
    if not text.startswith("CMSSW_"):
        raise ConfigError("payload.cmssw must be a CMSSW_ release name")
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


def _optional_path(section: dict, key: str, config_dir: Path) -> Path | None:
    value = _opt(section, key)
    if value in (None, ""):
        return None
    return resolve_path(str(value), config_dir)


def _xrdhover_version(raw: object) -> str:
    text = str(raw).strip()
    if text.lower() == "latest":
        return "latest"
    text = text.lstrip("v")
    if not text:
        raise ConfigError("payload.xrdhover_version must be non-empty")
    return text


def load_config(path: str | Path) -> Config:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise ConfigError(f"config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("controller YAML must be a mapping")

    campaign_id = raw.get("campaign_id")
    matrix_raw = raw.get("matrix")
    if campaign_id in (None, ""):
        raise ConfigError("missing required field: campaign_id")
    if matrix_raw in (None, ""):
        raise ConfigError("missing required field: matrix")

    plan = _section(raw, "plan", required=True)
    payload = _section(raw, "payload")
    submit = _section(raw, "submit", required=True)
    loop = _section(raw, "loop")
    config_dir = config_path.parent

    proxy_raw = _opt(submit, "proxy_min_ttl_s")
    return Config(
        campaign_id=str(campaign_id),
        matrix=resolve_path(str(matrix_raw), config_dir),
        filelists_dir=_optional_path(raw, "filelists_dir", config_dir),
        site_map=_optional_path(raw, "site_map", config_dir),
        plan=PlanConfig(
            max_job_rate_gbps=_require_positive_float(
                "plan.max_job_rate_gbps", _need(plan, "max_job_rate_gbps", "plan.max_job_rate_gbps")
            ),
            min_jobs_per_cell=_require_int(
                "plan.min_jobs_per_cell",
                _need(plan, "min_jobs_per_cell", "plan.min_jobs_per_cell"),
                minimum=1,
            ),
            read_size_bytes=_require_int(
                "plan.read_size_bytes",
                _opt(plan, "read_size_bytes", DEFAULT_READ_SIZE_BYTES),
                minimum=1,
                maximum=MAX_READ_SIZE_BYTES,
            ),
            max_bytes_per_file=_require_int(
                "plan.max_bytes_per_file",
                _opt(plan, "max_bytes_per_file", DEFAULT_SESSION_MAX_BYTES),
                minimum=1,
            ),
            job_duration_s=_require_int(
                "plan.job_duration_s",
                _opt(plan, "job_duration_s", 7200),
                minimum=1,
            ),
            target_rate_sum_gbps=_optional_positive_float(
                "plan.target_rate_sum_gbps", _opt(plan, "target_rate_sum_gbps")
            ),
        ),
        payload=PayloadConfig(
            xrdhover_version=_xrdhover_version(
                _opt(payload, "xrdhover_version", DEFAULT_XRDHOVER_VERSION)
            ),
            cache_dir=_optional_path(payload, "cache_dir", config_dir),
            binary=_optional_path(payload, "binary", config_dir),
            cmssw=_require_cmssw(_opt(payload, "cmssw", DEFAULT_CMSSW)),
            required_os=_require_os(_opt(payload, "required_os", "rhel9")),
        ),
        submit=SubmitConfig(
            pushgateway_url=str(
                _need(submit, "pushgateway_url", "submit.pushgateway_url")
            ),
            snapshot_interval_s=_require_int(
                "submit.snapshot_interval_s",
                _opt(submit, "snapshot_interval_s", 15),
                minimum=1,
            ),
            request_cpus=_require_int(
                "submit.request_cpus", _opt(submit, "request_cpus", 1), minimum=1
            ),
            request_memory_mb=_require_int(
                "submit.request_memory_mb",
                _opt(submit, "request_memory_mb", 2048),
                minimum=1,
            ),
            request_disk_mb=_require_int(
                "submit.request_disk_mb",
                _opt(submit, "request_disk_mb", 2048),
                minimum=1,
            ),
            condor_pool=_optional_host(_opt(submit, "condor_pool")),
            condor_schedd=_optional_host(_opt(submit, "condor_schedd")),
            keep_claim_idle_s=_require_int(
                "submit.keep_claim_idle_s",
                _opt(submit, "keep_claim_idle_s", DEFAULT_KEEP_CLAIM_IDLE_S),
                minimum=0,
            ),
            proxy_min_ttl_s=(
                None
                if proxy_raw in (None, "")
                else _require_int("submit.proxy_min_ttl_s", proxy_raw, minimum=1)
            ),
        ),
        loop=LoopConfig(
            max_idle_jobs_per_cell=_require_int(
                "loop.max_idle_jobs_per_cell",
                _opt(loop, "max_idle_jobs_per_cell", 4),
                minimum=0,
            ),
            max_idle_jobs_per_dest=_require_int(
                "loop.max_idle_jobs_per_dest",
                _opt(loop, "max_idle_jobs_per_dest", 20),
                minimum=0,
            ),
            max_jobs_per_dest=_require_int(
                "loop.max_jobs_per_dest",
                _opt(loop, "max_jobs_per_dest", 50),
                minimum=1,
            ),
            max_jobs_global=_require_int(
                "loop.max_jobs_global",
                _opt(loop, "max_jobs_global", 200),
                minimum=1,
            ),
            submits_per_minute=_require_int(
                "loop.submits_per_minute",
                _opt(loop, "submits_per_minute", 10),
                minimum=1,
            ),
            min_job_lifetime_s=_require_int(
                "loop.min_job_lifetime_s",
                _opt(loop, "min_job_lifetime_s", 120),
                minimum=0,
            ),
            recycle_lfn_after_s=_require_int(
                "loop.recycle_lfn_after_s",
                _opt(loop, "recycle_lfn_after_s", 7200),
                minimum=1,
            ),
            rate_deadband_frac=_require_frac(
                "loop.rate_deadband_frac",
                _opt(loop, "rate_deadband_frac", 0.05),
            ),
            ramp_jobs_per_tick=_require_int(
                "loop.ramp_jobs_per_tick",
                _opt(loop, "ramp_jobs_per_tick", 1),
                minimum=1,
            ),
        ),
        source_path=config_path,
    )
