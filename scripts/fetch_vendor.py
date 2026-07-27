#!/usr/bin/env python3
"""Downloads the Code tab's vendored JavaScript into vendor/.

Two packages, both from npm, neither committed (see .gitignore) — run this once
after cloning:

    python scripts/fetch_vendor.py

- **Monaco Editor** (~24MB) — the code editor and diff viewer.
- **xterm.js** (~1MB) — the terminal renderer.

Stdlib only, matching how the rest of this codebase talks to the network (see
assistant/streaming.py). Every download is pinned by version *and* sha256: this
JavaScript runs inside the app with access to the Python bridge, so an unverified
download would be an obvious supply-chain hole.

Re-running is cheap and idempotent — present-and-complete assets are skipped
unless --force is given.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_ROOT = REPO_ROOT / "vendor"


@dataclass
class Package:
    """One npm tarball and where its contents go."""

    name: str  # human label
    url: str
    sha256: str
    dest: Path  # directory the extracted files land in
    # archive-prefix -> subdirectory under `dest`. npm tarballs put everything
    # under "package/", and we only want specific parts of it.
    extract: Dict[str, str] = field(default_factory=dict)
    # Paths (relative to `dest`) that must exist for the package to be usable.
    required: Tuple[str, ...] = ()

    def is_available(self) -> bool:
        return all((self.dest / rel).is_file() for rel in self.required)


MONACO_VERSION = "0.56.0"
XTERM_VERSION = "6.0.0"
XTERM_FIT_VERSION = "0.11.0"

PACKAGES: List[Package] = [
    Package(
        name=f"Monaco Editor {MONACO_VERSION}",
        url=f"https://registry.npmjs.org/monaco-editor/-/monaco-editor-{MONACO_VERSION}.tgz",
        sha256="b74bc4437205c194b779b0f21e5e7fcd3b4e9acbf3f7c8732a545d2059fb7412",
        dest=VENDOR_ROOT / "monaco",
        # Only the minified build. The dev build is ~80MB and buys nothing —
        # we never debug inside Monaco itself.
        extract={"package/min/vs": "vs"},
        required=("vs/loader.js", "vs/editor/editor.main.js", "vs/editor/editor.main.css"),
    ),
    Package(
        name=f"xterm.js {XTERM_VERSION}",
        url=f"https://registry.npmjs.org/@xterm/xterm/-/xterm-{XTERM_VERSION}.tgz",
        sha256="908e66e04af6c8dc6b00dd3b54de088e2e81e5ed866284fd6c2fb3c2d1c7a3f6",
        dest=VENDOR_ROOT / "xterm",
        extract={"package/lib": "lib", "package/css": "css"},
        required=("lib/xterm.js", "css/xterm.css"),
    ),
    Package(
        name=f"xterm fit addon {XTERM_FIT_VERSION}",
        url=f"https://registry.npmjs.org/@xterm/addon-fit/-/addon-fit-{XTERM_FIT_VERSION}.tgz",
        sha256="26003b4517a132b64e4ff228fd88a5fda3fff5e606c76093f6dcff772e9ecec0",
        dest=VENDOR_ROOT / "xterm",
        extract={"package/lib": "lib"},
        required=("lib/addon-fit.js",),
    ),
]


def monaco_package() -> Package:
    return PACKAGES[0]


def xterm_packages() -> List[Package]:
    return PACKAGES[1:]


def is_monaco_available(vendor_dir: Optional[Path] = None) -> bool:
    """True if Monaco's assets are complete.

    Imported by gui/ide/monaco.py so the Code tab can show actionable
    instructions instead of a blank white webview.
    """
    package = monaco_package()
    dest = Path(vendor_dir) if vendor_dir else package.dest
    return all((dest / rel).is_file() for rel in package.required)


def is_xterm_available(vendor_dir: Optional[Path] = None) -> bool:
    """True if xterm.js and its fit addon are both present."""
    dest = Path(vendor_dir) if vendor_dir else (VENDOR_ROOT / "xterm")
    needed = [rel for package in xterm_packages() for rel in package.required]
    return all((dest / rel).is_file() for rel in needed)


def _download(url: str) -> bytes:
    print(f"  downloading {url}")
    try:
        with urllib.request.urlopen(url, timeout=180) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise SystemExit(f"Download failed: {exc}\nAre you online?") from exc


def _verify(payload: bytes, expected_sha256: str) -> None:
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise SystemExit(
            "Checksum mismatch — refusing to extract.\n"
            f"  expected {expected_sha256}\n  actual   {actual}\n"
            "Either the pinned hash is stale (did you bump a version?) or the download "
            "was corrupted/tampered with."
        )
    print(f"  checksum OK ({actual[:16]}...)")


def _safe_members(archive: tarfile.TarFile, prefix: str):
    """Yields only regular files/dirs under `prefix`, rejecting path traversal.

    A tarball can name members like `../../etc/passwd` or ship symlinks pointing
    outside the extraction root; `extractall` follows both happily. Python 3.9
    has no `filter="data"`, so this does the checking by hand.
    """
    for member in archive.getmembers():
        if not member.name.startswith(prefix + "/"):
            continue
        if not (member.isfile() or member.isdir()):
            continue  # skip symlinks/devices/hardlinks outright
        target = Path(member.name)
        if target.is_absolute() or ".." in target.parts:
            raise SystemExit(f"Refusing to extract suspicious tar member: {member.name!r}")
        yield member


def fetch_package(package: Package, force: bool = False) -> None:
    if package.is_available() and not force:
        print(f"{package.name}: already present — skipping.")
        return

    print(f"{package.name}:")
    payload = _download(package.url)
    _verify(payload, package.sha256)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        tarball = tmp / "package.tgz"
        tarball.write_bytes(payload)

        with tarfile.open(tarball, "r:gz") as archive:
            for prefix, subdirectory in package.extract.items():
                members = list(_safe_members(archive, prefix))
                if not members:
                    raise SystemExit(
                        f"Archive has no {prefix}/ entries — did the package layout change?"
                    )
                archive.extractall(path=tmp, members=members)

                source = tmp / prefix
                target = package.dest / subdirectory
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    # Replace rather than merge, so a partial previous run can't
                    # leave stale files shadowing the new ones. Directories shared
                    # by two packages (xterm's lib/) merge per-file instead.
                    if len(package.extract) == 1 and not _shared_dest(package, subdirectory):
                        shutil.rmtree(target)
                        shutil.move(str(source), str(target))
                        continue
                    _merge_into(source, target)
                else:
                    shutil.move(str(source), str(target))

    if not package.is_available():
        missing = [rel for rel in package.required if not (package.dest / rel).is_file()]
        raise SystemExit(f"Extraction finished but these are still missing: {missing}")

    size = sum(f.stat().st_size for f in package.dest.rglob("*") if f.is_file()) / 1_000_000
    print(f"  installed at {package.dest} ({size:.0f}MB total in that directory)")


def _shared_dest(package: Package, subdirectory: str) -> bool:
    """True if another package also extracts into this directory.

    xterm.js and its fit addon both write into `vendor/xterm/lib`, so that
    directory must be merged rather than replaced or the second fetch would
    delete the first one's output.
    """
    target = package.dest / subdirectory
    return any(
        other is not package and (other.dest / sub) == target
        for other in PACKAGES
        for sub in other.extract.values()
    )


def _merge_into(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if item.is_dir():
            continue
        destination = target / item.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    parser.add_argument(
        "--only",
        choices=["monaco", "xterm"],
        help="fetch just one of the two (default: both)",
    )
    parser.add_argument(
        "--print-hashes",
        action="store_true",
        help="download and print each sha256 without extracting (for version bumps)",
    )
    args = parser.parse_args()

    selected = PACKAGES
    if args.only == "monaco":
        selected = [monaco_package()]
    elif args.only == "xterm":
        selected = xterm_packages()

    if args.print_hashes:
        for package in selected:
            print(f"{package.url}\n  {hashlib.sha256(_download(package.url)).hexdigest()}")
        return 0

    for package in selected:
        fetch_package(package, force=args.force)
    print("\nDone. Restart Shadow to pick up newly fetched assets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
