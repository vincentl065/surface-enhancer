"""How the tiny sample in ``sample/`` was made (developer tool; you do not need to run it).

    python tools_dev/make_sample.py [--row R --col C] [--nodes 17] [--step 16] --out sample

Source: Scroll 1 (PHerc. Paris 4), the scroll read by the 2023 Grand Prize — public Vesuvius Challenge data.

* surface: a small window of the public segment 20230702185753. Its ``.ppm`` (pixel → x, y, z of the scan) is read over
  HTTP by byte ranges; one pixel out of ``--step`` becomes a grid node (17 × 17 nodes every 16 voxels: about 2 mm);
* scan: stored as a sparse OME-Zarr (zarr v2) of the same shape as the real volume, holding only the voxels within
  ± 48 voxels of that piece of surface. Coordinates stay those of the real scan.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from surface_enhancer import tifxyz                                  # noqa: E402
from surface_enhancer.core.commun import normales                    # noqa: E402
from surface_enhancer.prepare import densify                         # noqa: E402
from surface_enhancer.volume import VolumeReader                     # noqa: E402

BASE = "https://dl.ash2txt.org/full-scrolls/Scroll1/PHercParis4.volpkg"
SEGMENT = "20230702185753"
VOLUME = f"{BASE}/volumes_zarr_standardized/54keV_7.91um_Scroll1A.zarr"
VOLUME_ID = "20230205180739"
UM = 7.91

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="sample")
ap.add_argument("--row", type=int)
ap.add_argument("--col", type=int)
ap.add_argument("--nodes", type=int, default=17)
ap.add_argument("--step", type=int, default=16)
ap.add_argument("--cache-dir", help="where downloaded scan blocks are kept (default: a temporary folder)")
ap.add_argument("--dry", action="store_true", help="only print the candidate windows")
a = ap.parse_args()

import fsspec
http = fsspec.filesystem("http")
ppm = f"{BASE}/paths/{SEGMENT}/{SEGMENT}.ppm"
head = http.cat_file(ppm, start=0, end=300)
off = head.index(b"<>\n") + 3
W = int(head.split(b"width: ")[1].split(b"\n")[0])
H = int(head.split(b"height: ")[1].split(b"\n")[0])
print(f"segment {SEGMENT}: flat page {W} × {H} px")
n, st = a.nodes, a.step


def window(r, c):
    """n × n nodes, one pixel out of `st`, starting at pixel (r, c). → P (n, n, 3) in (z, y, x), valid."""
    out = np.zeros((n, n, 3), np.float32)
    for i in range(n):
        s = off + ((r + i * st) * W + c) * 48
        row = np.frombuffer(http.cat_file(ppm, start=s, end=s + ((n - 1) * st + 1) * 48), "<f8").reshape(-1, 6)[::st]
        out[i] = row[:, 2::-1]
    return out, (out[..., 0] > 0) & np.isfinite(out).all(-1)


def quality(P, ok):
    P0, N = normales(P, ok)
    du = np.linalg.norm(np.diff(P, axis=1), axis=-1)
    dv = np.linalg.norm(np.diff(P, axis=0), axis=-1)
    stretch = float(max(np.abs(du / st - 1).max(), np.abs(dv / st - 1).max()))
    bend = float(np.degrees(np.arccos(np.clip((N * N[n // 2, n // 2]).sum(-1), -1, 1))).max())
    return stretch, bend


if a.row is None or a.col is None:
    best = None
    for fr in (0.3, 0.45, 0.6):
        for fc in (0.2, 0.35, 0.5, 0.65, 0.8):
            r, c = int(H * fr), int(W * fc)
            P, ok = window(r, c)
            if not ok.all():
                continue
            stretch, bend = quality(P, ok)
            print(f"  candidate row {r} col {c}: stretch {stretch:.2f}, bend {bend:.0f}°")
            if stretch < 0.3 and (best is None or stretch * 100 + bend < best[0]):
                best = (stretch * 100 + bend, r, c)
    if best is None:
        raise SystemExit("no candidate window found")
    row, col = best[1], best[2]
else:
    row, col = a.row, a.col
print("window: row", row, "col", col)
if a.dry:
    sys.exit(0)

P, ok = window(row, col)
if not ok.all():
    raise SystemExit("this window has invalid nodes")
out = Path(a.out)
seg_dir = out / "segment" / "sample_scroll1"
z, y, x = P[..., 0], P[..., 1], P[..., 2]
meta = dict(type="seg", uuid="sample_scroll1", format="tifxyz", scale=[1 / st, 1 / st], bbox=tifxyz.bbox_xyz(x, y, z, ok), name="sample_scroll1", volume_id=VOLUME_ID,
            source=f"{n} × {n} nodes (one pixel out of {st}) cut out of the public Scroll 1 segment {SEGMENT}, rows {row}–{row + (n - 1) * st}, columns {col}–{col + (n - 1) * st} of its flat page")
if seg_dir.exists():
    shutil.rmtree(seg_dir)
tifxyz.write_tifxyz(seg_dir, x, y, z, meta, valid=ok)

import tempfile
reader = VolumeReader(VOLUME, a.cache_dir or tempfile.mkdtemp(prefix="sr_sample_"))
Pd, vd = densify(P, ok, 8)                        # voxels within ± 48 of the surface, on a finer grid so that none is skipped
P0, N = normales(Pd, vd)
lo = np.floor((P0 - 50 * np.abs(N)).reshape(-1, 3).min(0)).astype(int) - 3
hi = np.ceil((P0 + 50 * np.abs(N)).reshape(-1, 3).max(0)).astype(int) + 4
vol, lo = reader.region(lo, hi)
mask = np.zeros(vol.shape, bool)
for d in np.arange(-48, 48.01, 0.5):
    q = np.round(P0 + d * N - lo).astype(int).reshape(-1, 3)
    q = q[((q >= 0) & (q < np.array(vol.shape))).all(1)]
    mask[q[:, 0], q[:, 1], q[:, 2]] = True
from scipy import ndimage as ndi
mask = ndi.binary_dilation(mask, iterations=2)
vol = np.where(mask, vol, 0).astype(np.uint8)
print(f"scan region {vol.shape} at {lo.tolist()}, {mask.sum() / 1e6:.1f} M voxels kept; blocks: {reader.from_disk} from cache, {reader.from_source} downloaded, {reader.missing} missing")
if reader.missing:
    raise SystemExit("some scan blocks are missing: " + "; ".join(reader.errors))

import numcodecs
import zarr
zdir = out / "volume" / "sample_scroll1.zarr"
if zdir.exists():
    shutil.rmtree(zdir)
g = zarr.open_group(str(zdir), mode="w", zarr_format=2)
arr = g.create_array("0", shape=reader.shape, chunks=(64, 64, 64), dtype="uint8", fill_value=0, chunk_key_encoding={"name": "v2", "separator": "/"},
                     compressors=numcodecs.Blosc(cname="zstd", clevel=9, shuffle=numcodecs.Blosc.NOSHUFFLE))
arr[lo[0]:lo[0] + vol.shape[0], lo[1]:lo[1] + vol.shape[1], lo[2]:lo[2] + vol.shape[2]] = vol
g.attrs["multiscales"] = [dict(version="0.4", name="sample_scroll1", axes=[dict(name=k, type="space", unit="micrometer") for k in "zyx"],
                               datasets=[dict(path="0", coordinateTransformations=[dict(type="scale", scale=[UM, UM, UM])])])]
g.attrs["source"] = dict(volume=VOLUME, region_zyx=[lo.tolist(), (lo + np.array(vol.shape)).tolist()],
                         note="sparse copy: only the voxels within ± 48 voxels of the sample surface are stored; everything else reads as 0")
size = sum(f.stat().st_size for f in zdir.rglob("*") if f.is_file())
print(f"written: {seg_dir} and {zdir} ({size / 1e6:.2f} MB, {sum(1 for _ in zdir.rglob('*') if _.is_file())} files)")
(out / "sample.json").write_text(json.dumps(dict(segment="segment/sample_scroll1", volume="volume/sample_scroll1.zarr", voxel_um=UM, scroll="Scroll 1 (PHerc. Paris 4)", volume_source=VOLUME,
                                                 segment_source=f"{BASE}/paths/{SEGMENT}/", window=dict(row=row, col=col, nodes=n, step_px=st)), indent=2), encoding="utf-8")
