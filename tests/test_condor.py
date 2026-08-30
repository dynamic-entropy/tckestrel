from pathlib import Path

from tckestrel.cache import PrefixCache
from tckestrel.condor import (
    RecordingCondor,
    SubmitSpec,
    campaign_constraint,
    condor_argv,
    submit_items,
    submit_text,
)
from tckestrel.config import DEFAULT_CMSSW, load_config
from tckestrel.payload import Payload
from tckestrel.rucio_backend import MappingBackend
from tckestrel.submit import submit_cell, submit_plan

CERN_LFN = "/store/mc/PREMIX/cern-fnal.root"
CERN_PFN = "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-fnal.root"
FNAL_PFN = (
    "root://cmsxrootd.fnal.gov:1094//pnfs/fnal.gov/usr/cms/WAX/11"
    "/store/mc/PREMIX/fnal-cern.root"
)


def _campaign_backend() -> MappingBackend:
    return MappingBackend(
        {
            CERN_LFN: CERN_PFN,
            "/store/mc/PREMIX/cern-kit.root": CERN_PFN.replace("cern-fnal", "cern-kit"),
            "/store/mc/PREMIX/cern-ucsd.root": CERN_PFN.replace("cern-fnal", "cern-ucsd"),
            "/store/mc/PREMIX/fnal-cern.root": FNAL_PFN,
            "/store/mc/PREMIX/fnal-kit-a.root": FNAL_PFN.replace("fnal-cern", "fnal-kit-a"),
            "/store/mc/PREMIX/fnal-kit-b.root": FNAL_PFN.replace("fnal-cern", "fnal-kit-b"),
            "/store/mc/PREMIX/fnal-ucsd.root": FNAL_PFN.replace("fnal-cern", "fnal-ucsd"),
        }
    )


def _payload(tmp_path: Path) -> Payload:
    binary = tmp_path / "xrdhover"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    return Payload(path=binary, version="0.2.0", arch="linux-amd64", fetched=False)


def _spec(tmp_path: Path) -> SubmitSpec:
    job_dir = tmp_path / "job"
    job_dir.mkdir(exist_ok=True)
    return SubmitSpec(
        executable=job_dir / "run_xrdhover.sh",
        job_dir=job_dir,
        dest="T1_US_FNAL",
        campaign_id="test-6cell",
        source="T2_CH_CERN",
        run_id="test-6cell/T2_CH_CERN__T1_US_FNAL",
        job_id="job.0",
        payload=tmp_path / "xrdhover",
        cmssw=DEFAULT_CMSSW,
    )


def test_submit_text_contract(tmp_path: Path) -> None:
    text = submit_text(_spec(tmp_path))
    items = submit_items(_spec(tmp_path))
    assert items["universe"] == "vanilla"
    assert items["transfer_executable"] == "true"
    assert items["arguments"] == f"-C {DEFAULT_CMSSW} -- run job.json"
    assert items["transfer_input_files"] == f"job.json, files.txt, {tmp_path / 'xrdhover'}"
    assert items["+DesiredOS"] == "REQUIRED_OS"
    assert items["should_transfer_files"] == "YES"
    assert items["should_transfer_output"] == "YES"
    assert items["when_to_transfer_output"] == "ON_EXIT_OR_EVICT"
    assert items["output"] == "logs/$(Cluster).$(Process).out"
    assert items["error"] == "logs/$(Cluster).$(Process).err"
    assert items["log"] == "logs/$(Cluster).$(Process).log"
    assert items["job_machine_attrs"] == "GLIDEIN_CMSSite"
    assert items["x509userproxy"] == "$ENV(X509_USER_PROXY)"
    assert items["+DESIRED_Sites"] == '"T1_US_FNAL"'
    assert items["+REQUIRED_OS"] == '"rhel9"'
    assert items["+TckestrelCampaign"] == '"test-6cell"'
    assert items["+TckestrelSource"] == '"T2_CH_CERN"'
    assert items["+TckestrelDest"] == '"T1_US_FNAL"'
    assert items["+TckestrelRunId"] == '"test-6cell/T2_CH_CERN__T1_US_FNAL"'
    assert items["+TckestrelJobId"] == '"job.0"'
    assert items["use_x509userproxy"] == "true"
    assert items["request_cpus"] == "1"
    assert items["request_memory"] == "2048MB"
    assert items["request_disk"] == "2048MB"
    assert items["keep_claim_idle"] == "600"
    assert text.endswith("queue\n")
    assert "transfer_executable" in text and "= true" in text
    assert "arguments" in text and f"-C {DEFAULT_CMSSW}" in text
    assert "run job.json" in text


def test_submit_text_includes_proxy(tmp_path: Path) -> None:
    proxy = tmp_path / "x509up"
    proxy.write_text("proxy", encoding="utf-8")
    spec = SubmitSpec(
        executable=tmp_path / "xrdhover",
        job_dir=tmp_path / "job",
        dest="T1_US_FNAL",
        campaign_id="c",
        source="S",
        run_id="c/S__T1_US_FNAL",
        job_id="1",
        proxy=proxy,
    )
    assert submit_items(spec)["x509userproxy"] == "$ENV(X509_USER_PROXY)"


def test_condor_argv_remote_pool() -> None:
    assert condor_argv(
        "condor_submit", "job.sub", pool="vocms4100.cern.ch"
    ) == ["condor_submit", "-pool", "vocms4100.cern.ch", "job.sub"]
    assert condor_argv(
        "condor_q", "-af", "JobStatus", pool="vocms4100.cern.ch"
    ) == ["condor_q", "-pool", "vocms4100.cern.ch", "-af", "JobStatus"]
    assert condor_argv(
        "condor_submit",
        "job.sub",
        pool="vocms4100.cern.ch",
        schedd="schedd.cern.ch",
    ) == [
        "condor_submit",
        "-pool",
        "vocms4100.cern.ch",
        "-remote",
        "schedd.cern.ch",
        "job.sub",
    ]


def test_campaign_constraint() -> None:
    assert campaign_constraint("camp") == 'TckestrelCampaign == "camp"'
    assert campaign_constraint("camp", dest="T1_US_FNAL") == (
        'TckestrelCampaign == "camp" && TckestrelDest == "T1_US_FNAL"'
    )
    assert campaign_constraint("camp", "T2_CH_CERN", "T1_US_FNAL") == (
        'TckestrelCampaign == "camp" && TckestrelSource == "T2_CH_CERN" '
        '&& TckestrelDest == "T1_US_FNAL"'
    )


def test_submit_cell_dry_run_writes_sub(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.delenv("X509_USER_PROXY", raising=False)
    config = load_config(fixtures_dir / "controller.yaml")
    recorder = RecordingCondor()
    result = submit_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        job_id="dry.0",
        out_dir=tmp_path / "job",
        backend=MappingBackend({CERN_LFN: CERN_PFN}),
        cache=PrefixCache(tmp_path / "cache.json"),
        condor=recorder,
        payload=_payload(tmp_path),
        submit=False,
    )
    assert result.result is None
    assert recorder.submitted == []
    text = result.submit_file.read_text(encoding="utf-8")
    assert "run job.json" in text
    assert '+DESIRED_Sites' in text
    assert '"T1_US_FNAL"' in text
    assert str(result.spec.executable) in text
    assert (tmp_path / "job" / "job.json").is_file()
    assert (tmp_path / "job" / "files.txt").is_file()
    assert (tmp_path / "job" / "logs").is_dir()
    assert (tmp_path / "job" / "run_xrdhover.sh").is_file()
    assert "run_xrdhover.sh" in text
    assert f"-C {DEFAULT_CMSSW}" in text
    assert "xrdhover" in text
    assert "logs/$(Cluster).$(Process).out" in text
    assert str((fixtures_dir / "campaign" / ".tckestrel" / "condor.log").resolve()) in text
    assert "when_to_transfer_output" in text
    assert "request_memory" in text
    assert "keep_claim_idle" in text
    assert "600" in text


def test_submit_cell_queues_via_backend(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.delenv("X509_USER_PROXY", raising=False)
    config = load_config(fixtures_dir / "controller.yaml")
    recorder = RecordingCondor()
    result = submit_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        job_id="live.0",
        out_dir=tmp_path / "job",
        backend=MappingBackend({CERN_LFN: CERN_PFN}),
        cache=PrefixCache(tmp_path / "cache.json"),
        condor=recorder,
        payload=_payload(tmp_path),
        submit=True,
    )
    assert result.result is not None
    assert result.result.cluster_proc == "100.0"
    assert len(recorder.submitted) == 1
    assert recorder.submitted[0].dest == "T1_US_FNAL"
    assert recorder.submitted[0].job_id == "live.0"
    rows = recorder.query("test-6cell", dest="T1_US_FNAL")
    assert len(rows) == 1
    assert rows[0].status == "Idle"


def test_submit_plan_queues_n_per_cell(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.delenv("X509_USER_PROXY", raising=False)
    config = load_config(fixtures_dir / "controller.yaml")
    recorder = RecordingCondor()
    jobs = submit_plan(
        config,
        backend=_campaign_backend(),
        cache=PrefixCache(tmp_path / "cache.json"),
        condor=recorder,
        payload=_payload(tmp_path),
        submit=True,
    )
    assert len(jobs) == 6
    dests = {(spec.source, spec.dest) for spec in recorder.submitted}
    assert dests == {
        ("T2_CH_CERN", "T1_US_FNAL"),
        ("T2_CH_CERN", "T1_DE_KIT"),
        ("T2_CH_CERN", "T2_US_UCSD"),
        ("T1_US_FNAL", "T2_CH_CERN"),
        ("T1_US_FNAL", "T1_DE_KIT"),
        ("T1_US_FNAL", "T2_US_UCSD"),
    }
    assert {spec.job_id for spec in recorder.submitted} == {
        f"{src}__{dst}" for src, dst in dests
    }
    assert {spec.run_id for spec in recorder.submitted} == {
        f"{src}__{dst}" for src, dst in dests
    }


def test_recording_query_and_remove() -> None:
    condor = RecordingCondor()
    condor.submit(
        SubmitSpec(
            executable=Path("/bin/xrdhover"),
            job_dir=Path("/tmp"),
            dest="T1_US_FNAL",
            campaign_id="camp",
            source="T2_CH_CERN",
            run_id="camp/T2_CH_CERN__T1_US_FNAL",
            job_id="a",
        )
    )
    condor.submit(
        SubmitSpec(
            executable=Path("/bin/xrdhover"),
            job_dir=Path("/tmp"),
            dest="T1_DE_KIT",
            campaign_id="camp",
            source="T2_CH_CERN",
            run_id="camp/T2_CH_CERN__T1_DE_KIT",
            job_id="b",
        )
    )
    condor.submit(
        SubmitSpec(
            executable=Path("/bin/xrdhover"),
            job_dir=Path("/tmp"),
            dest="T1_US_FNAL",
            campaign_id="other",
            source="T2_CH_CERN",
            run_id="other/T2_CH_CERN__T1_US_FNAL",
            job_id="c",
        )
    )
    assert len(condor.query("camp")) == 2
    assert len(condor.query("camp", dest="T1_US_FNAL")) == 1
    removed = condor.remove("camp", dest="T1_US_FNAL")
    assert removed == 1
    assert [job.job_id for job in condor.query("camp")] == ["b"]
    assert condor.query("other")[0].job_id == "c"
    assert condor.removed == [
        'TckestrelCampaign == "camp" && TckestrelDest == "T1_US_FNAL"'
    ]
    assert condor.remove("camp") == 1
    assert condor.query("camp") == []
