"""tifxyz segments: the surface format of Volume Cartographer (VC3D).

A segment is a folder holding ``x.tif``, ``y.tif``, ``z.tif`` (one float per grid node: the scan coordinates of that
node, in voxels of the full-resolution volume) and ``meta.json``. Rules followed here are the ones read in the VC3D
source (``core/src/QuadSurface.cpp``, ``core/src/Segmentation.cpp``; see docs/USING_WITH_VC3D.md):

* ``meta.json`` must hold ``"type": "seg"``, a ``"uuid"`` string, ``"format": "tifxyz"`` and ``"scale": [sx, sy]``
  (grid nodes per voxel: 0.05 means one node every 20 voxels). ``"bbox": [[x0, y0, z0], [x1, y1, z1]]`` is optional.
* a node is invalid when its z is <= 0 (VC3D then stores -1, -1, -1); an optional ``mask.tif`` invalidates more nodes
  (first channel below 255 = invalid; it may be an integer multiple of the grid size);
* VC3D itself writes untiled, uncompressed 32-bit float TIFFs, and registers every OTHER ``*.tif`` of the folder as an
  extra channel: side files written next to a segment must therefore not be TIFFs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np

BANDS = ("x.tif", "y.tif", "z.tif")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,95}")


class TifxyzError(ValueError):
    """The folder is not a usable tifxyz segment; the message says what is wrong and what to do."""


def safe_name(text: str, fallback: str = "segment") -> str:
    """A folder-safe name made from any text (letters, digits, ``_``, ``-``, ``.``)."""
    s = re.sub(r"[^A-Za-z0-9_.\-]+", "_", str(text)).strip("._-")[:96]
    return s or fallback


def check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name or ""):
        raise TifxyzError("name: letters, digits, '_', '-' and '.' only, starting with a letter or a digit (96 characters at most)")
    return name


def find_tifxyz(d) -> Path:
    """The tifxyz folder itself, or the single folder below it that holds x.tif (unzipped archives, ``pages/<name>/``)."""
    d = Path(d)
    if (d / "x.tif").is_file():
        return d
    if not d.is_dir():
        raise TifxyzError(f"not a folder: {d}")
    found = sorted({p.parent for p in d.glob("*/x.tif")} | {p.parent for p in d.glob("*/*/x.tif")})
    if not found:
        raise TifxyzError(f"no tifxyz surface (x.tif, y.tif, z.tif, meta.json) in {d}")
    if len(found) > 1:
        raise TifxyzError(f"several tifxyz surfaces in {d}: point to one of them ({', '.join(p.name for p in found[:6])}…)")
    return found[0]


def read_meta(d) -> dict:
    f = Path(d) / "meta.json"
    if not f.is_file():
        return {}
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        raise TifxyzError(f"{f}: not valid JSON ({e})")
    if not isinstance(m, dict):
        raise TifxyzError(f"{f}: a JSON object is expected")
    return m


def grid_step(meta: dict, default_scale: float | None = None) -> tuple[int, float]:
    """Voxels between two grid nodes (integer) and the raw scale. Raises when the scale is unusable."""
    sc = meta.get("scale")
    if sc is None:
        if default_scale is None:
            raise TifxyzError('meta.json has no "scale" ([nodes per voxel in x, in y], for example [0.05, 0.05])')
        sc = [default_scale, default_scale]
    try:
        sx, sy = float(sc[0]), float(sc[1])
    except (TypeError, ValueError, IndexError):
        raise TifxyzError(f'meta.json: "scale" must be two numbers, got {sc!r}')
    if not (sx > 0 and sy > 0):
        raise TifxyzError(f'meta.json: "scale" must be positive, got {sc!r}')
    if abs(sx - sy) > 1e-6 * max(sx, sy):
        raise TifxyzError(f"this grid has a different step in x and y (scale {sc!r}): not supported yet")
    step = 1.0 / sx
    if abs(step - round(step)) > 0.02 or round(step) < 1:
        raise TifxyzError(f"the grid step is {step:.3f} voxels: an integer number of voxels is needed (resample it with the 'densify' command)")
    return int(round(step)), sx


def _tiff_shape(f: Path) -> tuple[int, int]:
    import tifffile
    with tifffile.TiffFile(str(f)) as t:
        p = t.pages[0]
        if p.samplesperpixel != 1:
            raise TifxyzError(f"{f.name}: one sample per pixel is expected, found {p.samplesperpixel}")
        return int(p.imagelength), int(p.imagewidth)


def inspect(d) -> dict:
    """Cheap summary of a segment folder (reads only the TIFF headers and meta.json)."""
    d = find_tifxyz(d)
    missing = [b for b in BANDS if not (d / b).is_file()]
    if missing:
        raise TifxyzError(f"{d}: missing {', '.join(missing)}")
    shapes = {_tiff_shape(d / b) for b in BANDS}
    if len(shapes) != 1:
        raise TifxyzError(f"{d}: x.tif, y.tif and z.tif do not have the same size")
    gh, gw = shapes.pop()
    meta = read_meta(d)
    warnings = []
    if not meta:
        warnings.append('no meta.json: a scale of 0.05 (one node every 20 voxels) is assumed')
    step, scale = grid_step(meta, default_scale=0.05)
    if meta and meta.get("type") not in (None, "seg"):
        warnings.append(f'meta.json: "type" is {meta.get("type")!r} (VC3D expects "seg")')
    if meta and meta.get("format") not in (None, "tifxyz"):
        warnings.append(f'meta.json: "format" is {meta.get("format")!r} (VC3D expects "tifxyz")')
    size = sum((d / b).stat().st_size for b in BANDS)
    return dict(path=str(d), id=str(meta.get("uuid") or d.name), folder=d.name, grid=[gh, gw], step=step, scale=scale,
                page=[(gh - 1) * step + 1, (gw - 1) * step + 1], bbox=meta.get("bbox"), has_mask=(d / "mask.tif").is_file(),
                area_cm2=meta.get("area_cm2"), bytes=int(size), modified=time.strftime("%Y-%m-%d %H:%M", time.localtime((d / "x.tif").stat().st_mtime)),
                warnings=warnings, meta_keys=sorted(meta))


def _mask_valid(d: Path, shape) -> np.ndarray | None:
    """Validity from mask.tif, following VC3D: first channel >= 255 = valid; the mask may be k times larger than the grid."""
    f = d / "mask.tif"
    if not f.is_file():
        return None
    import tifffile
    try:
        m = np.asarray(tifffile.imread(str(f)))
    except Exception:
        return None
    if m.ndim == 3:
        m = m[..., 0] if m.shape[-1] <= 4 else m[0]
    if m.ndim != 2:
        return None
    ok = m >= 255
    gh, gw = shape
    if ok.shape == (gh, gw):
        return ok
    if gh > 0 and gw > 0 and ok.shape[0] % gh == 0 and ok.shape[1] % gw == 0:
        ky, kx = ok.shape[0] // gh, ok.shape[1] // gw
        return ok.reshape(gh, ky, gw, kx).all((1, 3))
    return None


def read_grid(d):
    """→ P (rows, cols, 3) as (z, y, x) float32, valid mask, step (voxels between nodes), meta dict."""
    import tifffile
    d = find_tifxyz(d)
    info = inspect(d)
    X, Y, Z = [np.asarray(tifffile.imread(str(d / b))).astype(np.float32) for b in BANDS]
    valid = np.isfinite(X) & np.isfinite(Y) & np.isfinite(Z) & (Z > 0)
    m = _mask_valid(d, valid.shape)
    if m is not None:
        valid &= m
    if not valid.any():
        raise TifxyzError(f"{d}: no valid node (every z is <= 0, or the mask hides everything)")
    return np.stack([Z, Y, X], -1), valid, info["step"], read_meta(d)


def bbox_xyz(x, y, z, valid) -> list | None:
    """VC3D bounding box [[x0, y0, z0], [x1, y1, z1]] of the valid nodes."""
    if not valid.any():
        return None
    lo = [float(a[valid].min()) for a in (x, y, z)]
    hi = [float(a[valid].max()) for a in (x, y, z)]
    return [lo, hi]


def area_vx2(P, valid) -> float:
    """Area of the valid quads, in voxels² (P in any consistent axis order)."""
    q = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    if not q.any():
        return 0.0
    P = P.astype(np.float64)
    d1 = P[1:, 1:] - P[:-1, :-1]
    d2 = P[1:, :-1] - P[:-1, 1:]
    a = 0.5 * np.linalg.norm(np.cross(d1, d2), axis=-1)
    return float(a[q].sum())


def segment_meta(original: dict, uuid: str, scale: float, bbox, *, area_vx2_: float | None = None, voxel_um: float | None = None,
                 provenance: dict | None = None) -> dict:
    """meta.json for a NEW segment: every field of the original is kept, the fields VC3D checks are (re)written."""
    meta = dict(original or {})
    meta.update(type="seg", uuid=uuid, format="tifxyz", scale=[float(scale), float(scale)])
    if bbox is not None:
        meta["bbox"] = bbox
    else:
        meta.pop("bbox", None)
    meta["name"] = uuid
    if area_vx2_ is not None:
        meta["area_vx2"] = float(area_vx2_)
        if voxel_um:
            meta["area_cm2"] = float(area_vx2_) * (float(voxel_um) * 1e-4) ** 2
        else:
            meta.pop("area_cm2", None)
    meta["date_last_modified"] = time.strftime("%Y%m%d%H%M%S")
    for stale in ("components", "vc_open_data_lazy_placeholder"):
        meta.pop(stale, None)
    if provenance is not None:
        meta["surface_enhancer"] = provenance
    return meta


def write_tifxyz(dst, x, y, z, meta: dict, *, valid=None, mask: bool = False, side_files: dict | None = None) -> Path:
    """Write a NEW segment folder (refuses to touch an existing one). Written next door first, then renamed, so that a
    program scanning the parent folder never sees a half-written segment. ``side_files``: name → bytes or source path
    (never ``*.tif``: VC3D would take them for extra channels)."""
    import tifffile
    dst = Path(dst)
    if dst.exists():
        raise FileExistsError(f"{dst} already exists: an existing segment is never overwritten")
    if meta.get("uuid") != dst.name:
        raise TifxyzError(f'the folder name ({dst.name}) and the "uuid" of meta.json ({meta.get("uuid")}) must be the same for VC3D')
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".tmp_sr_{os.getpid()}_{dst.name}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    try:
        arrays = dict(x=np.asarray(x, np.float32), y=np.asarray(y, np.float32), z=np.asarray(z, np.float32))
        if valid is not None:
            for a in arrays.values():
                a[~valid] = -1.0
        for c, a in arrays.items():
            tifffile.imwrite(str(tmp / f"{c}.tif"), a, photometric="minisblack", rowsperstrip=min(256, a.shape[0]))
        if mask and valid is not None:
            tifffile.imwrite(str(tmp / "mask.tif"), valid.astype(np.uint8) * 255, photometric="minisblack")
        for name, src in (side_files or {}).items():
            if name.lower().endswith((".tif", ".tiff")) or "/" in name or "\\" in name:
                raise TifxyzError(f"side file {name!r}: no TIFF and no sub-folder next to a segment")
            if isinstance(src, (bytes, bytearray)):
                (tmp / name).write_bytes(src)
            else:
                shutil.copy2(src, tmp / name)
        (tmp / "meta.json.tmp").write_text(json.dumps(meta, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        os.replace(tmp / "meta.json.tmp", tmp / "meta.json")
        os.replace(tmp, dst)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return dst


def validate_for_vc3d(d) -> list[str]:
    """Problems that would stop VC3D from loading this folder (empty list = fine). Mirrors the checks read in its source."""
    d = Path(d)
    out = []
    try:
        meta = read_meta(d)
    except TifxyzError as e:
        return [str(e)]
    if not meta:
        return ["meta.json is missing"]
    if meta.get("type") != "seg":
        out.append('meta.json: "type" must be "seg"')
    if not isinstance(meta.get("uuid"), str) or not meta.get("uuid"):
        out.append('meta.json: "uuid" must be a non-empty string')
    elif meta["uuid"] != d.name:
        out.append(f'meta.json: "uuid" ({meta["uuid"]}) differs from the folder name ({d.name})')
    if meta.get("format") != "tifxyz":
        out.append('meta.json: "format" must be "tifxyz"')
    sc = meta.get("scale")
    if not (isinstance(sc, list) and len(sc) >= 2 and all(isinstance(v, (int, float)) and v > 0 for v in sc[:2])):
        out.append('meta.json: "scale" must be two positive numbers')
    bb = meta.get("bbox")
    if bb is not None and not (isinstance(bb, list) and len(bb) == 2 and all(isinstance(v, list) and len(v) == 3 for v in bb)):
        out.append('meta.json: "bbox" must be [[x0, y0, z0], [x1, y1, z1]]')
    shapes = set()
    for b in BANDS:
        if not (d / b).is_file():
            out.append(f"{b} is missing")
            continue
        try:
            import tifffile
            with tifffile.TiffFile(str(d / b)) as t:
                p = t.pages[0]
                shapes.add((p.imagelength, p.imagewidth))
                if p.samplesperpixel != 1:
                    out.append(f"{b}: one sample per pixel expected")
                if p.bitspersample not in (8, 16, 32, 64):
                    out.append(f"{b}: unsupported bits per sample ({p.bitspersample})")
        except Exception as e:
            out.append(f"{b}: unreadable ({e})")
    if len(shapes) > 1:
        out.append("x.tif, y.tif and z.tif do not have the same size")
    if (d / "overlapping").is_dir():
        out.append('an "overlapping" sub-folder is present (VC3D refuses it: it wants overlapping.json)')
    extra = sorted(p.name for p in d.glob("*.tif") if p.name not in BANDS + ("mask.tif",))
    if extra:
        out.append("note: VC3D will list these TIFFs as extra channels: " + ", ".join(extra[:6]))
    return out


# ───────────────────────────── zip in, zip out ─────────────────────────────
WANTED = set(BANDS) | {"meta.json", "mask.tif", "overlapping.json"}


def extract_zip(zip_path, dst_dir, max_bytes: int = 2 << 30) -> Path:
    """Extract ONE tifxyz segment from an uploaded zip into ``dst_dir`` and return its folder. Only the segment files are
    taken (x/y/z.tif, meta.json, mask.tif); paths inside the archive are never trusted."""
    dst_dir = Path(dst_dir)
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        raise TifxyzError(f"not a readable zip archive ({e})")
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        roots = sorted({str(Path(i.filename.replace("\\", "/")).parent.as_posix()) for i in infos if Path(i.filename.replace("\\", "/")).name == "x.tif"})
        if not roots:
            raise TifxyzError("no x.tif in this zip: zip the segment folder (x.tif, y.tif, z.tif, meta.json)")
        if len(roots) > 1:
            raise TifxyzError(f"this zip holds {len(roots)} segments: upload one segment per zip ({', '.join(r or '(top level)' for r in roots[:5])})")
        root = roots[0]
        prefix = "" if root in (".", "") else root + "/"
        take = [i for i in infos if i.filename.replace("\\", "/").startswith(prefix) and i.filename.replace("\\", "/")[len(prefix):] in WANTED]
        total = sum(i.file_size for i in take)
        if total > max_bytes:
            raise TifxyzError(f"this segment is {total / 1e6:.0f} MB once unzipped: over the upload limit ({max_bytes / 1e6:.0f} MB, see max_upload_mb)")
        folder = safe_name(Path(root).name if root not in (".", "") else Path(str(zip_path)).stem)
        out = dst_dir / folder
        out.mkdir(parents=True, exist_ok=True)
        for i in take:
            name = i.filename.replace("\\", "/")[len(prefix):]
            with zf.open(i) as src, open(out / name, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    return out


def zip_folders(zip_path, folders: dict) -> Path:
    """Write a zip: archive folder name → folder on disk (flat folders only). TIFFs are stored, the rest is deflated."""
    zip_path = Path(zip_path)
    tmp = zip_path.with_name(zip_path.name + f".{os.getpid()}.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for arc, folder in folders.items():
            for f in sorted(Path(folder).iterdir()):
                if f.is_file():
                    zf.write(f, f"{arc}/{f.name}", compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, zip_path)
    return zip_path
