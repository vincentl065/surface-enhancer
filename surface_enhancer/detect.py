"""Which public scan was this segment traced on? A guess, from what the segment folder itself says.

Tried in this order, and the answer says which one worked:

1. **the id of the scan, written in the folder**: public scans are named ``<14 digits>-<voxel size>um-….zarr``; that id is
   looked for in ``meta.json`` (VC3D writes the traced volume as ``target_volume``; other tools use ``volume``), in the
   ``uuid`` and in the folder name (``…-on-20230205180739-7.91um.tifxyz``). An id found is certain.
2. **the name of the scroll** (``PHerc0125``…) in the same places; when that scroll has several scans, the one in which
   the surface fits is kept.
The geometry alone is NOT used to choose a scroll: it was tried and does not decide (a small segment of PHerc0125
"fits" inside eight other scrolls, which are all cylinders of about the same size). Without an id or a name in the
folder there is no guess, and the user picks the scan.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

WEB = Path(__file__).resolve().parent / "web"
ID_RE = re.compile(r"(?<!\d)(20\d{12})(?!\d)")
SCROLL_RE = re.compile(r"PHerc[\s._-]*(Paris[\s._-]*\d|\d{3,4}[A-Za-z]?)", re.I)


@lru_cache(maxsize=1)
def _scans() -> list[dict]:
    try:
        vols = json.loads((WEB / "public_volumes.json").read_text(encoding="utf-8"))["volumes"]
        index = json.loads((WEB / "scrolls" / "index.json").read_text(encoding="utf-8"))["volumes"]
    except (OSError, ValueError, KeyError):
        return []
    out = []
    for v in vols:
        name = v["volume"].removesuffix(".zarr")
        out.append(dict(url=v["url"], scroll=v["scroll"], name=name, id=name[:14], um=v.get("um"), overview=index.get(name)))
    return out


def _norm_scroll(text: str) -> str:
    g = re.sub(r"[\s._-]", "", text).lower()
    m = re.fullmatch(r"(\d+)([a-z]?)", g)
    return "pherc" + (f"{int(m.group(1)):04d}{m.group(2)}" if m else g)


def _strings(meta: dict, folder: Path) -> list[tuple[str, str]]:
    """(where it was read, text) for everything in the folder that may name a scan or a scroll."""
    out = [(f"“{k}” in meta.json", v) for k in ("target_volume", "volume", "volume_id", "source", "uuid", "name") for v in [meta.get(k)] if isinstance(v, str)]
    sr = meta.get("surface_enhancer") or meta.get("surface_retoucher")      # the second: exports made before the tool was renamed
    if isinstance(sr, dict) and isinstance(sr.get("volume"), str):
        out.append(("the retouch record in meta.json", sr["volume"]))
    out.append(("the name of the folder", folder.name))
    return out


def _fits(P, valid, scan: dict) -> float | None:
    """Share of the surface that lies inside the papyrus of this scan, by its low-resolution overview (None: no overview)."""
    ov = scan.get("overview")
    if not ov:
        return None
    nz, ny, nx = ov["size"]
    fz, fy, fx = ov["factor"]
    pts = P[valid]
    if len(pts) == 0:
        return 0.0
    pts = pts[:: max(1, len(pts) // 3000)]
    i = np.floor(pts / np.array([fz, fy, fx], np.float32)).astype(np.int64)
    inside = (i >= 0).all(1) & (i[:, 0] < nz) & (i[:, 1] < ny) & (i[:, 2] < nx)
    if inside.mean() < 0.98:
        return 0.0
    vol = _overview(ov["file"], nz, ny, nx, ov["cols"])
    if vol is None:
        return None
    j = i[inside]
    return float((vol[j[:, 0], j[:, 1], j[:, 2]] > 12).mean())


@lru_cache(maxsize=8)
def _overview(file: str, nz: int, ny: int, nx: int, cols: int):
    try:
        from PIL import Image
        m = np.asarray(Image.open(WEB / "scrolls" / file).convert("L"))
    except Exception:
        return None
    vol = np.zeros((nz, ny, nx), np.uint8)
    for k in range(nz):
        r, c = divmod(k, cols)
        vol[k] = m[r * ny:(r + 1) * ny, c * nx:(c + 1) * nx]
    return vol


def guess_scan(folder, meta: dict | None = None, grid=None) -> dict | None:
    """→ ``{url, scroll, name, how, sure}`` or None. ``grid`` = (P, valid) when already read (else read on demand)."""
    from . import tifxyz
    folder = Path(folder)
    scans = _scans()
    if not scans:
        return None
    if meta is None:
        try:
            meta = tifxyz.read_meta(folder)
        except tifxyz.TifxyzError:
            meta = {}
    answer = lambda s, how, sure: dict(url=s["url"], scroll=s["scroll"], name=s["name"], um=s["um"], how=how, sure=sure)
    texts = _strings(meta, folder)
    for where, text in texts:                                     # 1. the id of the scan
        for i in ID_RE.findall(text):
            hit = [s for s in scans if s["id"] == i]
            if hit:
                return answer(hit[0], f"scan id {i} read in {where}", True)

    def geometry():
        nonlocal grid
        if grid is None:
            try:
                P, valid, _, _ = tifxyz.read_grid(folder)
                grid = (P, valid)
            except Exception:
                grid = (None, None)
        return grid

    for where, text in texts:                                     # 2. the name of the scroll
        m = SCROLL_RE.search(text)
        if not m:
            continue
        key = _norm_scroll(m.group(1))
        hit = [s for s in scans if _norm_scroll(s["scroll"][5:]) == key]
        if len(hit) == 1:
            return answer(hit[0], f"scroll name read in {where} (its only public scan)", True)
        if len(hit) > 1:
            P, valid = geometry()
            if P is not None:
                ok = [(f, s) for s in hit for f in [_fits(P, valid, s)] if f is not None and f >= 0.8]
                if len(ok) == 1:
                    return answer(ok[0][1], f"scroll name read in {where}; the surface fits this scan of it only", True)
            return None
    return None
