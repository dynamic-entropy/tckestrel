from pathlib import Path

import pytest
import yaml

from tckestrel.config import ConfigError, load_config


def test_load_fixture_config(fixtures_dir: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    assert config.campaign_id == "test-6cell"
    assert config.matrix == (fixtures_dir / "matrix.csv").resolve()
    assert config.filelists_dir == (fixtures_dir / "campaign").resolve()
    assert config.max_rate_per_job_gbps == 0.1
    assert config.default_inflight == 1
    assert config.job_duration_s == 7200
    assert config.required_os == "rhel9"
    assert config.request_cpus == 1
    assert config.request_memory_mb == 2048
    assert config.request_disk_mb == 2048
    assert config.condor_pool is None
    assert config.cmssw == "CMSSW_20_1_0_pre2"
    assert config.keep_claim_idle_s == 600
    assert config.max_bytes == 32_000_000
    assert config.chunk_bytes == 8_000_000
    assert config.target_rate_sum_gbps is None
    assert config.loop.idle_cap_per_cell == 4
    assert config.loop.deadband_frac == 0.05
    assert config.proxy_min_ttl_s is None


def test_xrdhover_expands_home(tmp_path: Path, fixtures_dir: Path, monkeypatch: object) -> None:
    home = tmp_path / "home"
    binary = home / "vendor" / "xrdhover"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "x",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_rate_per_job_gbps": 0.1,
                "default_inflight": 1,
                "chunk_bytes": 1,
                "prom_url": "http://127.0.0.1:9091",
                "xrdhover": "$HOME/vendor/xrdhover",
            }
        ),
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert config.xrdhover == binary


def test_xrdhover_version_strips_v(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "x",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_rate_per_job_gbps": 0.1,
                "default_inflight": 1,
                "chunk_bytes": 1,
                "prom_url": "http://127.0.0.1:9091",
                "xrdhover_version": "v0.2.0",
                "xrdhover_dir": "$HOME/vendor/xrdhover",
            }
        ),
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert config.xrdhover_version == "0.2.0"


def test_filelists_dir_optional(fixtures_dir: Path) -> None:
    config = load_config(fixtures_dir / "controller_matrix_only.yaml")
    assert config.filelists_dir is None
    assert config.xrdhover is None
    assert config.xrdhover_dir is None
    assert config.xrdhover_version == "latest"


def test_flat_keys_still_load(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "flat",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_rate_per_job_gbps": 0.2,
                "default_inflight": 2,
                "chunk_bytes": 1,
                "prom_url": "http://127.0.0.1:9091",
                "idle_cap_per_cell": 3,
                "deadband_frac": 0.1,
                "recycle_after_s": 3600,
            }
        ),
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert config.max_rate_per_job_gbps == 0.2
    assert config.default_inflight == 2
    assert config.loop.idle_cap_per_cell == 3
    assert config.loop.deadband_frac == 0.1
    assert config.recycle_after_s == 3600


def test_nested_section_wins_over_flat(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "nested",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_rate_per_job_gbps": 0.9,
                "default_inflight": 9,
                "prom_url": "http://127.0.0.1:1",
                "plan": {
                    "max_rate_per_job_gbps": 0.1,
                    "default_inflight": 1,
                    "chunk_bytes": 1,
                },
                "submit": {"prom_url": "http://127.0.0.1:9091"},
                "loop": {"idle_cap_per_cell": 8, "recycle_after_s": 1800},
                "payload": {"xrdhover_version": "v0.3.0", "required_os": "rhel9"},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert config.max_rate_per_job_gbps == 0.1
    assert config.default_inflight == 1
    assert config.prom_url == "http://127.0.0.1:9091"
    assert config.loop.idle_cap_per_cell == 8
    assert config.recycle_after_s == 1800
    assert config.xrdhover_version == "0.3.0"


def test_missing_required_field(tmp_path: Path, fixtures_dir: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "x",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_rate_per_job_gbps": 0.1,
                "default_inflight": 1,
                "chunk_bytes": 1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="prom_url"):
        load_config(path)


def test_rejects_non_positive_rate(tmp_path: Path, fixtures_dir: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "x",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_rate_per_job_gbps": 0,
                "default_inflight": 1,
                "chunk_bytes": 1,
                "prom_url": "http://127.0.0.1:9091",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="max_rate_per_job_gbps"):
        load_config(path)


def test_rejects_chunk_bytes_over_8mb(tmp_path: Path, fixtures_dir: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "x",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_rate_per_job_gbps": 0.1,
                "default_inflight": 1,
                "chunk_bytes": 16_000_000_000,
                "prom_url": "http://127.0.0.1:9091",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="chunk_bytes"):
        load_config(path)


def test_rejects_max_bytes_zero(tmp_path: Path, fixtures_dir: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "x",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "max_rate_per_job_gbps": 0.1,
                "default_inflight": 1,
                "prom_url": "http://127.0.0.1:9091",
                "max_bytes": 0,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="max_bytes"):
        load_config(path)
