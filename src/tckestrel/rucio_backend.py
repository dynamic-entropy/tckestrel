"""Rucio LFN→PFN backends. Tests inject a mock; live import is optional."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from tckestrel.pfn import as_cms_lfn, bare_lfn

PACKAGED_RUCIO_CFG = Path(__file__).resolve().parent / "rucio.cfg"

CA_CERT_CANDIDATES = (
    "/cvmfs/cms.cern.ch/grid/etc/grid-security/certificates",
    "/etc/grid-security/certificates",
    "/etc/grid-security",
)


def packaged_rucio_config() -> Path:
    return PACKAGED_RUCIO_CFG


def resolve_ca_cert_dir() -> Path:
    """IGTF CA directory: X509_CERT_DIR, then CVMFS, then /etc/grid-security."""
    ordered: list[str] = []
    env = os.environ.get("X509_CERT_DIR")
    if env:
        ordered.append(env)
    ordered.extend(CA_CERT_CANDIDATES)
    seen: set[str] = set()
    for raw in ordered:
        key = str(Path(raw))
        if key in seen:
            continue
        seen.add(key)
        path = Path(raw)
        if path.is_dir():
            return path
    raise RuntimeError(
        "No IGTF CA directory found. Set X509_CERT_DIR, or use CVMFS "
        "(/cvmfs/cms.cern.ch/grid/etc/grid-security/certificates) "
        "or /etc/grid-security/certificates."
    )


def runtime_rucio_config_path() -> Path:
    override = os.environ.get("TCKESTREL_RUCIO_CFG")
    if override:
        return Path(override)
    cache_root = os.environ.get("XDG_CACHE_HOME")
    cache = Path(cache_root) if cache_root else Path.home() / ".cache"
    return cache / "tckestrel" / "rucio.cfg"


def _render_rucio_cfg(ca_cert: Path) -> str:
    if not PACKAGED_RUCIO_CFG.is_file():
        raise RuntimeError("packaged CMS rucio.cfg is missing from the tckestrel install")
    template = PACKAGED_RUCIO_CFG.read_text(encoding="utf-8")
    line = f"ca_cert = {ca_cert.as_posix()}"
    rendered, n = re.subn(r"(?m)^ca_cert\s*=\s*.*$", line, template, count=1)
    if n != 1:
        raise RuntimeError("packaged rucio.cfg has no ca_cert line")
    return rendered


def ensure_rucio_config() -> Path:
    """Use RUCIO_CONFIG if set, otherwise a CMS cfg with a host-local ca_cert."""
    existing = os.environ.get("RUCIO_CONFIG")
    if existing:
        return Path(existing)
    dest = runtime_rucio_config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_render_rucio_cfg(resolve_ca_cert_dir()), encoding="utf-8")
    os.environ["RUCIO_CONFIG"] = str(dest)
    return dest


class RucioBackend(Protocol):
    def lfns2pfns(self, rse: str, lfns: list[str]) -> dict[str, str]: ...


class MappingBackend:
    """Fixed map or factory. Counts API calls for cache tests."""

    def __init__(self, pfns: dict[str, str] | Callable[[str, list[str]], dict[str, str]]) -> None:
        self._pfns = pfns
        self.calls = 0

    def lfns2pfns(self, rse: str, lfns: list[str]) -> dict[str, str]:
        self.calls += 1
        if callable(self._pfns):
            return self._pfns(rse, lfns)
        return {lfn: self._pfns[lfn] for lfn in lfns}


def _rucio_failure(exc: BaseException) -> RuntimeError:
    name = type(exc).__name__
    if name in {"ConfigNotFound", "ConfigLoadingError"}:
        return RuntimeError(
            "Rucio configuration not found. Set RUCIO_CONFIG to a rucio.cfg "
            "and confirm `rucio whoami` (CMS VOMS proxy)."
        )
    return RuntimeError(f"Rucio: {exc}")


class LiveRucio:
    """RSEClient.lfns2pfns, then ReplicaClient.list_replicas."""

    def lfns2pfns(self, rse: str, lfns: list[str]) -> dict[str, str]:
        dids = [as_cms_lfn(lfn) for lfn in lfns]
        try:
            from rucio.client.rseclient import RSEClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("rucio client is not installed") from exc
        try:
            ensure_rucio_config()
            client = RSEClient()
            if hasattr(client, "lfns2pfns"):
                mapping = client.lfns2pfns(
                    rse=rse,
                    lfns=dids,
                    scheme="root",
                    operation="read",
                    protocol_domain="wan",
                )
                return _normalize_mapping(lfns, mapping)
            return _list_replicas(rse, lfns)
        except RuntimeError:
            raise
        except Exception as exc:
            raise _rucio_failure(exc) from exc


def _normalize_mapping(lfns: list[str], mapping: dict[str, str]) -> dict[str, str]:
    by_bare = {bare_lfn(key): value for key, value in mapping.items()}
    out: dict[str, str] = {}
    for lfn in lfns:
        pfn = mapping.get(lfn) or mapping.get(as_cms_lfn(lfn)) or by_bare.get(bare_lfn(lfn))
        if not pfn:
            raise RuntimeError(f"Rucio returned no PFN for {lfn}")
        out[lfn] = pfn
    return out


def pfns_from_replica_records(
    rse: str, lfns: list[str], records: list[dict[str, object]]
) -> dict[str, str]:
    found: dict[str, str] = {}
    for rec in records:
        name = str(rec.get("name") or "")
        rses = rec.get("rses") or {}
        urls: list[str] = []
        if isinstance(rses, dict):
            raw = rses.get(rse) or []
            if isinstance(raw, list):
                urls = [str(url) for url in raw]
        if not urls:
            pfns = rec.get("pfns") or {}
            if isinstance(pfns, dict):
                for url, meta in pfns.items():
                    if str(url).startswith("root://") and isinstance(meta, dict) and meta.get("rse") == rse:
                        urls = [str(url)]
                        break
        if urls:
            found[name] = urls[0]
    return _normalize_mapping(lfns, found)


def _list_replicas(rse: str, lfns: list[str]) -> dict[str, str]:
    from rucio.client.replicaclient import ReplicaClient  # type: ignore[import-not-found]

    dids = [{"scope": "cms", "name": bare_lfn(lfn)} for lfn in lfns]
    records = list(
        ReplicaClient().list_replicas(dids=dids, rse_expression=rse, schemes=["root"])
    )
    return pfns_from_replica_records(rse, lfns, records)
