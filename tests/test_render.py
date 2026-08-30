from pathlib import Path

import pytest

from tckestrel.cache import PrefixCache
from tckestrel.config import load_config
from tckestrel.render import (
    RenderError,
    format_duration,
    format_si_bit_rate,
    format_size,
    render_cell,
    validate_workload,
)
from tckestrel.rucio_backend import MappingBackend

CERN_LFN = "/store/mc/PREMIX/cern-fnal.root"
CERN_PFN = "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-fnal.root"


def test_format_si_bit_rate() -> None:
    assert format_si_bit_rate(0.017) == "17Mbps"
    assert format_si_bit_rate(0.1) == "100Mbps"
    assert format_si_bit_rate(1.0) == "1Gbps"


def test_format_duration() -> None:
    assert format_duration(7200) == "2h"
    assert format_duration(15) == "15s"
    assert format_duration(120) == "2m"


def test_format_size() -> None:
    assert format_size(16000000000) == "16GB"
    assert format_size(16 * 1024**3) == "16GiB"
    assert format_size(32_000_000) == "32MB"
    assert format_size(8_000_000) == "8MB"
    assert format_size(7) == "7"


def test_render_fixture_cell_shape(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    backend = MappingBackend({CERN_LFN: CERN_PFN})
    result = render_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        job_id="render.0",
        out_dir=tmp_path / "job",
        backend=backend,
        cache=PrefixCache(tmp_path / "cache.json"),
    )
    assert set(result.workload) == {
        "schema_version",
        "run_id",
        "duration",
        "seed",
        "auth",
        "targets",
        "client_tuning",
        "sinks",
    }
    assert result.workload["schema_version"] == 1
    assert result.workload["run_id"] == "T2_CH_CERN__T1_US_FNAL"
    assert result.workload["duration"] == "2h"
    assert result.workload["auth"] == {"mode": "x509"}
    target = result.workload["targets"][0]
    assert target["name"] == "T2_CH_CERN__T1_US_FNAL"
    assert target["endpoint"] == "root://eoscms.cern.ch:1094/"
    assert target["filelist"] == "files.txt"
    assert target["target_rate"] == "17Mbps"
    assert target["pattern"]["read_size"] == "8MB"
    assert target["pattern"]["max_bytes"] == "32MB"
    assert target["pattern"]["max_bytes"] != "auto"
    assert result.workload["sinks"]["job_id"] == "render.0"
    assert result.workload["sinks"]["pushgateway"]["url"] == "http://127.0.0.1:9091"
    assert result.workload["sinks"]["snapshot_interval"] == "15s"
    assert result.job_json.is_file()
    assert result.files_txt.read_text(encoding="utf-8") == (
        "/eos/cms/store/mc/PREMIX/cern-fnal.root\n"
    )


def test_render_link_ids(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    backend = MappingBackend({CERN_LFN: CERN_PFN})
    first = render_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        out_dir=tmp_path / "a",
        backend=backend,
        cache=PrefixCache(tmp_path / "cache.json"),
    )
    second = render_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        out_dir=tmp_path / "b",
        backend=backend,
        cache=PrefixCache(tmp_path / "cache.json"),
    )
    assert first.job_id == second.job_id == "T2_CH_CERN__T1_US_FNAL"
    assert first.run_id == second.run_id == "T2_CH_CERN__T1_US_FNAL"


def test_render_validate_stub(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    backend = MappingBackend({CERN_LFN: CERN_PFN})
    binary = tmp_path / "xrdhover"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    result = render_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        job_id="ok.0",
        out_dir=tmp_path / "job",
        backend=backend,
        cache=PrefixCache(tmp_path / "cache.json"),
        validate=validate_workload,
        xrdhover=binary,
    )
    assert result.job_json.is_file()


def test_render_validate_nonzero(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    backend = MappingBackend({CERN_LFN: CERN_PFN})
    binary = tmp_path / "xrdhover"
    binary.write_text("#!/bin/sh\necho bad rate >&2\nexit 2\n", encoding="utf-8")
    binary.chmod(0o755)
    with pytest.raises(RenderError, match="validate failed"):
        render_cell(
            config,
            "T2_CH_CERN",
            "T1_US_FNAL",
            out_dir=tmp_path / "job",
            backend=backend,
            cache=PrefixCache(tmp_path / "cache.json"),
            validate=validate_workload,
            xrdhover=binary,
        )
