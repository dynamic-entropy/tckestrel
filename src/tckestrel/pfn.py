"""Parse and pin root:// PFNs. Reject AAA redirectors."""

from __future__ import annotations

from dataclasses import dataclass

AAA_HOSTS = frozenset(
    {
        "cms-xrd-global.cern.ch",
        "cms-xrd-transit.cern.ch",
    }
)


class PfnError(ValueError):
    """Invalid or rejected PFN."""


@dataclass(frozen=True)
class ParsedPfn:
    host: str
    port: int
    path: str

    @property
    def endpoint(self) -> str:
        return f"root://{self.host}:{self.port}/"


def as_cms_lfn(lfn: str) -> str:
    text = lfn.strip()
    if text.startswith("cms:"):
        return text
    if not text.startswith("/"):
        text = "/" + text
    return f"cms:{text}"


def bare_lfn(lfn: str) -> str:
    text = lfn.strip()
    if text.startswith("cms:"):
        text = text[4:]
    if not text.startswith("/"):
        text = "/" + text
    return text


def is_aaa_host(host: str) -> bool:
    return host.lower() in AAA_HOSTS or "cms-xrd-global" in host.lower() or "cms-xrd-transit" in host.lower()


def parse_root_pfn(raw: str) -> ParsedPfn:
    pfn = raw.strip()
    if not pfn.startswith("root://"):
        raise PfnError(f"PFN is not root:// : {raw!r}")
    rest = pfn[len("root://") :]
    if "/" not in rest:
        raise PfnError(f"PFN has no path: {raw!r}")
    netloc, path = rest.split("/", 1)
    if not netloc:
        raise PfnError(f"PFN has no host: {raw!r}")
    if ":" in netloc:
        host, port_s = netloc.rsplit(":", 1)
        try:
            port = int(port_s)
        except ValueError as exc:
            raise PfnError(f"PFN has a bad port: {raw!r}") from exc
    else:
        host, port = netloc, 1094
    if is_aaa_host(host):
        raise PfnError(f"AAA host rejected: {host}")
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if "/store/" not in path and not path.startswith("/store"):
        raise PfnError(f"PFN path has no /store/: {raw!r}")
    return ParsedPfn(host=host, port=port, path=path)


def derive_prefix(path: str, lfn: str) -> str:
    name = bare_lfn(lfn)
    if path.endswith(name):
        return path[: -len(name)]
    raise PfnError(f"cannot derive prefix: path={path!r} lfn={name!r}")


def apply_prefix(prefix: str, lfn: str) -> str:
    return prefix.rstrip("/") + bare_lfn(lfn)
