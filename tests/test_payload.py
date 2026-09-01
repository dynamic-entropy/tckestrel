import tarfile
from pathlib import Path

import pytest
from helpers import dump_controller
from tckestrel.config import load_config
from tckestrel.payload import (
    DEFAULT_ARCH,
    PayloadError,
    cached_binary,
    ensure_payload,
    payload_arch_for_dest,
    release_url,
    resolve_release_version,
)


def _write_config(tmp_path: Path, fixtures_dir: Path, payload: dict | None = None) -> Path:
    return dump_controller(
        tmp_path / "controller.yaml",
        matrix=fixtures_dir / "matrix.csv",
        plan={"read_size_bytes": 1},
        payload=payload,
    )


def _make_tarball(
    tmp_path: Path, version: str, arch: str, build_os: str | None = None
) -> Path:
    pkg = tmp_path / "pkg" / f"xrdhover-{version}-{arch}"
    root = pkg / "bin"
    root.mkdir(parents=True)
    binary = root / "xrdhover"
    binary.write_bytes(b"#!/bin/sh\necho xrdhover\n")
    binary.chmod(0o755)
    if build_os is not None:
        (pkg / "BUILD_OS").write_text(f"{build_os}\n", encoding="utf-8")
    tarball = tmp_path / "xrdhover.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(pkg, arcname=f"xrdhover-{version}-{arch}")
    return tarball


def test_payload_arch_for_dest_is_amd64() -> None:
    assert payload_arch_for_dest("T1_DE_KIT") == DEFAULT_ARCH


def test_release_url() -> None:
    assert release_url("0.2.0", "linux-amd64").endswith(
        "/v0.2.0/xrdhover-0.2.0-linux-amd64.tar.gz"
    )


def test_resolve_release_version_passthrough() -> None:
    assert resolve_release_version("0.2.0") == "0.2.0"
    assert resolve_release_version("v0.3.0") == "0.3.0"


def test_resolve_latest_uses_github_tag(monkeypatch: object) -> None:
    class _Resp:
        def read(self) -> bytes:
            return b'{"tag_name": "v0.3.1"}'

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "tckestrel.payload.urllib.request.urlopen", lambda request: _Resp()
    )
    assert resolve_release_version("latest") == "0.3.1"


def test_ensure_uses_existing_cache(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: object
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    config = load_config(
        _write_config(
            tmp_path,
            fixtures_dir,
            {"cache_dir": str(tmp_path / "vendor"), "xrdhover_version": "0.2.0"},
        )
    )
    dest = cached_binary(config, DEFAULT_ARCH, "0.2.0")
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"#!/bin/sh\n")
    dest.chmod(0o755)

    def fail(url: str, path: Path) -> None:
        raise AssertionError(f"should not download {url}")

    result = ensure_payload(config, download=fail)
    assert result.fetched is False
    assert result.path == dest
    assert result.arch == DEFAULT_ARCH


def test_ensure_downloads_missing_binary(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    tarball = _make_tarball(tmp_path, "0.2.0", "linux-amd64")
    config = load_config(
        _write_config(
            tmp_path,
            fixtures_dir,
            {"cache_dir": str(tmp_path / "vendor"), "xrdhover_version": "0.2.0"},
        )
    )

    def copy_tarball(url: str, dest: Path) -> None:
        assert "linux-amd64" in url
        dest.write_bytes(tarball.read_bytes())

    result = ensure_payload(config, download=copy_tarball)
    assert result.fetched is True
    assert result.path.is_file()
    assert result.path.stat().st_mode & 0o111
    assert result.path.read_bytes().startswith(b"#!/bin/sh")


def test_ensure_second_arch(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    tarball = _make_tarball(tmp_path, "0.2.0", "linux-aarch64")
    config = load_config(
        _write_config(
            tmp_path,
            fixtures_dir,
            {"cache_dir": str(tmp_path / "vendor"), "xrdhover_version": "0.2.0"},
        )
    )

    def copy_tarball(url: str, dest: Path) -> None:
        assert "linux-aarch64" in url
        dest.write_bytes(tarball.read_bytes())

    result = ensure_payload(config, "linux-aarch64", download=copy_tarball)
    assert result.arch == "linux-aarch64"
    assert result.path == cached_binary(config, "linux-aarch64", "0.2.0")
    assert result.path.is_file()


def test_pinned_file_skips_download(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    pin = tmp_path / "pinned"
    pin.write_bytes(b"#!/bin/sh\n")
    pin.chmod(0o755)
    config = load_config(_write_config(tmp_path, fixtures_dir, {"binary": str(pin)}))

    def fail(url: str, path: Path) -> None:
        raise AssertionError(f"should not download {url}")

    result = ensure_payload(config, download=fail)
    assert result.path == pin
    assert result.fetched is False


def test_missing_pin_fails(tmp_path: Path, fixtures_dir: Path) -> None:
    pin = tmp_path / "missing-bin"
    config = load_config(_write_config(tmp_path, fixtures_dir, {"binary": str(pin)}))
    with pytest.raises(PayloadError, match="pinned"):
        ensure_payload(config, download=lambda url, dest: None)


def test_cache_root_file_conflicts(tmp_path: Path, fixtures_dir: Path) -> None:
    root = tmp_path / "vendor" / "xrdhover"
    root.parent.mkdir(parents=True)
    root.write_text("legacy", encoding="utf-8")
    config = load_config(
        _write_config(
            tmp_path,
            fixtures_dir,
            {"cache_dir": str(root), "xrdhover_version": "0.2.0"},
        )
    )
    with pytest.raises(PayloadError, match="cache root is a file"):
        ensure_payload(config, download=lambda url, dest: None)


def test_ensure_latest_uses_resolved_tag(tmp_path: Path, fixtures_dir: Path) -> None:
    tarball = _make_tarball(tmp_path, "0.3.1", "linux-amd64")
    config = load_config(
        _write_config(tmp_path, fixtures_dir, {"cache_dir": str(tmp_path / "vendor")})
    )
    assert config.payload.xrdhover_version == "latest"

    def copy_tarball(url: str, dest: Path) -> None:
        assert "/v0.3.1/xrdhover-0.3.1-linux-amd64.tar.gz" in url
        dest.write_bytes(tarball.read_bytes())

    result = ensure_payload(
        config, download=copy_tarball, resolve=lambda requested: "0.3.1"
    )
    assert result.fetched is True
    assert result.version == "0.3.1"
    assert result.path == cached_binary(config, DEFAULT_ARCH, "0.3.1")


def test_el9_build_os_is_accepted(tmp_path: Path, fixtures_dir: Path) -> None:
    tarball = _make_tarball(tmp_path, "0.2.0", "linux-amd64", build_os="el9-amd64")
    config = load_config(
        _write_config(
            tmp_path,
            fixtures_dir,
            {"cache_dir": str(tmp_path / "vendor"), "xrdhover_version": "0.2.0"},
        )
    )

    def copy_tarball(url: str, dest: Path) -> None:
        dest.write_bytes(tarball.read_bytes())

    result = ensure_payload(config, download=copy_tarball)
    assert result.fetched is True
    assert result.path.is_file()


def test_el10_build_os_is_rejected(tmp_path: Path, fixtures_dir: Path) -> None:
    tarball = _make_tarball(tmp_path, "0.2.0", "linux-amd64", build_os="el10-amd64")
    config = load_config(
        _write_config(
            tmp_path,
            fixtures_dir,
            {"cache_dir": str(tmp_path / "vendor"), "xrdhover_version": "0.2.0"},
        )
    )

    def copy_tarball(url: str, dest: Path) -> None:
        dest.write_bytes(tarball.read_bytes())

    with pytest.raises(PayloadError, match="el9 build"):
        ensure_payload(config, download=copy_tarball)
