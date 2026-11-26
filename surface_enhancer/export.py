"""Export of a retouched surface: always a NEW tifxyz segment, never over the original, never over an earlier export.

Only the nodes you moved change; every other node keeps the exact value of the original file. Next to the segment go
the pieces needed to audit or redo the work: the offset field (voxels along the original normal, per node), the
journal of gestures, the marked areas and a provenance record.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import numpy as np

from . import __version__, tifxyz


def retouched_arrays(seg, grid: str = "working"):
    """→ (x, y, z, valid, moved, scale, had_mask, added) of the retouched surface, on the CURRENT grid (larger than the
    original one when the surface was extended). Nodes of the original surface that were not moved keep the exact value
    of the original file. ``grid='original'`` gives back the node layout of the source segment when it was resampled
    finer for the retouch (one node out of F, aligned on the source nodes)."""
    import tifffile
    F = int(seg.cfg.get("densified_factor") or 1)
    v0 = seg.d / "versions" / "v000"
    Pc = seg.P0 + seg.h[..., None] * seg.N
    moved = seg.valide & (seg.h != 0)
    ov, ou = (int(v) for v in getattr(seg, "org", (0, 0)))
    base_valid = seg._base["valide"] if getattr(seg, "_base", None) else seg.valide
    g0, w0 = base_valid.shape
    was = np.zeros(seg.valide.shape, bool)
    was[ov:ov + g0, ou:ou + w0] = base_valid
    added = seg.valide & ~was
    work = {c: np.where(seg.valide, Pc[..., i], -1.0).astype(np.float32) for i, c in enumerate("zyx")}
    if grid == "original" and F > 1:
        sv, su = ov % F, ou % F
        iv, iu = (ov - sv) // F, (ou - su) // F
        arr = {c: np.ascontiguousarray(work[c][sv::F, su::F]) for c in "xyz"}
        src = {c: np.asarray(tifffile.imread(str(v0 / "source" / f"{c}.tif"))).astype(np.float32) for c in "xyz"}
        gs, ws = src["x"].shape
        sub_moved, sub_added = moved[sv::F, su::F], added[sv::F, su::F]
        keep = np.isfinite(src["z"]) & (src["z"] > 0) & ~sub_moved[iv:iv + gs, iu:iu + ws] & base_valid[::F, ::F]
        for c in "xyz":
            arr[c][iv:iv + gs, iu:iu + ws][keep] = src[c][keep]
        scale, mask_src, moved, added = 1.0 / (seg.pas * F), v0 / "source", sub_moved, sub_added
    else:
        arr = work
        keep = base_valid & ~moved[ov:ov + g0, ou:ou + w0]
        for c in "xyz":
            o = np.asarray(tifffile.imread(str(v0 / "tifxyz" / f"{c}.tif"))).astype(np.float32)
            arr[c][ov:ov + g0, ou:ou + w0][keep] = o[keep]
        scale, mask_src = 1.0 / seg.pas, v0 / "tifxyz"
    valid = np.isfinite(arr["x"]) & np.isfinite(arr["y"]) & np.isfinite(arr["z"]) & (arr["z"] > 0)
    return arr["x"], arr["y"], arr["z"], valid, moved, scale, (mask_src / "mask.tif").is_file(), added


def default_id(seg) -> str:
    base = tifxyz.safe_name((seg.cfg.get("meta_origine") or {}).get("uuid") or Path(seg.cfg.get("surface", seg.nom)).name or seg.nom)
    return f"{base[:70]}_rt{time.strftime('%Y%m%d%H%M%S')}"


def provenance(seg, uuid, grid, moved, added=None) -> dict:
    h = seg.h
    nz = np.abs(h[seg.valide & (h != 0)])
    vol = str(seg.cfg.get("volume") or "")
    return dict(tool="surface-enhancer", tool_version=__version__, exported=time.strftime("%Y-%m-%d %H:%M:%S"), id=uuid,
                source_id=(seg.cfg.get("meta_origine") or {}).get("uuid") or Path(seg.cfg.get("surface", "")).name,
                volume=vol if vol.startswith(("s3://", "http://", "https://")) else Path(vol).name,
                working_version=seg.version, gestures=len(seg.pile), journal_events=int(seg.n_evt), grid=grid,
                working_step_vx=int(seg.pas), resampled_factor=int(seg.cfg.get("densified_factor") or 1),
                nodes_moved=int(moved.sum()), nodes_added=int(added.sum()) if added is not None else 0, extensions=len(getattr(seg, "ext", ()) or ()),
                original_grid_origin=[int(v) for v in getattr(seg, "org", (0, 0))], offset_max_vx=round(float(nz.max()), 3) if nz.size else 0.0,
                offset_median_vx=round(float(np.median(nz)), 3) if nz.size else 0.0,
                note="Only the moved nodes differ from the source segment. Offsets are measured along the smoothed normal of the source surface.")


def export_segment(seg, *, uuid=None, dest_dir=None, grid="working", sidecar=True) -> dict:
    """Write ``<dest_dir>/<uuid>/`` (default: the exports folder of the segment). Returns a summary with the VC3D check."""
    if grid not in ("working", "original"):
        raise ValueError('grid must be "working" or "original"')
    uuid = tifxyz.check_name(uuid or default_id(seg))
    dest_dir = Path(dest_dir) if dest_dir else seg.d / "exports"
    dst = dest_dir / uuid
    if dst.exists():
        raise FileExistsError(f"{dst} already exists: choose another id (an existing segment is never overwritten)")
    orig = (seg.cfg.get("surface") and Path(seg.cfg["surface"]))
    if orig and dst.resolve() == orig.resolve():
        raise FileExistsError("refusing to write over the original segment")
    x, y, z, valid, moved, scale, had_mask, added = retouched_arrays(seg, grid)
    P = np.stack([z, y, x], -1)
    um = float(seg.um) if seg.cfg.get("um_known", True) else None
    prov = provenance(seg, uuid, grid, moved, added)
    meta = tifxyz.segment_meta(seg.cfg.get("meta_origine") or {}, uuid, scale, tifxyz.bbox_xyz(x, y, z, valid),
                               area_vx2_=tifxyz.area_vx2(P, valid), voxel_um=um, provenance=prov)
    side = {}
    src_dir = seg.d / "versions" / "v000" / ("source" if (grid == "original" and int(seg.cfg.get("densified_factor") or 1) > 1) else "tifxyz")
    for f in sorted(src_dir.iterdir()):          # small companions of the source (overlapping.json, notes…), never TIFFs
        if f.is_file() and f.suffix.lower() in (".json", ".txt", ".npy") and f.name != "meta.json" and f.stat().st_size < 50e6:
            side[f.name] = f
    tifxyz.write_tifxyz(dst, x, y, z, meta, valid=valid, mask=had_mask, side_files=side)
    out = dict(folder=str(dst), id=uuid, grid=grid, shape=list(x.shape), nodes_moved=int(moved.sum()), nodes_added=prov["nodes_added"], offset_max_vx=prov["offset_max_vx"],
               vc3d_problems=[p for p in tifxyz.validate_for_vc3d(dst) if not p.startswith("note:")])
    if sidecar:
        out["retouch_folder"] = str(write_sidecar(seg, seg.d / "exports" / f"{uuid}.retouch", prov, dst))
    return out


def write_sidecar(seg, folder: Path, prov: dict, segment_folder=None) -> Path:
    """The record of the retouch: offset field, journal of gestures, marked areas, provenance."""
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=False)
    np.save(folder / "offset_along_normal.npy", seg.h.astype(np.float32))
    j = seg.d / "journal.jsonl"
    (folder / "journal.jsonl").write_bytes(j.read_bytes() if j.exists() else b"")
    Image.fromarray(seg.zones.astype(np.uint8) * 255).save(folder / "marked_areas.png")
    rec = dict(prov, written_to=str(segment_folder) if segment_folder else None)
    (folder / "provenance.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "README.txt").write_text(
        "Surface Enhancer — record of a retouch\n\n"
        "offset_along_normal.npy  float32, one value per grid node of the WORKING grid (the enlarged one if the surface was extended;\n"
        "                         provenance.json gives where the original grid starts in it): how far the node was moved, in voxels,\n"
        "                         along the smoothed normal of the source surface (0 = untouched). Shape = working grid.\n"
        "journal.jsonl            every gesture, in order (tool, parameters, touched rectangle, score before/after), undo and redo included.\n"
        "                         Tool and parameter names are documented in docs/DATA_LAYOUT.md of the project.\n"
        "marked_areas.png         the areas marked as problems (255 = marked), one pixel per grid node.\n"
        "provenance.json          source segment, volume, version, counts.\n", encoding="utf-8")
    return folder


def export_to_segments_dir(seg, segments_dir, *, uuid=None, grid="original") -> dict:
    """Write the retouched surface as a NEW segment of a VC3D segments folder (``paths/``…). The record of the retouch
    stays in the Surface Enhancer data folder, so that the VC3D folder only receives a plain segment."""
    segments_dir = Path(segments_dir)
    if not segments_dir.is_dir():
        raise FileNotFoundError(f"segments folder not found: {segments_dir}")
    r = export_segment(seg, uuid=uuid, dest_dir=segments_dir, grid=grid, sidecar=True)
    r["segments_dir"] = str(segments_dir)
    return r


def download_bytes(seg, what: str = "bundle", grid: str = "working") -> tuple[str, bytes, str]:
    """→ (file name, content, mime type) for the Download buttons. ``what``: segment | offset | journal | bundle."""
    import tempfile
    import zipfile
    stamp = time.strftime("%Y%m%d%H%M%S")
    if what == "offset":
        b = io.BytesIO()
        np.save(b, seg.h.astype(np.float32))
        return f"{seg.nom}_offset_along_normal_{stamp}.npy", b.getvalue(), "application/octet-stream"
    if what == "journal":
        j = seg.d / "journal.jsonl"
        return f"{seg.nom}_journal_{stamp}.jsonl", (j.read_bytes() if j.exists() else b""), "application/x-ndjson"
    if what not in ("segment", "bundle"):
        raise ValueError("what: segment, offset, journal or bundle")
    with tempfile.TemporaryDirectory(prefix="sr_dl_") as t:
        r = export_segment(seg, dest_dir=Path(t), grid=grid, sidecar=False)
        uuid = r["id"]
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for f in sorted(Path(r["folder"]).iterdir()):
                zf.write(f, f"{uuid}/{f.name}")
            if what == "bundle":
                side = write_sidecar(seg, Path(t) / f"{uuid}.retouch", json.loads((Path(r["folder"]) / "meta.json").read_text(encoding="utf-8"))["surface_enhancer"])
                for f in sorted(side.iterdir()):
                    zf.write(f, f"{uuid}.retouch/{f.name}")
        return f"{uuid}.zip", b.getvalue(), "application/zip"


def render_layers(seg, out_dir, first=-8, last=8, as_stack=False) -> dict:
    """Flat-page images of the RETOUCHED surface at depths first … last (voxels along the normal), read from the
    straightened block: the input an ink-detection model needs. One 8-bit TIFF per depth (00.tif = ``first``)."""
    import tifffile
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    first, last = int(first), int(last)
    if not -40 <= first <= last <= 40:
        raise ValueError("depths must stay within -40 … +40 voxels, first <= last")
    reach = float(np.abs(seg.h).max()) + max(abs(first), abs(last))      # beyond ± 39 voxels from the ORIGINAL surface the block ends: values are clamped there
    ks = np.arange(first, last + 1)
    stack = np.zeros((len(ks), seg.H, seg.W), np.uint8)
    for y0 in range(0, seg.H, 256):
        y1 = min(seg.H, y0 + 256)
        a = seg.page_px(y0, y1, 0, seg.W, ks)
        stack[:, y0:y1] = np.clip(a + 0.5, 0, 255).astype(np.uint8).transpose(2, 0, 1)
    if as_stack:
        tifffile.imwrite(str(out_dir / "layers.tif"), stack)
    else:
        for i, k in enumerate(ks):
            tifffile.imwrite(str(out_dir / f"{i:02d}.tif"), stack[i])
    (out_dir / "layers.json").write_text(json.dumps(dict(segment=seg.nom, version=seg.version, depths_vx=[int(k) for k in ks], page=[seg.H, seg.W],
                                                         clamped=bool(reach > 39),
                                                         note="depth 0 = the retouched surface; negative = towards the top of the sections; clamped = some depths reach the end of the straightened block"), indent=2), encoding="utf-8")
    return dict(folder=str(out_dir), layers=len(ks), page=[seg.H, seg.W])
