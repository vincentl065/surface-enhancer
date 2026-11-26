"""Reading the scan: an OME-Zarr volume on disk, over HTTPS or on S3 (anonymous, read-only — nothing is ever sent).

The scan is read by blocks of 128³ voxels. Blocks of a REMOTE volume are kept on disk (``<cache>/volumes/<name>/
<kz>_<ky>_<kx>.npy``) so that a second preload, or a neighbouring segment, does not download them again. Blocks of a
LOCAL volume are read straight from the zarr and only kept in memory.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

OPEN_DATA = "s3://vesuvius-challenge-open-data/"
BLOCK = 128


class VolumeError(ValueError):
    pass


def is_remote(location: str) -> bool:
    return bool(re.match(r"^(s3|https?)://", str(location)))


def normalize_location(location: str) -> str:
    """Accepts a local path, an ``https://`` or ``s3://`` URL, or the short form ``PHercXXXX/volumes/<name>.zarr`` of
    the public Vesuvius Challenge bucket."""
    loc = str(location).strip().strip('"')
    if not loc:
        raise VolumeError("no volume given: a local .zarr folder, an https:// URL or an s3:// URL is needed")
    if is_remote(loc):
        return loc.rstrip("/")
    if re.match(r"^PHerc[^/\\]*/volumes/.+", loc) and not Path(loc).exists():
        return OPEN_DATA + loc.strip("/")
    p = Path(loc).expanduser()
    if not p.exists():
        raise VolumeError(f"volume not found: {p} (give a local .zarr folder, or an https:// / s3:// URL)")
    return str(p.resolve())


def volume_key(location: str) -> str:
    """Folder name of the chunk cache of a volume: readable name + short hash of the full address."""
    loc = normalize_location(location) if not is_remote(str(location)) else str(location).rstrip("/")
    name = re.sub(r"[^A-Za-z0-9_.\-]+", "_", loc.replace("\\", "/").rstrip("/").split("/")[-1])[:80] or "volume"
    return f"{name}-{hashlib.sha1(loc.encode('utf-8')).hexdigest()[:8]}"


def voxel_size_um(location: str) -> float | None:
    """The voxel size written in the volume name, when it is there (``54keV_7.91um_Scroll1A.zarr``, ``…-7.91um-…``)."""
    m = re.search(r"[-_]([\d.]+)um[-_.]", str(location).replace("\\", "/").rstrip("/").split("/")[-1] + ".")
    return float(m.group(1)) if m else None


def open_zarr_array(location: str, level: int = 0):
    """→ (array, attrs of the group). Opens the resolution level ``level`` of an OME-Zarr group, or a bare zarr array."""
    import zarr
    loc = normalize_location(location)
    kw = {}
    if loc.startswith("s3://"):
        kw["storage_options"] = dict(anon=True)
    try:
        node = zarr.open(loc, mode="r", **kw)
    except Exception as e:
        raise VolumeError(f"cannot open the volume {loc}: {type(e).__name__}: {str(e)[:300]}")
    attrs = {}
    try:
        attrs = dict(node.attrs)
    except Exception:
        pass
    if hasattr(node, "shape") and hasattr(node, "dtype"):
        arr = node
    else:
        try:
            arr = node[str(level)]
        except Exception:
            raise VolumeError(f"{loc}: no resolution level '{level}' in this zarr group (an OME-Zarr volume with levels 0, 1, 2… is expected)")
    if len(arr.shape) != 3:
        raise VolumeError(f"{loc}: a 3-D (z, y, x) array is expected, found shape {tuple(arr.shape)}")
    return arr, attrs


def describe(location: str, level: int = 0) -> dict:
    arr, attrs = open_zarr_array(location, level)
    um = voxel_size_um(location)
    if um is None:
        try:
            ms = attrs.get("multiscales", [{}])[0]
            sc = ms["datasets"][level]["coordinateTransformations"][0]["scale"]
            unit = (ms.get("axes") or [{}])[0].get("unit", "")
            um = float(sc[0]) if str(unit).startswith("micro") else None
        except Exception:
            um = None
    return dict(location=normalize_location(location), shape=[int(v) for v in arr.shape], dtype=str(arr.dtype), voxel_um=um,
                remote=is_remote(normalize_location(location)), key=volume_key(location))


def _to_u8(b: np.ndarray) -> np.ndarray:
    if b.dtype == np.uint8:
        return b
    if b.dtype == np.uint16:
        return (b >> 8).astype(np.uint8)
    if b.dtype.kind == "f":
        return np.clip(b * (255.0 if float(b.max(initial=0)) <= 1.0 else 1.0), 0, 255).astype(np.uint8)
    return np.clip(b, 0, 255).astype(np.uint8)


class VolumeReader:
    """Blocks of 128³ voxels of one volume, as 8-bit. ``chunk_cache``: exact folder for the on-disk blocks (defaults to
    ``<cache_dir>/<volume key>`` for a remote volume; a local volume is not copied). ``network=False``: never download,
    a block missing from the cache counts as empty."""

    def __init__(self, location: str, cache_dir=None, *, chunk_cache=None, level: int = 0, network: bool = True, max_blocks: int = 160):
        self.location = normalize_location(location)
        self.remote = is_remote(self.location)
        self.level = int(level)
        self.network = network
        self.max = max_blocks
        self.dir = Path(chunk_cache) if chunk_cache else (Path(cache_dir) / volume_key(self.location) if (self.remote and cache_dir) else None)
        if self.dir is not None:
            self.dir.mkdir(parents=True, exist_ok=True)
        self.mem: OrderedDict = OrderedDict()
        self.lock = threading.Lock()
        self._open_lock = threading.Lock()
        self._arr = None
        self.from_disk = 0
        self.from_source = 0
        self.missing = 0
        self.errors: list[str] = []

    # ---- source ----
    def array(self):
        with self._open_lock:
            if self._arr is None:
                if self.remote and not self.network:
                    raise VolumeError("network access is disabled (--offline) and this volume is remote")
                self._arr, _ = open_zarr_array(self.location, self.level)
            return self._arr

    @property
    def shape(self):
        return tuple(int(v) for v in self.array().shape)

    def _file(self, k) -> Path | None:
        return None if self.dir is None else self.dir / f"{k[0]}_{k[1]}_{k[2]}.npy"

    def _read_source(self, k):
        a = self.array()
        z, y, x = (k[i] * BLOCK for i in range(3))
        if min(k) < 0 or z >= a.shape[0] or y >= a.shape[1] or x >= a.shape[2]:
            return None
        return _to_u8(np.asarray(a[z:z + BLOCK, y:y + BLOCK, x:x + BLOCK]))

    def _store(self, k, b) -> None:
        f = self._file(k)
        if f is None:
            return
        tmp = f.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:                                    # atomic: never a half-written block in a shared cache
            with open(tmp, "wb") as fh:
                np.save(fh, b)
            os.replace(tmp, f)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def block(self, k):
        k = (int(k[0]), int(k[1]), int(k[2]))
        with self.lock:
            if k in self.mem:
                self.mem.move_to_end(k)
                return self.mem[k]
        b = None
        f = self._file(k)
        if f is not None:
            try:
                b = np.load(f)
                self.from_disk += 1
            except (OSError, ValueError):
                b = None
        if b is None and min(k) >= 0 and (self.network or not self.remote):
            try:
                b = self._read_source(k)
                if b is not None:
                    self.from_source += 1
                    if self.remote:
                        self._store(k, b)
            except Exception as e:               # network down, certificate…: the block counts as empty, reported at the end
                if len(self.errors) < 5:
                    self.errors.append(f"block {k}: {type(e).__name__}: {str(e)[:160]}")
        if b is None:
            self.missing += 1
        with self.lock:
            self.mem[k] = b
            while len(self.mem) > self.max:
                self.mem.popitem(last=False)
        return b

    def region(self, lo, hi):
        """Sub-volume [lo, hi) in (z, y, x), assembled from blocks; missing blocks stay at zero. → (array, origin)."""
        lo = np.maximum(np.asarray(lo, np.int64), 0)
        hi = np.asarray(hi, np.int64)
        out = np.zeros(tuple(np.maximum(hi - lo, 1)), np.uint8)
        for kz in range(lo[0] // BLOCK, (hi[0] - 1) // BLOCK + 1):
            for ky in range(lo[1] // BLOCK, (hi[1] - 1) // BLOCK + 1):
                for kx in range(lo[2] // BLOCK, (hi[2] - 1) // BLOCK + 1):
                    b = self.block((kz, ky, kx))
                    if b is None:
                        continue
                    o = np.array((kz, ky, kx)) * BLOCK
                    s0 = np.maximum(lo, o)
                    s1 = np.minimum(hi, o + np.array(b.shape))
                    if np.any(s1 <= s0):
                        continue
                    out[tuple(slice(a - l, c - l) for a, c, l in zip(s0, s1, lo))] = b[tuple(slice(a - q, c - q) for a, c, q in zip(s0, s1, o))]
        return out, lo

    # ---- parallel download of the blocks a surface needs ----
    def missing_keys(self, keys):
        if self.dir is None:
            return []
        return [k for k in keys if not self._file(k).exists()]

    def prefetch(self, keys, workers: int = 16, progress=None) -> dict:
        """Download in parallel the blocks that are not in the on-disk cache yet (remote volumes only)."""
        todo = self.missing_keys(sorted(set(keys)))
        if not todo or not self.remote or not self.network:
            return dict(wanted=len(set(keys)), downloaded=0, failed=0, seconds=0.0)
        from concurrent.futures import ThreadPoolExecutor
        self.array()
        done = [0, 0]
        t0 = time.time()
        lock = threading.Lock()

        def one(k):
            ok = False
            for attempt in range(3):
                try:
                    b = self._read_source(k)
                    if b is not None:
                        self._store(k, b)
                    ok = True
                    break
                except Exception as e:
                    if attempt == 2 and len(self.errors) < 5:
                        self.errors.append(f"block {k}: {type(e).__name__}: {str(e)[:160]}")
                    time.sleep(0.5 * (attempt + 1))
            with lock:
                done[0] += 1
                done[1] += 0 if ok else 1
                if progress and (done[0] % 8 == 0 or done[0] == len(todo)):
                    progress(done[0], len(todo))

        with ThreadPoolExecutor(max(1, int(workers))) as ex:
            list(ex.map(one, todo))
        return dict(wanted=len(set(keys)), downloaded=len(todo) - done[1], failed=done[1], seconds=round(time.time() - t0, 1))


def blocks_touched(P0, N, valid, half: int, margin: int = 6):
    """Keys of the 128³ blocks a surface touches within ± (half + margin) voxels along its normal."""
    keys = set()
    pts = np.ascontiguousarray(P0[valid][::3])
    nrm = np.ascontiguousarray(N[valid][::3])
    for d in range(-(half + margin), half + margin + 1, 6):
        Q = pts + d * nrm
        for dz in (-2, 2):
            for dy in (-2, 2):
                for dx in (-2, 2):
                    keys |= set(map(tuple, np.unique(np.floor((Q + (dz, dy, dx)) / BLOCK).astype(np.int64), axis=0).tolist()))
    return sorted(k for k in keys if min(k) >= 0)
