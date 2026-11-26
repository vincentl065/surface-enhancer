"""Volume Cartographer (VC3D) data: open a volume package, list its volumes and segments.

Two layouts are understood, both read from the VC3D source (``core/src/VolpkgConvert.cpp``, ``core/src/VolumePkg.cpp``):

* the classic ``*.volpkg`` FOLDER: ``config.json`` (name), ``volumes/<id>/`` (zarr volumes), and segments in ``paths/``
  (also ``traces/`` and ``export/``);
* the VC3D PROJECT FILE (JSON): ``{"name", "version", "volumes": [...], "segments": [...], "output_segments": ...}``
  where each entry is a location string or ``{"location": ..., "tags": [...]}``; relative locations are resolved from
  the folder of the project file; remote volumes are direct ``.zarr`` URLs (``s3://``, ``https://``).

A plain folder of segments (sub-folders holding ``meta.json`` + ``x.tif``) is accepted too.
Nothing is ever written here: writing a retouched segment back is done by ``export.export_to_segments_dir``.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import tifxyz
from .volume import is_remote, voxel_size_um

SEGMENT_DIRS = ("paths", "traces", "export")


class VolpkgError(ValueError):
    pass


def _json(f: Path) -> dict:
    try:
        j = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise VolpkgError(f"cannot read {f}: {e}")
    if not isinstance(j, dict):
        raise VolpkgError(f"{f}: a JSON object is expected")
    return j


def _has_zarr_marker(d: Path) -> bool:
    return any((d / n).exists() for n in (".zarray", ".zgroup", ".zattrs", "zarr.json"))


def _is_volume_dir(d: Path) -> bool:
    """Same test as VC3D (isSingleZarrVolumeDir): a zarr array, or a folder with metadata and a zarr level inside."""
    if not d.is_dir():
        return False
    if (d / ".zarray").exists() or (d / "zarr.json").exists():
        return True
    if not ((d / "meta.json").exists() or (d / "metadata.json").exists() or _has_zarr_marker(d)):
        return False
    try:
        return any(c.is_dir() and _has_zarr_marker(c) for c in d.iterdir())
    except OSError:
        return False


def _is_segment_dir(d: Path) -> bool:
    return d.is_dir() and (d / "meta.json").is_file()


def _subdirs(d: Path):
    try:
        return sorted(c for c in d.iterdir() if c.is_dir() and not c.name.startswith("."))
    except OSError:
        return []


def _local(location: str, base: Path) -> Path:
    loc = location[7:] if location.startswith("file://") else location
    p = Path(loc)
    return p if p.is_absolute() else base / p


def _entries(arr) -> list[dict]:
    out = []
    for v in arr if isinstance(arr, list) else []:
        if isinstance(v, str) and v:
            out.append(dict(location=v, tags=[]))
        elif isinstance(v, dict) and v.get("location"):
            out.append(dict(location=str(v["location"]), tags=[str(t) for t in v.get("tags", []) if isinstance(t, str)]))
    return out


def _volume_info(d: Path, tags=()) -> dict:
    meta = {}
    for n in ("meta.json", "metadata.json"):
        if (d / n).is_file():
            try:
                meta = json.loads((d / n).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            break
    um = meta.get("voxelsize") if isinstance(meta.get("voxelsize"), (int, float)) and meta.get("voxelsize") else None
    if um is None and isinstance(meta.get("scan"), dict):
        v = meta["scan"].get("voxel_size_um") or meta["scan"].get("voxelsize")
        um = float(v) if isinstance(v, (int, float)) else None
    shape = [meta.get(k) for k in ("slices", "height", "width")] if all(isinstance(meta.get(k), int) for k in ("slices", "height", "width")) else None
    return dict(id=str(meta.get("uuid") or d.name), name=str(meta.get("name") or d.name), location=str(d), remote=False, voxel_um=um or voxel_size_um(d.name),
                shape=shape, tags=list(tags))


def _segment_info(d: Path, source: str) -> dict:
    info = dict(folder=d.name, path=str(d), source=source, loadable=False, problem=None)
    try:
        meta = tifxyz.read_meta(d)
    except tifxyz.TifxyzError as e:
        info["problem"] = str(e)
        return info
    info["id"] = str(meta.get("uuid") or d.name)
    bands = all((d / b).is_file() for b in tifxyz.BANDS)
    if meta.get("type") != "seg":
        info["problem"] = f'"type" is {meta.get("type")!r}, not "seg"'
    elif meta.get("format") != "tifxyz":
        info["problem"] = f'not a tifxyz segment (format: {meta.get("format")!r})'
    elif not bands:
        info["problem"] = "x.tif / y.tif / z.tif missing"
    else:
        info["loadable"] = True
    sc = meta.get("scale")
    if isinstance(sc, list) and sc and isinstance(sc[0], (int, float)) and sc[0] > 0:
        info["step"] = round(1.0 / sc[0], 3)
    for k in ("area_cm2", "area_vx2", "bbox", "name", "volume"):
        if meta.get(k) is not None:
            info[k] = meta[k]
    try:
        info["modified"] = time.strftime("%Y-%m-%d %H:%M", time.localtime((d / ("x.tif" if bands else "meta.json")).stat().st_mtime))
    except OSError:
        pass
    info["retouched"] = "surface_enhancer" in meta or "surface_retoucher" in meta      # the second: exports made before the tool was renamed
    return info


def open_volpkg(path, max_segments: int = 5000) -> dict:
    """Describe a volume package / project file / folder of segments. Raises VolpkgError with a clear message."""
    p = Path(str(path).strip().strip('"')).expanduser()
    if not p.exists():
        raise VolpkgError(f"not found: {p}")
    out = dict(path=str(p.resolve()), name=p.name, kind="", volumes=[], segment_dirs=[], segments=[], output_segments=None, warnings=[])
    vol_entries, seg_entries, base = [], [], p
    if p.is_file():
        j = _json(p)
        if "volumes" not in j and "segments" not in j:
            raise VolpkgError(f'{p.name} does not look like a VC3D project file (no "volumes" or "segments" list)')
        out.update(kind="project", name=str(j.get("name") or p.stem))
        base = p.parent
        vol_entries, seg_entries = _entries(j.get("volumes")), _entries(j.get("segments"))
        if isinstance(j.get("output_segments"), str) and j["output_segments"]:
            out["output_segments"] = str(_local(j["output_segments"], base))
    elif (p / "volumes").is_dir() or any((p / s).is_dir() for s in SEGMENT_DIRS):
        out["kind"] = "folder"
        if (p / "config.json").is_file():
            try:
                n = _json(p / "config.json").get("name")
                if isinstance(n, str) and n and n != "NULL":
                    out["name"] = n
            except VolpkgError as e:
                out["warnings"].append(str(e))
        if (p / "volumes").is_dir():
            vol_entries.append(dict(location="volumes", tags=[]))
        for s in SEGMENT_DIRS:
            if (p / s).is_dir():
                seg_entries.append(dict(location=s, tags=[]))
        if seg_entries:
            out["output_segments"] = str(p / seg_entries[0]["location"])
    elif _is_segment_dir(p) or any(_is_segment_dir(c) for c in _subdirs(p)):
        out["kind"] = "segments-folder"
        seg_entries.append(dict(location=str(p), tags=[]))
        out["output_segments"] = str(p.parent if _is_segment_dir(p) else p)
    else:
        raise VolpkgError(f"{p} is neither a volume package (no volumes/ or paths/ folder), nor a VC3D project file, nor a folder of segments")

    for e in vol_entries:
        loc = e["location"]
        if is_remote(loc) or loc.startswith("s3+"):
            name = loc.rstrip("/").split("/")[-1]
            ok = loc.split("?")[0].rstrip("/").lower().endswith(".zarr")
            out["volumes"].append(dict(id=name, name=name, location=loc, remote=True, voxel_um=voxel_size_um(loc), shape=None, tags=e["tags"],
                                       problem=None if ok and is_remote(loc) else "remote location that is not a direct s3:// or https:// .zarr address"))
            continue
        d = _local(loc, base)
        if not d.exists():
            out["warnings"].append(f"volume location not found: {loc}")
            continue
        for v in ([d] if _is_volume_dir(d) else [c for c in _subdirs(d) if _is_volume_dir(c)]):
            out["volumes"].append(_volume_info(v, e["tags"]))
    seen = set()
    for e in seg_entries:
        if is_remote(e["location"]):
            out["warnings"].append(f"remote segments location skipped: {e['location']}")
            continue
        d = _local(e["location"], base)
        if not d.exists():
            out["warnings"].append(f"segments location not found: {e['location']}")
            continue
        dirs = [d] if _is_segment_dir(d) else [c for c in _subdirs(d) if _is_segment_dir(c)]
        out["segment_dirs"].append(dict(location=e["location"], path=str(d if not _is_segment_dir(d) else d.parent), segments=len(dirs)))
        for c in dirs:
            if len(out["segments"]) >= max_segments:
                out["warnings"].append(f"more than {max_segments} segments: the list is cut")
                break
            info = _segment_info(c, e["location"])
            if info.get("id") in seen:
                info["problem"] = info.get("problem") or "duplicate id (VC3D keeps the first one only)"
            seen.add(info.get("id"))
            out["segments"].append(info)
    out["segments"].sort(key=lambda s: s.get("modified", ""), reverse=True)
    return out


def find_segment(pkg: dict, segment_id: str) -> dict:
    for s in pkg["segments"]:
        if s.get("id") == segment_id or s.get("folder") == segment_id:
            return s
    raise VolpkgError(f"no segment “{segment_id}” in {pkg['path']}")


def find_volume(pkg: dict, volume_id: str | None) -> dict:
    vols = [v for v in pkg["volumes"] if not v.get("problem")]
    if not vols:
        raise VolpkgError(f"no usable volume in {pkg['path']}: give the volume address yourself")
    if volume_id in (None, ""):
        if len(vols) == 1:
            return vols[0]
        raise VolpkgError("this package holds several volumes: choose one (" + ", ".join(v["id"] for v in vols[:8]) + ")")
    for v in vols:
        if volume_id in (v["id"], v["name"], v["location"]):
            return v
    raise VolpkgError(f"no volume “{volume_id}” in {pkg['path']}")
