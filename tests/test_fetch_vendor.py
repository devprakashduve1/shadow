"""Tests for scripts/fetch_vendor.py.

Deliberately does not hit the network — the download path is exercised by
actually running the script. What's tested here is the logic that decides
whether assets are usable, and the tar-extraction guard.
"""
from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_vendor  # noqa: E402


MONACO = fetch_vendor.monaco_package()
XTERM_PACKAGES = fetch_vendor.xterm_packages()
ARCHIVE_PREFIX = next(iter(MONACO.extract))


def _make_vendor(tmp_path: Path, rel_paths) -> Path:
    vendor = tmp_path / "monaco"
    for rel in rel_paths:
        target = vendor / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
    return vendor


def test_is_monaco_available_true_when_all_required_files_present(tmp_path: Path) -> None:
    vendor = _make_vendor(tmp_path, MONACO.required)
    assert fetch_vendor.is_monaco_available(vendor) is True


def test_is_monaco_available_false_when_a_required_file_is_missing(tmp_path: Path) -> None:
    """A partial extraction must not read as "ready" — the editor would load a
    blank page instead of showing the fetch instructions."""
    partial = MONACO.required[:-1]
    vendor = _make_vendor(tmp_path, partial)
    assert fetch_vendor.is_monaco_available(vendor) is False


def test_is_monaco_available_false_for_empty_dir(tmp_path: Path) -> None:
    assert fetch_vendor.is_monaco_available(tmp_path / "nothing-here") is False


def test_committed_host_html_exists_and_references_the_loader() -> None:
    """monaco_host.html is committed (unlike vs/), so this always holds."""
    host = Path(MONACO.dest) / "monaco_host.html"
    assert host.is_file()
    body = host.read_text()
    assert 'src="vs/loader.js"' in body
    # The two non-obvious requirements that make Monaco work under file://
    assert "getWorkerUrl" in body, "worker shim missing — Monaco will fail on file://"
    assert 'paths: { vs: "vs" }' in body, "relative vs path missing — loader would hit a CDN"


def _tar_with_member(tmp_path: Path, name: str) -> Path:
    """Builds a tarball containing one file member called `name`."""
    path = tmp_path / "evil.tgz"
    with tarfile.open(path, "w:gz") as archive:
        payload = b"pwned"
        info = tarfile.TarInfo(name=name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return path


def test_safe_members_rejects_path_traversal(tmp_path: Path) -> None:
    tar_path = _tar_with_member(tmp_path, f"{ARCHIVE_PREFIX}/../../evil.js")

    with tarfile.open(tar_path, "r:gz") as archive:
        with pytest.raises(SystemExit):
            list(fetch_vendor._safe_members(archive, ARCHIVE_PREFIX))


def test_safe_members_ignores_members_outside_the_prefix(tmp_path: Path) -> None:
    tar_path = _tar_with_member(tmp_path, "package/other/thing.js")

    with tarfile.open(tar_path, "r:gz") as archive:
        assert list(fetch_vendor._safe_members(archive, ARCHIVE_PREFIX)) == []


def test_safe_members_skips_symlinks(tmp_path: Path) -> None:
    """A symlink member could point anywhere on disk once extracted."""
    tar_path = tmp_path / "link.tgz"
    with tarfile.open(tar_path, "w:gz") as archive:
        info = tarfile.TarInfo(name=f"{ARCHIVE_PREFIX}/link.js")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)

    with tarfile.open(tar_path, "r:gz") as archive:
        assert list(fetch_vendor._safe_members(archive, ARCHIVE_PREFIX)) == []


def test_verify_rejects_a_mismatched_checksum() -> None:
    with pytest.raises(SystemExit, match="Checksum mismatch"):
        fetch_vendor._verify(b"not the real tarball", MONACO.sha256)


def test_verify_accepts_matching_payload() -> None:
    import hashlib

    payload = b"anything"
    fetch_vendor._verify(payload, hashlib.sha256(payload).hexdigest())  # must not raise


# -- xterm.js packages -------------------------------------------------------


def test_xterm_is_a_separate_vendored_package() -> None:
    """Two packages (xterm + its fit addon) both land in vendor/xterm/."""
    assert len(XTERM_PACKAGES) == 2
    assert {p.dest.name for p in XTERM_PACKAGES} == {"xterm"}


def test_xterm_packages_share_the_lib_directory() -> None:
    """They must merge rather than replace, or the second fetch would delete
    the first one's output."""
    libs = [p.dest / sub for p in XTERM_PACKAGES for sub in p.extract.values() if sub == "lib"]
    assert len(libs) == 2 and libs[0] == libs[1]
    assert fetch_vendor._shared_dest(XTERM_PACKAGES[0], "lib") is True


def test_monaco_vs_dir_is_not_shared() -> None:
    """Monaco owns vendor/monaco/vs alone, so it's safe to replace wholesale."""
    assert fetch_vendor._shared_dest(MONACO, "vs") is False


def test_is_xterm_available_false_for_empty_dir(tmp_path: Path) -> None:
    assert fetch_vendor.is_xterm_available(tmp_path / "nothing") is False


def test_is_xterm_available_true_when_complete(tmp_path: Path) -> None:
    vendor = tmp_path / "xterm"
    for rel in ("lib/xterm.js", "css/xterm.css", "lib/addon-fit.js"):
        target = vendor / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")

    assert fetch_vendor.is_xterm_available(vendor) is True


def test_is_xterm_available_false_when_the_addon_is_missing(tmp_path: Path) -> None:
    vendor = tmp_path / "xterm"
    for rel in ("lib/xterm.js", "css/xterm.css"):
        target = vendor / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")

    assert fetch_vendor.is_xterm_available(vendor) is False


def test_terminal_host_html_is_committed_and_wired() -> None:
    host = Path(fetch_vendor.VENDOR_ROOT) / "xterm" / "terminal_host.html"
    assert host.is_file()

    body = host.read_text()
    assert 'src="lib/xterm.js"' in body
    assert 'href="css/xterm.css"' in body
    # The two things that make it a real terminal rather than a text dump.
    assert "term.onData" in body, "keystrokes must reach the PTY"
    assert "onResize" in body, "size changes must reach the PTY"


def test_every_package_pins_a_sha256() -> None:
    """An unpinned download would run unverified JS inside the app."""
    for package in fetch_vendor.PACKAGES:
        assert len(package.sha256) == 64, f"{package.name} has no usable sha256"
