from pathlib import Path

import pytest
import yaml

from helpers import dump_controller
from tckestrel.config import ConfigError, load_config


def test_load_fixture_config(fixtures_dir: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    assert config.campaign_id == "test-6cell"
    assert config.matrix == (fixtures_dir / "matrix.csv").resolve()
    assert config.filelists_dir == (fixtures_dir / "campaign").resolve()
    assert config.plan.max_job_rate_gbps == 0.1
    assert config.plan.min_jobs_per_cell == 1
    assert config.plan.job_duration_s == 7200
    assert config.payload.required_os == "rhel9"
    assert config.submit.request_cpus == 1
    assert config.submit.request_memory_mb == 2048
    assert config.submit.request_disk_mb == 2048
    assert config.submit.condor_pool is None
    assert config.payload.cmssw == "CMSSW_20_1_0_pre2"
    assert config.submit.keep_claim_idle_s == 600
    assert config.plan.max_bytes_per_file == 32_000_000
    assert config.plan.read_size_bytes == 8_000_000
    assert config.plan.target_rate_sum_gbps is None
    assert config.loop.max_idle_jobs_per_cell == 4
    assert config.loop.rate_deadband_frac == 0.05
    assert config.submit.proxy_min_ttl_s is None


def test_xrdhover_expands_home(tmp_path: Path, fixtures_dir: Path, monkeypatch: object) -> None:
    home = tmp_path / "home"
    binary = home / "vendor" / "xrdhover"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    yaml_path = dump_controller(
        tmp_path / "controller.yaml",
        matrix=fixtures_dir / "matrix.csv",
        payload={"binary": "$HOME/vendor/xrdhover"},
    )
    config = load_config(yaml_path)
    assert config.payload.binary == binary


def test_xrdhover_version_strips_v(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_path = dump_controller(
        tmp_path / "controller.yaml",
        matrix=fixtures_dir / "matrix.csv",
        payload={"xrdhover_version": "v0.2.0", "cache_dir": "$HOME/vendor/xrdhover"},
    )
    config = load_config(yaml_path)
    assert config.payload.xrdhover_version == "0.2.0"


def test_filelists_dir_optional(fixtures_dir: Path) -> None:
    config = load_config(fixtures_dir / "controller_matrix_only.yaml")
    assert config.filelists_dir is None
    assert config.payload.binary is None
    assert config.payload.cache_dir is None
    assert config.payload.xrdhover_version == "latest"


def test_flat_keys_are_rejected(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "flat",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_job_rate_gbps": 0.2,
                "min_jobs_per_cell": 2,
                "pushgateway_url": "http://127.0.0.1:9091",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing required section: plan"):
        load_config(yaml_path)


def test_loop_section_loads(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_path = dump_controller(
        tmp_path / "controller.yaml",
        matrix=fixtures_dir / "matrix.csv",
        loop={"max_idle_jobs_per_cell": 8, "recycle_lfn_after_s": 1800},
        payload={"xrdhover_version": "v0.3.0", "required_os": "rhel9"},
    )
    config = load_config(yaml_path)
    assert config.loop.max_idle_jobs_per_cell == 8
    assert config.loop.recycle_lfn_after_s == 1800
    assert config.payload.xrdhover_version == "0.3.0"


def test_missing_required_field(tmp_path: Path, fixtures_dir: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "x",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "plan": {"max_job_rate_gbps": 0.1, "min_jobs_per_cell": 1},
                "submit": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="pushgateway_url"):
        load_config(path)


def test_rejects_non_positive_rate(tmp_path: Path, fixtures_dir: Path) -> None:
    path = dump_controller(
        tmp_path / "bad.yaml",
        matrix=fixtures_dir / "matrix.csv",
        plan={"max_job_rate_gbps": 0},
    )
    with pytest.raises(ConfigError, match="max_job_rate_gbps"):
        load_config(path)


def test_rejects_read_size_over_8mb(tmp_path: Path, fixtures_dir: Path) -> None:
    path = dump_controller(
        tmp_path / "bad.yaml",
        matrix=fixtures_dir / "matrix.csv",
        plan={"read_size_bytes": 16_000_000_000},
    )
    with pytest.raises(ConfigError, match="read_size_bytes"):
        load_config(path)


def test_rejects_max_bytes_per_file_zero(tmp_path: Path, fixtures_dir: Path) -> None:
    path = dump_controller(
        tmp_path / "bad.yaml",
        matrix=fixtures_dir / "matrix.csv",
        plan={"max_bytes_per_file": 0},
    )
    with pytest.raises(ConfigError, match="max_bytes_per_file"):
        load_config(path)
