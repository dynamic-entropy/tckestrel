import os
from pathlib import Path

import pytest
import yaml

from tckestrel.cache import PrefixCache
from tckestrel.config import load_config
from tckestrel.campaign import SidecarRow
from tckestrel.resolve import ResolveError, choose_sidecar_rows, resolve_cell
from tckestrel.rucio_backend import (
    MappingBackend,
    ensure_rucio_config,
    packaged_rucio_config,
    pfns_from_replica_records,
    resolve_ca_cert_dir,
)
from tckestrel.site_map import load_default_rse


CERN_LFN = "/store/mc/PREMIX/cern-fnal.root"
CERN_PFN = "root://eoscms.cern.ch:1094//eos/cms/store/mc/PREMIX/cern-fnal.root"
FNAL_A = "/store/mc/PREMIX/fnal-kit-a.root"
FNAL_B = "/store/mc/PREMIX/fnal-kit-b.root"


def _cern_map(rse: str, lfns: list[str]) -> dict[str, str]:
    return {lfn: f"root://eoscms.cern.ch:1094//eos/cms{lfn}" for lfn in lfns}


def test_choose_sidecar_rows_fills_job_wall() -> None:
    rows = [
        SidecarRow("/a", 4_000_000_000, "R"),
        SidecarRow("/b", 4_000_000_000, "R"),
        SidecarRow("/c", 4_000_000_000, "R"),
    ]
    assert [r.lfn for r in choose_sidecar_rows(rows, 8_000_000_000)] == ["/a", "/b"]
    unsized = [SidecarRow("/a", None, None), SidecarRow("/b", None, None)]
    assert [r.lfn for r in choose_sidecar_rows(unsized, 16_000_000_000)] == ["/a"]
    with pytest.raises(ResolveError, match="no LFNs"):
        choose_sidecar_rows([], 1)


def test_eos_double_slash_normalized(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    backend = MappingBackend(
        {CERN_LFN: "root://eoscms.cern.ch:1094//eos/cms//store/mc/PREMIX/cern-fnal.root"}
    )
    result = resolve_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        backend=backend,
        cache=PrefixCache(tmp_path / "cache.json"),
    )
    assert result.pfns[0].path == "/eos/cms/store/mc/PREMIX/cern-fnal.root"
    assert "//" not in result.pfns[0].path


def test_resolve_fixture_cell(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    backend = MappingBackend({CERN_LFN: CERN_PFN})
    result = resolve_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        backend=backend,
        cache=PrefixCache(tmp_path / "cache.json"),
    )
    assert result.rse == "T2_CH_CERN"
    assert result.endpoint == "root://eoscms.cern.ch:1094/"
    assert result.pfns[0].path == "/eos/cms/store/mc/PREMIX/cern-fnal.root"
    assert result.cache_hit is False
    assert backend.calls == 1


def test_aaa_host_fails(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    backend = MappingBackend(
        {CERN_LFN: "root://cms-xrd-global.cern.ch:1094//store/mc/PREMIX/cern-fnal.root"}
    )
    with pytest.raises(ResolveError, match="AAA"):
        resolve_cell(
            config,
            "T2_CH_CERN",
            "T1_US_FNAL",
            backend=backend,
            cache=PrefixCache(tmp_path / "cache.json"),
        )
    assert not (tmp_path / "cache.json").exists()


def test_cache_hit_skips_api(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    cache_path = tmp_path / "cache.json"
    backend = MappingBackend(_cern_map)
    first = resolve_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        backend=backend,
        cache=PrefixCache(cache_path),
    )
    assert backend.calls == 1
    assert first.cache_hit is False

    second = resolve_cell(
        config,
        "T2_CH_CERN",
        "T1_US_FNAL",
        backend=backend,
        cache=PrefixCache(cache_path),
    )
    assert backend.calls == 1
    assert second.cache_hit is True
    assert second.pfns[0].path == first.pfns[0].path


def test_cold_slice_calls_api_once(fixtures_dir: Path, tmp_path: Path) -> None:
    config = load_config(fixtures_dir / "controller.yaml")
    backend = MappingBackend(
        lambda rse, lfns: {
            lfn: f"root://cmsxrootd.fnal.gov:1094//pnfs/fnal.gov/usr/cms/WAX/11{lfn}"
            for lfn in lfns
        }
    )
    result = resolve_cell(
        config,
        "T1_US_FNAL",
        "T1_DE_KIT",
        backend=backend,
        cache=PrefixCache(tmp_path / "cache.json"),
    )
    assert backend.calls == 1
    assert [pfn.path for pfn in result.pfns] == [
        f"/pnfs/fnal.gov/usr/cms/WAX/11{FNAL_A}",
        f"/pnfs/fnal.gov/usr/cms/WAX/11{FNAL_B}",
    ]


def test_old_premix_uses_site_map(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    (campaign / "filelists").mkdir(parents=True)
    (campaign / "links.csv").write_text(
        "source,dest,rate_gbps,rse,file_list,n_files,selected_bytes,target_bytes,shortfall\n"
        "T2_CH_CERN,T1_DE_KIT,0.017,,filelists/T2_CH_CERN__T1_DE_KIT.csv,1,100,100,false\n",
        encoding="utf-8",
    )
    (campaign / "filelists" / "T2_CH_CERN__T1_DE_KIT.csv").write_text(
        "file,size\n/store/mc/PREMIX/old.root,100\n",
        encoding="utf-8",
    )
    site_map = tmp_path / "site_map.csv"
    site_map.write_text(
        "cms_site,pnn,disk_rses\nT2_CH_CERN,T2_CH_CERN,T2_CH_CERN_Disk\n",
        encoding="utf-8",
    )
    matrix = tmp_path / "matrix.csv"
    matrix.write_text(
        "source,T1_DE_KIT\nT2_CH_CERN,0.017\n",
        encoding="utf-8",
    )
    yaml_path = tmp_path / "controller.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "campaign_id": "old",
                "matrix": str(matrix),
                "filelists_dir": str(campaign),
                "site_map": str(site_map),
                "max_rate_per_job_gbps": 0.1,
                "default_inflight": 1,
                "chunk_bytes": 1,
                "prom_url": "http://127.0.0.1:9091",
            }
        ),
        encoding="utf-8",
    )

    seen: list[str] = []

    def factory(rse: str, lfns: list[str]) -> dict[str, str]:
        seen.append(rse)
        return {lfn: f"root://eoscms.cern.ch:1094//eos/cms{lfn}" for lfn in lfns}

    config = load_config(yaml_path)
    result = resolve_cell(
        config,
        "T2_CH_CERN",
        "T1_DE_KIT",
        backend=MappingBackend(factory),
        cache=PrefixCache(tmp_path / "cache.json"),
    )
    assert seen == ["T2_CH_CERN_Disk"]
    assert result.rse == "T2_CH_CERN_Disk"
    assert result.pfns[0].path == "/eos/cms/store/mc/PREMIX/old.root"
    assert load_default_rse(site_map, "T2_CH_CERN") == "T2_CH_CERN_Disk"


def test_packaged_rucio_config(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.delenv("RUCIO_CONFIG", raising=False)
    certs = tmp_path / "grid-security" / "certificates"
    certs.mkdir(parents=True)
    monkeypatch.setenv("X509_CERT_DIR", str(certs))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    path = ensure_rucio_config()
    assert path != packaged_rucio_config()
    text = path.read_text(encoding="utf-8")
    assert "http://cms-rucio.cern.ch" in text
    assert "https://cms-rucio-auth.cern.ch" in text
    assert "auth_type = x509_proxy" in text
    assert f"ca_cert = {certs.as_posix()}" in text
    assert path.as_posix() == os.environ["RUCIO_CONFIG"]
    assert resolve_ca_cert_dir() == certs
    template = packaged_rucio_config().read_text(encoding="utf-8")
    assert "/cvmfs/cms.cern.ch/grid/etc/grid-security/certificates" in template


def test_ca_cert_falls_back_to_etc_grid_security(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.delenv("X509_CERT_DIR", raising=False)
    local = tmp_path / "etc" / "grid-security" / "certificates"
    local.mkdir(parents=True)
    monkeypatch.setattr(
        "tckestrel.rucio_backend.CA_CERT_CANDIDATES",
        ("/no/cvmfs/certificates", str(local), str(local.parent)),
    )
    assert resolve_ca_cert_dir() == local


def test_replica_records_fallback() -> None:
    lfn = "/store/mc/PREMIX/x.root"
    mapping = pfns_from_replica_records(
        "T2_CH_CERN",
        [lfn],
        [
            {
                "name": lfn,
                "rses": {"T2_CH_CERN": [CERN_PFN.replace("cern-fnal", "x")]},
            }
        ],
    )
    assert mapping[lfn].startswith("root://eoscms.cern.ch:1094/")
