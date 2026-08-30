from pathlib import Path

from tckestrel.cli import main
from tckestrel.condor import RecordingCondor, SubmitSpec
from tckestrel.payload import Payload
from tckestrel.rucio_backend import MappingBackend


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


def test_resolve_cli_uses_mock_backend(
    fixtures_dir: Path, tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    backend = MappingBackend(
        {
            "/store/mc/PREMIX/cern-fnal.root": (
                "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-fnal.root"
            )
        }
    )
    monkeypatch.setattr("tckestrel.cli.default_backend", lambda: backend)
    monkeypatch.setattr(
        "tckestrel.cli.cache_file", lambda config: tmp_path / "rse_prefix.json"
    )
    code = main(
        [
            "resolve",
            "--config",
            str(fixtures_dir / "controller.yaml"),
            "--cell",
            "T2_CH_CERN,T1_US_FNAL",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "root://eoscms.cern.ch:1094/" in captured.out
    assert "/eos/cms/store/mc/PREMIX/cern-fnal.root" in captured.out
    assert "cms-xrd-global" not in captured.out


def test_render_cli_writes_job(
    tmp_path: Path, fixtures_dir: Path, capsys: object, monkeypatch: object
) -> None:
    backend = MappingBackend(
        {
            "/store/mc/PREMIX/cern-fnal.root": (
                "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-fnal.root"
            )
        }
    )
    monkeypatch.setattr("tckestrel.cli.default_backend", lambda: backend)
    monkeypatch.setattr(
        "tckestrel.cli.cache_file", lambda config: tmp_path / "rse_prefix.json"
    )
    out = tmp_path / "rendered"
    code = main(
        [
            "render",
            "--config",
            str(fixtures_dir / "controller.yaml"),
            "--cell",
            "T2_CH_CERN,T1_US_FNAL",
            "--out",
            str(out),
            "--job-id",
            "cli.0",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert (out / "job.json").is_file()
    assert (out / "files.txt").is_file()
    assert "17Mbps" in (out / "job.json").read_text(encoding="utf-8")
    assert "auto" not in (out / "job.json").read_text(encoding="utf-8")
    assert str(out / "job.json") in captured.out


def test_submit_cli_dry_run_writes_sub(
    tmp_path: Path, fixtures_dir: Path, capsys: object, monkeypatch: object
) -> None:
    backend = MappingBackend(
        {
            "/store/mc/PREMIX/cern-fnal.root": (
                "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-fnal.root"
            )
        }
    )
    binary = tmp_path / "xrdhover"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.delenv("X509_USER_PROXY", raising=False)
    monkeypatch.setattr("tckestrel.cli.default_backend", lambda: backend)
    monkeypatch.setattr(
        "tckestrel.cli.cache_file", lambda config: tmp_path / "rse_prefix.json"
    )
    monkeypatch.setattr(
        "tckestrel.submit.ensure_payload",
        lambda config, arch: Payload(
            path=binary, version="0.2.0", arch=arch, fetched=False
        ),
    )
    out = tmp_path / "submitted"
    code = main(
        [
            "submit",
            "--config",
            str(fixtures_dir / "controller.yaml"),
            "--cell",
            "T2_CH_CERN,T1_US_FNAL",
            "--out",
            str(out),
            "--job-id",
            "cli.sub.0",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert (out / "job.sub").is_file()
    assert "submitted false" in captured.out
    text = (out / "job.sub").read_text(encoding="utf-8")
    assert "+DESIRED_Sites" in text
    assert '"T1_US_FNAL"' in text
    assert "run job.json" in text


def test_submit_cli_queues_with_mock(
    tmp_path: Path, fixtures_dir: Path, capsys: object, monkeypatch: object
) -> None:
    backend = MappingBackend(
        {
            "/store/mc/PREMIX/cern-fnal.root": (
                "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-fnal.root"
            )
        }
    )
    binary = tmp_path / "xrdhover"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    recorder = RecordingCondor()
    monkeypatch.delenv("X509_USER_PROXY", raising=False)
    monkeypatch.setattr("tckestrel.cli.default_backend", lambda: backend)
    monkeypatch.setattr(
        "tckestrel.cli.cache_file", lambda config: tmp_path / "rse_prefix.json"
    )
    monkeypatch.setattr(
        "tckestrel.cli.default_condor", lambda *args, **kwargs: recorder
    )
    monkeypatch.setattr(
        "tckestrel.submit.ensure_payload",
        lambda config, arch: Payload(
            path=binary, version="0.2.0", arch=arch, fetched=False
        ),
    )
    code = main(
        [
            "submit",
            "--config",
            str(fixtures_dir / "controller.yaml"),
            "--cell",
            "T2_CH_CERN,T1_US_FNAL",
            "--out",
            str(tmp_path / "queued"),
            "--job-id",
            "cli.q.0",
            "--submit",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "submitted 100.0" in captured.out
    assert len(recorder.submitted) == 1
    assert recorder.submitted[0].job_id == "cli.q.0"


def test_submit_cli_queues_plan(
    tmp_path: Path, fixtures_dir: Path, capsys: object, monkeypatch: object
) -> None:
    backend = MappingBackend(
        {
            "/store/mc/PREMIX/cern-fnal.root": (
                "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-fnal.root"
            ),
            "/store/mc/PREMIX/cern-kit.root": (
                "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-kit.root"
            ),
            "/store/mc/PREMIX/cern-ucsd.root": (
                "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-ucsd.root"
            ),
            "/store/mc/PREMIX/fnal-cern.root": (
                "root://cmsxrootd.fnal.gov:1094//pnfs/fnal.gov/usr/cms/WAX/11"
                "/store/mc/PREMIX/fnal-cern.root"
            ),
            "/store/mc/PREMIX/fnal-kit-a.root": (
                "root://cmsxrootd.fnal.gov:1094//pnfs/fnal.gov/usr/cms/WAX/11"
                "/store/mc/PREMIX/fnal-kit-a.root"
            ),
            "/store/mc/PREMIX/fnal-kit-b.root": (
                "root://cmsxrootd.fnal.gov:1094//pnfs/fnal.gov/usr/cms/WAX/11"
                "/store/mc/PREMIX/fnal-kit-b.root"
            ),
            "/store/mc/PREMIX/fnal-ucsd.root": (
                "root://cmsxrootd.fnal.gov:1094//pnfs/fnal.gov/usr/cms/WAX/11"
                "/store/mc/PREMIX/fnal-ucsd.root"
            ),
        }
    )
    binary = tmp_path / "xrdhover"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    recorder = RecordingCondor()
    monkeypatch.delenv("X509_USER_PROXY", raising=False)
    monkeypatch.setattr("tckestrel.cli.default_backend", lambda: backend)
    monkeypatch.setattr(
        "tckestrel.cli.cache_file", lambda config: tmp_path / "rse_prefix.json"
    )
    monkeypatch.setattr(
        "tckestrel.cli.default_condor", lambda *args, **kwargs: recorder
    )
    monkeypatch.setattr(
        "tckestrel.submit.ensure_payload",
        lambda config, arch: Payload(
            path=binary, version="0.2.0", arch=arch, fetched=False
        ),
    )
    code = main(
        [
            "submit",
            "--config",
            str(fixtures_dir / "controller.yaml"),
            "--submit",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "queued 6" in captured.out
    assert len(recorder.submitted) == 6


def test_jobs_and_rm_cli(
    tmp_path: Path, fixtures_dir: Path, capsys: object, monkeypatch: object
) -> None:
    recorder = RecordingCondor()
    recorder.submit(
        SubmitSpec(
            executable=tmp_path / "xrdhover",
            job_dir=tmp_path,
            dest="T1_US_FNAL",
            campaign_id="test-6cell",
            source="T2_CH_CERN",
            run_id="test-6cell/T2_CH_CERN__T1_US_FNAL",
            job_id="listed.0",
        )
    )
    monkeypatch.setattr(
        "tckestrel.cli.default_condor", lambda *args, **kwargs: recorder
    )
    code = main(["jobs", "--config", str(fixtures_dir / "controller.yaml")])
    captured = capsys.readouterr()
    assert code == 0
    assert "100.0" in captured.out
    assert "listed.0" in captured.out
    assert "T1_US_FNAL" in captured.out
    code = main(
        [
            "rm",
            "--config",
            str(fixtures_dir / "controller.yaml"),
            "--cell",
            "T2_CH_CERN,T1_US_FNAL",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "removed 1" in captured.out
    assert 'TckestrelCampaign == "test-6cell"' in captured.out
    assert recorder.query("test-6cell") == []


def test_payload_cli_uses_cache(
    tmp_path: Path, fixtures_dir: Path, capsys: object
) -> None:
    dest_dir = tmp_path / "vendor"
    binary = dest_dir / "0.2.0" / "linux-amd64" / "xrdhover"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o755)
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                "campaign_id: payload",
                f"matrix: {fixtures_dir / 'matrix.csv'}",
                "max_rate_per_job_gbps: 0.1",
                "default_inflight: 1",
                "chunk_bytes: 1",
                "prom_url: http://127.0.0.1:9091",
                f"xrdhover_dir: {dest_dir}",
                "xrdhover_version: 0.2.0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    code = main(["payload", "--config", str(yaml_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert "linux-amd64" in captured.out
    assert str(binary) in captured.out
    assert "fetched   false" in captured.out


def test_resolve_cli_bad_rucio_config(
    fixtures_dir: Path, tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    monkeypatch.setenv("RUCIO_CONFIG", str(tmp_path / "missing.cfg"))
    monkeypatch.setattr(
        "tckestrel.cli.cache_file", lambda config: tmp_path / "rse_prefix.json"
    )
    code = main(
        [
            "resolve",
            "--config",
            str(fixtures_dir / "controller.yaml"),
            "--cell",
            "T2_CH_CERN,T1_US_FNAL",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "Traceback" not in captured.err
    assert "Rucio" in captured.err
