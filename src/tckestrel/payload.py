"""Fetch and cache the xrdhover release binary for Condor transfer."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import URLError

from tckestrel.config import DEFAULT_XRDHOVER_VERSION, Config

DEFAULT_VERSION = DEFAULT_XRDHOVER_VERSION
DEFAULT_ARCH = "linux-amd64"
DEFAULT_DIR = Path("vendor") / "xrdhover"
LATEST_API = "https://api.github.com/repos/dynamic-entropy/xrdhover/releases/latest"
RELEASE_URL = (
    "https://github.com/dynamic-entropy/xrdhover/releases/download/"
    "v{version}/xrdhover-{version}-{arch}.tar.gz"
)

Downloader = Callable[[str, Path], None]
VersionResolver = Callable[[str], str]


class PayloadError(RuntimeError):
    """Release binary could not be resolved or fetched."""


@dataclass(frozen=True)
class Payload:
    path: Path
    version: str
    arch: str
    fetched: bool


def default_payload_dir() -> Path:
    return Path.home() / DEFAULT_DIR


def payload_arch_for_dest(dest: str) -> str:
    """WN architecture for ``DESIRED_Sites``. v1 is linux-amd64 for every dest."""
    _ = dest
    return DEFAULT_ARCH


def release_url(version: str, arch: str) -> str:
    return RELEASE_URL.format(version=version, arch=arch)


def resolve_release_version(requested: str) -> str:
    text = requested.strip()
    if not text:
        raise PayloadError("xrdhover_version is empty")
    if text.lower() != "latest":
        return text.lstrip("v")
    request = urllib.request.Request(
        LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "tckestrel",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode())
    except (URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayloadError(f"could not resolve latest xrdhover release: {exc}") from exc
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise PayloadError("latest xrdhover release has no tag_name")
    return tag.lstrip("v")


def payload_root(config: Config) -> Path:
    if config.xrdhover_dir is not None:
        return config.xrdhover_dir
    return default_payload_dir()


def cached_binary(config: Config, arch: str, version: str) -> Path:
    return payload_root(config) / version / arch / "xrdhover"


def payload_path(config: Config, arch: str, version: str) -> Path:
    if config.xrdhover is not None and arch == DEFAULT_ARCH:
        return config.xrdhover
    return cached_binary(config, arch, version)


def download_url(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, dest.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _install_from_tarball(tarball: Path, dest: Path) -> None:
    with tarfile.open(tarball, "r:gz") as archive:
        member = next(
            (
                item
                for item in archive.getmembers()
                if item.isfile()
                and (
                    Path(item.name).name == "xrdhover"
                    and (item.name.endswith("/bin/xrdhover") or item.name == "xrdhover")
                )
            ),
            None,
        )
        if member is None:
            raise PayloadError(f"tarball has no xrdhover binary: {tarball}")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise PayloadError(f"tarball member is not a file: {member.name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(extracted.read())
        tmp.chmod(0o755)
        tmp.replace(dest)


def ensure_payload(
    config: Config,
    arch: str | None = None,
    *,
    download: Downloader = download_url,
    resolve: VersionResolver = resolve_release_version,
) -> Payload:
    chosen = arch or DEFAULT_ARCH
    pinned = config.xrdhover is not None and chosen == DEFAULT_ARCH
    version = config.xrdhover_version if pinned else resolve(config.xrdhover_version)
    dest = payload_path(config, chosen, version)
    root = payload_root(config)
    if dest != config.xrdhover and root.exists() and root.is_file():
        raise PayloadError(
            f"payload cache root is a file: {root}. "
            f"Pin it with xrdhover: or replace it with a directory"
        )
    if dest.is_file() and os.access(dest, os.X_OK):
        return Payload(path=dest, version=version, arch=chosen, fetched=False)
    if dest.is_file():
        dest.chmod(0o755)
        return Payload(path=dest, version=version, arch=chosen, fetched=False)

    if pinned:
        raise PayloadError(f"pinned xrdhover is missing: {dest}")

    url = release_url(version, chosen)
    try:
        with tempfile.TemporaryDirectory(prefix="tckestrel-xrdhover-") as tmp:
            tarball = Path(tmp) / "xrdhover.tar.gz"
            download(url, tarball)
            _install_from_tarball(tarball, dest)
    except PayloadError:
        raise
    except URLError as exc:
        raise PayloadError(f"download failed: {url}: {exc}") from exc
    except OSError as exc:
        raise PayloadError(f"download failed: {url}: {exc}") from exc
    if not dest.is_file():
        raise PayloadError(f"payload missing after fetch: {dest}")
    dest.chmod(0o755)
    return Payload(path=dest, version=version, arch=chosen, fetched=True)
