"""Resolve a cell's LFNs to pinned root:// PFNs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tckestrel.cache import PrefixCache
from tckestrel.campaign import CampaignError, Link, load_links, load_sidecar_rows
from tckestrel.config import Config
from tckestrel.pfn import ParsedPfn, PfnError, apply_prefix, parse_root_pfn
from tckestrel.rucio_backend import LiveRucio, RucioBackend
from tckestrel.site_map import SiteMapError, load_default_rse


class ResolveError(ValueError):
    """Cell LFN list could not be stamped with PFNs."""


@dataclass(frozen=True)
class ResolvedSlice:
    source: str
    dest: str
    rse: str
    endpoint: str
    pfns: list[ParsedPfn]
    cache_hit: bool


def default_backend() -> RucioBackend:
    return LiveRucio()


def parse_cell(raw: str) -> tuple[str, str]:
    text = raw.strip()
    if "," in text:
        source, dest = text.split(",", 1)
    elif "__" in text:
        source, dest = text.split("__", 1)
    else:
        raise ResolveError("cell must be SOURCE,DEST")
    source, dest = source.strip(), dest.strip()
    if not source or not dest:
        raise ResolveError("cell must be SOURCE,DEST")
    return source, dest


def cache_file(config: Config) -> Path:
    if config.filelists_dir is None:
        raise ResolveError("filelists_dir is required to resolve PFNs")
    return config.filelists_dir / ".tckestrel" / "rse_prefix.json"


def find_site_map(config: Config, override: Path | None = None) -> Path | None:
    if override is not None:
        return override
    if config.site_map is not None:
        return config.site_map
    if config.filelists_dir is not None:
        candidate = config.filelists_dir / "site_map.csv"
        if candidate.is_file():
            return candidate
    return None


def pick_rse(
    *,
    source: str,
    link_rse: str,
    sidecar_rses: list[str | None],
    site_map: Path | None,
) -> str:
    if link_rse:
        return link_rse
    named = {rse for rse in sidecar_rses if rse}
    if len(named) == 1:
        return named.pop()
    if len(named) > 1:
        raise ResolveError("sidecar has multiple RSEs and links.csv rse is empty")
    if site_map is None:
        raise ResolveError(
            f"no RSE for {source}; set links.csv rse or site_map.csv"
        )
    try:
        return load_default_rse(site_map, source)
    except SiteMapError as exc:
        raise ResolveError(str(exc)) from exc


def _stamp(rse: str, lfns: list[str], backend: RucioBackend, cache: PrefixCache) -> tuple[list[ParsedPfn], bool]:
    template = cache.get(rse)
    if template is not None:
        return (
            [
                ParsedPfn(
                    host=template.host,
                    port=template.port,
                    path=apply_prefix(template.prefix, lfn),
                )
                for lfn in lfns
            ],
            True,
        )

    first = backend.lfns2pfns(rse, [lfns[0]])
    pfn = first.get(lfns[0])
    if not pfn:
        raise ResolveError(f"Rucio returned no PFN for {lfns[0]}")
    parse_root_pfn(pfn)
    template = cache.learn(rse, lfns[0], pfn)
    stamped = [
        ParsedPfn(
            host=template.host,
            port=template.port,
            path=apply_prefix(template.prefix, lfn),
        )
        for lfn in lfns
    ]
    hosts = {(item.host, item.port) for item in stamped}
    if len(hosts) != 1:
        raise ResolveError("slice PFNs do not share one (host, port)")
    return stamped, False


def resolve_cell(
    config: Config,
    source: str,
    dest: str,
    *,
    limit: int = 3,
    backend: RucioBackend | None = None,
    cache: PrefixCache | None = None,
    site_map: Path | None = None,
) -> ResolvedSlice:
    if config.filelists_dir is None:
        raise ResolveError("filelists_dir is required to resolve PFNs")
    if limit < 1:
        raise ResolveError("limit must be >= 1")

    try:
        links = load_links(config.filelists_dir)
    except CampaignError as exc:
        raise ResolveError(str(exc)) from exc
    link: Link | None = links.get((source, dest))
    if link is None:
        raise ResolveError(f"no links.csv row for {source},{dest}")

    try:
        rows = load_sidecar_rows(link.sidecar)
    except CampaignError as exc:
        raise ResolveError(str(exc)) from exc
    chosen = rows[:limit]
    lfns = [row.lfn for row in chosen]
    rse = pick_rse(
        source=source,
        link_rse=link.rse,
        sidecar_rses=[row.rse for row in chosen],
        site_map=find_site_map(config, site_map),
    )

    store = cache if cache is not None else PrefixCache(cache_file(config))
    client = backend if backend is not None else default_backend()
    try:
        pfns, cache_hit = _stamp(rse, lfns, client, store)
    except ResolveError:
        raise
    except (PfnError, RuntimeError) as exc:
        raise ResolveError(str(exc)) from exc
    except Exception as exc:
        raise ResolveError(str(exc)) from exc

    return ResolvedSlice(
        source=source,
        dest=dest,
        rse=rse,
        endpoint=pfns[0].endpoint,
        pfns=pfns,
        cache_hit=cache_hit,
    )
