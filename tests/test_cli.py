from pathlib import Path

from tckestrel.cli import main


def test_plan_cli_prints_six_cells(fixtures_dir: Path, capsys: object) -> None:
    code = main(["plan", "--config", str(fixtures_dir / "controller.yaml")])
    captured = capsys.readouterr()
    assert code == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert lines[0].split()[:5] == ["source", "dest", "rate_gbps", "N", "job_rate_gbps"]
    assert len(lines) == 7
    assert "T2_CH_CERN" in captured.out
    assert "T1_US_FNAL" in captured.out
    assert "MISSING" not in captured.out


def test_plan_cli_missing_links_exits_nonzero(
    tmp_path: Path, fixtures_dir: Path, capsys: object
) -> None:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / "links.csv").write_text(
        "source,dest,rate_gbps,rse,file_list,n_files,selected_bytes,target_bytes,shortfall\n",
        encoding="utf-8",
    )
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                "campaign_id: missing",
                f"matrix: {fixtures_dir / 'matrix.csv'}",
                f"filelists_dir: {campaign}",
                "max_rate_per_job_gbps: 0.1",
                "default_inflight: 1",
                "chunk_bytes: 1",
                "prom_url: http://127.0.0.1:9091",
                "",
            ]
        ),
        encoding="utf-8",
    )
    code = main(["plan", "--config", str(yaml_path)])
    captured = capsys.readouterr()
    assert code == 1
    assert "MISSING" in captured.out


def test_plan_cli_rejects_rse_dests(tmp_path: Path, fixtures_dir: Path, capsys: object) -> None:
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                "campaign_id: bad",
                f"matrix: {fixtures_dir / 'rse_dest_matrix.csv'}",
                "max_rate_per_job_gbps: 0.1",
                "default_inflight: 1",
                "chunk_bytes: 1",
                "prom_url: http://127.0.0.1:9091",
                "",
            ]
        ),
        encoding="utf-8",
    )
    code = main(["plan", "--config", str(yaml_path)])
    captured = capsys.readouterr()
    assert code == 1
    assert "CMS sites" in captured.err
