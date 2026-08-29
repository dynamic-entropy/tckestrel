import pytest

from tckestrel.pfn import (
    apply_prefix,
    as_cms_lfn,
    derive_prefix,
    parse_root_pfn,
    PfnError,
)


def test_parse_cern_double_slash() -> None:
    parsed = parse_root_pfn(
        "root://eoscms.cern.ch:1094//eos/cms//store/mc/PREMIX/cern.root"
    )
    assert parsed.host == "eoscms.cern.ch"
    assert parsed.port == 1094
    assert parsed.path == "/eos/cms/store/mc/PREMIX/cern.root"
    assert parsed.endpoint == "root://eoscms.cern.ch:1094/"
    assert "//" not in parsed.path


def test_parse_fnal_path() -> None:
    parsed = parse_root_pfn(
        "root://cmsxrootd.fnal.gov:1094//pnfs/fnal.gov/usr/cms/WAX/11/store/mc/PREMIX/fnal.root"
    )
    assert parsed.host == "cmsxrootd.fnal.gov"
    assert parsed.path.startswith("/pnfs/")
    assert "/store/" in parsed.path


def test_reject_aaa_hosts() -> None:
    with pytest.raises(PfnError, match="AAA"):
        parse_root_pfn("root://cms-xrd-global.cern.ch:1094//store/mc/PREMIX/x.root")
    with pytest.raises(PfnError, match="AAA"):
        parse_root_pfn("root://cms-xrd-transit.cern.ch:1094//store/mc/PREMIX/x.root")


def test_prefix_roundtrip() -> None:
    lfn = "/store/mc/PREMIX/cern.root"
    path = "/eos/cms/store/mc/PREMIX/cern.root"
    assert derive_prefix(path, lfn) == "/eos/cms"
    assert apply_prefix("/eos/cms", lfn) == path
    assert as_cms_lfn(lfn) == "cms:/store/mc/PREMIX/cern.root"
