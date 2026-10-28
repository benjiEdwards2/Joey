"""JY-260 phase 2: the local poster store (spec docs/specs/JY-260-posters.md, "Phase 2").

B. 2026-10-28: "We can complete a full replacement of all and then store them local to help with loading pages quicker."

Layout, one folder per Jellyfin item under POSTERS_DIR (NAS /volume1/Docker/joey/posters/out, mounted read-write into
joey-hub and read-only into joey-media at /data/posters/out):

    <jf_id>/<ver>.full.jpg      the 1000 x 1500 master (the review page, the Jellyfin write-back)
    <jf_id>/<ver>.<h>.jpg       pre-sized variants, h in VARIANTS (the heights the hub and the TV ask /img for)
    <jf_id>/meta.json           the sidecar: pick, sub-line, status, `ver` (the review page reads it)
    <jf_id>/current             the published version: /img serves <current>.<h>.jpg; absent = not served
    <jf_id>/orig.<ext>          the Jellyfin original, saved before the first write-back (never pruned)

`ver` hashes the template kit's version with the poster's words, so a template change (or a new season) makes a new
file name and re-renders; the old files are removed once the new version is published. Every write is atomic.
This module reads and writes local files only: no network.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

from PIL import Image

from hub import media_item

DEFAULT_DIR = "/data/posters/out"
VARIANTS = (120, 240, 400, 600)   # /img poster heights: _poster.html 120 / 240, /img default 400, TV + title page 600
FULL_FOR = (1280,)                # an /img height above the variants is served the master
VARIANT_QUALITY = 85


def out_dir() -> Path:
    return Path(os.environ.get("POSTERS_DIR", "").strip() or DEFAULT_DIR)


def version(template_version: str, text: str) -> str:
    return hashlib.sha256(f"{template_version}|{text}".encode("utf-8")).hexdigest()[:10]


def _folder(jf_id: str) -> Path | None:
    return out_dir() / jf_id if media_item.ITEM_RE.match(jf_id or "") else None


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem[:16] + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def variants(master: bytes) -> dict[int, bytes]:
    """The pre-sized JPEGs of a master, by height (2:3, LANCZOS, q85)."""
    out = {}
    with Image.open(io.BytesIO(master)) as im:
        im = im.convert("RGB")
        for h in VARIANTS:
            buf = io.BytesIO()
            im.resize((round(h * 2 / 3), h), Image.LANCZOS).save(buf, "JPEG", quality=VARIANT_QUALITY, optimize=True)
            out[h] = buf.getvalue()
    return out


def save(jf_id: str, ver: str, master: bytes, publish: bool = True) -> int:
    """Store a render as version `ver` (master + variants); publish it unless the item is reverted or held back.
    Older versions are removed once this one is written. -> bytes on disk for this version."""
    folder = _folder(jf_id)
    if folder is None:
        raise ValueError("bad item id")
    total = 0
    write_atomic(folder / f"{ver}.full.jpg", master)
    total += len(master)
    for h, body in variants(master).items():
        write_atomic(folder / f"{ver}.{h}.jpg", body)
        total += len(body)
    if publish:
        write_atomic(folder / "current", ver.encode("ascii"))
    for old in folder.glob("*.jpg"):
        if not old.name.startswith(f"{ver}.") and not old.name.startswith("orig."):
            with contextlib.suppress(OSError):
                old.unlink()
    return total


def current(jf_id: str) -> str | None:
    folder = _folder(jf_id)
    try:
        ver = (folder / "current").read_text(encoding="ascii").strip() if folder else ""
    except (OSError, UnicodeDecodeError):
        return None
    return ver if ver.isalnum() else None


def lookup(jf_id: str, h: int) -> Path | None:
    """The published file /img should serve for jf:<jf_id> at height h, or None (not stored, not published, a
    height the store does not hold, a bad id). One small read and one stat."""
    if h not in VARIANTS and h not in FULL_FOR:
        return None
    ver = current(jf_id)
    if ver is None:
        return None
    path = out_dir() / jf_id / (f"{ver}.{h}.jpg" if h in VARIANTS else f"{ver}.full.jpg")
    return path if path.is_file() else None


def master(jf_id: str, ver: str | None = None) -> Path | None:
    """The master JPEG of `ver` (default: the sidecar's version), or None."""
    folder = _folder(jf_id)
    ver = ver or (read_meta(jf_id) or {}).get("ver")
    if folder is None or not isinstance(ver, str) or not ver.isalnum():
        return None
    path = folder / f"{ver}.full.jpg"
    return path if path.is_file() else None


def publish(jf_id: str, on: bool) -> bool:
    """Serve (on) or stop serving (off) the item's stored poster: the per-item revert / restore. -> done."""
    folder = _folder(jf_id)
    if folder is None:
        return False
    if not on:
        with contextlib.suppress(FileNotFoundError):
            (folder / "current").unlink()
        return True
    ver = (read_meta(jf_id) or {}).get("ver")
    if not isinstance(ver, str) or master(jf_id, ver) is None:
        return False
    write_atomic(folder / "current", ver.encode("ascii"))
    return True


def read_meta(jf_id: str) -> dict | None:
    folder = _folder(jf_id)
    try:
        side = json.loads((folder / "meta.json").read_text(encoding="utf-8")) if folder else None
    except (OSError, ValueError):
        return None
    return side if isinstance(side, dict) else None


def write_meta(jf_id: str, side: dict) -> None:
    folder = _folder(jf_id)
    if folder is None:
        raise ValueError("bad item id")
    write_atomic(folder / "meta.json", json.dumps(side).encode("utf-8"))


def all_meta() -> list[dict]:
    try:
        folders = sorted(p for p in out_dir().iterdir() if p.is_dir())
    except OSError:
        return []
    out = []
    for folder in folders:
        side = read_meta(folder.name)
        if side and side.get("jf_id") == folder.name:
            out.append(side)
    return out


def orig_path(jf_id: str) -> Path | None:
    folder = _folder(jf_id)
    if folder is None:
        return None
    for ext in (".jpg", ".png", ".webp", ".gif"):
        path = folder / f"orig{ext}"
        if path.is_file():
            return path
    return None


def save_orig(jf_id: str, body: bytes, ext: str) -> Path:
    folder = _folder(jf_id)
    if folder is None or ext not in (".jpg", ".png", ".webp", ".gif"):
        raise ValueError("bad item id or image type")
    path = folder / f"orig{ext}"
    write_atomic(path, body)
    return path


def disk_use(jf_id: str) -> int:
    folder = _folder(jf_id)
    try:
        return sum(p.stat().st_size for p in folder.iterdir() if p.is_file()) if folder else 0
    except OSError:
        return 0
