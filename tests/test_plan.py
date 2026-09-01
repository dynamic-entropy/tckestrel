from pathlib import Path

import pytest

from helpers import dump_controller
from tckestrel.config import load_config
from tckestrel.matrix import Cell
from tckestrel.plan import build_plan, has_missing, scale_cells


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
    yaml_path = dump_controller(
        tmp_path / "controller.yaml",
        campaign_id="missing",
        matrix=fixtures_dir / "matrix.csv",
        filelists_dir=campaign,
        plan={"read_size_bytes": 1},
    )
    rows = build_plan(load_config(yaml_path))
    assert len(rows) == 6
    assert has_missing(rows)
    assert all(r.missing for r in rows)


def test_scale_cells_to_target_sum() -> None:
    cells = [
        Cell("S", "A", 2.0),
        Cell("S", "B", 2.0),
    ]
    scaled = scale_cells(cells, 1.0)
    assert sum(c.rate_gbps for c in scaled) == pytest.approx(1.0)
    assert scaled[0].rate_gbps == pytest.approx(0.5)
    assert scale_cells(cells, None) == cells


def test_target_rate_sum_scales_plan(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_path = dump_controller(
        tmp_path / "controller.yaml",
        campaign_id="scaled",
        matrix=fixtures_dir / "matrix.csv",
        filelists_dir=fixtures_dir / "campaign",
        plan={"max_job_rate_gbps": 0.2, "target_rate_sum_gbps": 0.06},
    )
    rows = build_plan(load_config(yaml_path))
    assert sum(r.rate_gbps for r in rows) == pytest.approx(0.06)
    assert all(r.n_jobs == 1 for r in rows)
