from pathlib import Path

import pytest
import yaml

from tckestrel.config import load_config
from tckestrel.plan import build_plan, has_missing


def test_join_fixture_campaign(fixtures_dir: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    rows = build_plan(config)
    assert len(rows) == 6
    assert not has_missing(rows)
    by_pair = {(r.source, r.dest): r for r in rows}

    cern_kit = by_pair[("T2_CH_CERN", "T1_DE_KIT")]
    assert cern_kit.n_jobs == 1
    assert cern_kit.job_rate_gbps == pytest.approx(0.017)
    assert cern_kit.rse == "T2_CH_CERN"
    assert cern_kit.n_files == 1
    assert cern_kit.shortfall is False

    fnal_kit = by_pair[("T1_US_FNAL", "T1_DE_KIT")]
    assert fnal_kit.rse == "T1_US_FNAL_Disk"
    assert fnal_kit.n_files == 2


def test_matrix_only_leaves_file_fields_blank(fixtures_dir: Path) -> None:
    config = load_config(fixtures_dir / "controller_matrix_only.yaml")
    rows = build_plan(config)
    assert len(rows) == 6
    assert not has_missing(rows)
    assert all(r.rse is None and r.n_files is None for r in rows)


def test_missing_links_row(tmp_path: Path, fixtures_dir: Path) -> None:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / "links.csv").write_text(
        "source,dest,rate_gbps,rse,file_list,n_files,selected_bytes,target_bytes,shortfall\n",
        encoding="utf-8",
    )
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "missing",
                "matrix": str(fixtures_dir / "matrix.csv"),
                "filelists_dir": str(campaign),
                "max_rate_per_job_gbps": 0.1,
                "default_inflight": 1,
                "chunk_bytes": 1,
                "prom_url": "http://127.0.0.1:9091",
            }
        ),
        encoding="utf-8",
    )
    rows = build_plan(load_config(yaml_path))
    assert len(rows) == 6
    assert has_missing(rows)
    assert all(r.missing for r in rows)
