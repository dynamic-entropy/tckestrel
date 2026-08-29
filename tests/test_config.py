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


def test_filelists_dir_optional(fixtures_dir: Path) -> None:
    config = load_config(fixtures_dir / "controller_matrix_only.yaml")
    assert config.filelists_dir is None


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
