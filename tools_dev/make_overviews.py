"""Build the low-resolution overview of every public scan, shipped with the tool (``surface_enhancer/web/scrolls/``).

    python tools_dev/make_overviews.py [text the volume address must contain] [--redo]

The editor shows, under the two sections, where the pinned point is in the whole scroll: one slice across the scroll
and one along it. They come from these overviews, so nothing has to be downloaded when the tool is used.

For each volume of ``web/public_volumes.json`` the coarsest level of the OME-Zarr pyramid is read once (anonymous,
read-only), averaged down until a slice is at most 144 pixels wide, stretched to 8 bits, and written as ONE image:
all the slices side by side (``<volume name>.webp``, a few hundred kB). ``index.json`` gives, per volume name, the
size of the overview (z, y, x), how many slices per row of the image, and how many voxels of the full scan one
overview voxel stands for on each axis. A volume that is already done is skipped (``--redo`` to build it again).
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

WEB = Path(__file__).resolve().parents[1] / "surface_enhancer" / "web"
OUT = WEB / "scrolls"
WIDEST = 144                     # pixels across a slice, at most
MAX_BYTES = 3e9                  # coarsest level larger than this: skipped and reported


def open_levels(url: str):
    import s3fs
    import zarr
    g = zarr.open_group(s3fs.S3Map(url.replace("s3://", ""), s3=s3fs.S3FileSystem(anon=True)), mode="r")
    keys = sorted((k for k in g.array_keys() if k.isdigit()), key=int)
    return g[keys[0]], g[keys[-1]], keys[-1]


def overview(url: str) -> tuple[np.ndarray, list]:
    full, a, level = open_levels(url)
    if a.ndim != 3:
        raise ValueError(f"level {level} has {a.ndim} dimensions, 3 expected")
    if a.size * a.dtype.itemsize > MAX_BYTES:
        raise ValueError(f"coarsest level {level} is {a.size * a.dtype.itemsize / 1e9:.1f} GB: too large")
    nz, ny, nx = a.shape
    r = max(1, math.ceil(max(ny, nx) / WIDEST))
    slab = max(r, (128 // r) * r)
    parts = []
    for z0 in range(0, nz - nz % r, slab):
        b = np.asarray(a[z0:min(z0 + slab, nz - nz % r)]).astype(np.float32)
        if b.dtype != np.float32 or a.dtype.itemsize > 1:
            b = b / (256.0 if a.dtype.itemsize == 2 else 1.0)
        z, y, x = (b.shape[0] // r) * r, (ny // r) * r, (nx // r) * r
        parts.append(b[:z, :y, :x].reshape(z // r, r, y // r, r, x // r, r).mean((1, 3, 5)))
    v = np.concatenate(parts)
    filled = v[v > 0]
    top = float(np.percentile(filled, 99.9)) if filled.size else 1.0
    v8 = np.clip(v / max(top, 1e-6) * 255.0, 0, 255).astype(np.uint8)
    factor = [full.shape[i] / v8.shape[i] for i in range(3)]          # full-resolution voxels per overview voxel (z, y, x)
    return v8, factor


def mosaic(v: np.ndarray) -> tuple[np.ndarray, int]:
    nz, ny, nx = v.shape
    cols = max(1, math.ceil(math.sqrt(nz * ny / nx)))
    rows = math.ceil(nz / cols)
    m = np.zeros((rows * ny, cols * nx), np.uint8)
    for k in range(nz):
        m[(k // cols) * ny:(k // cols + 1) * ny, (k % cols) * nx:(k % cols + 1) * nx] = v[k]
    return m, cols


def build_one(url: str) -> dict:
    """One volume: the image, and its index entry (also written next to it as <name>.json, merged by the main run)."""
    name = url.rstrip("/").split("/")[-1].removesuffix(".zarr")
    v, factor = overview(url)
    m, cols = mosaic(v)
    Image.fromarray(m).save(OUT / f"{name}.webp", quality=78, method=6)
    entry = dict(file=f"{name}.webp", size=[int(x) for x in v.shape], cols=cols, factor=[round(f, 4) for f in factor])
    (OUT / f"{name}.json").write_text(json.dumps(entry), encoding="utf-8")
    return entry


def main():
    """Each volume is built by a separate process with a time limit (a stalled network read cannot block the rest),
    three at a time, tried twice."""
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    OUT.mkdir(exist_ok=True)
    if "--one" in sys.argv:
        build_one(sys.argv[sys.argv.index("--one") + 1])
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    redo = "--redo" in sys.argv
    volumes = json.loads((WEB / "public_volumes.json").read_text(encoding="utf-8"))["volumes"]
    index_file = OUT / "index.json"
    index = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else dict(about="low-resolution overviews of the public scans, built by tools_dev/make_overviews.py", volumes={})
    todo = []
    for vol in volumes:
        url = vol["url"].rstrip("/")
        name = url.split("/")[-1].removesuffix(".zarr")
        if args and not any(a.lower() in url.lower() for a in args):
            continue
        if name in index["volumes"] and (OUT / index["volumes"][name]["file"]).exists() and not redo:
            continue
        todo.append((vol["scroll"], name, url))

    def run(job):
        scroll, name, url = job
        t, why = time.time(), ""
        for attempt in (1, 2):
            try:
                r = subprocess.run([sys.executable, "-X", "utf8", __file__, "--one", url], capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
                if r.returncode == 0 and (OUT / f"{name}.json").exists():
                    return scroll, name, json.loads((OUT / f"{name}.json").read_text(encoding="utf-8")), time.time() - t, ""
                why = ([l for l in r.stderr.strip().splitlines() if "Error" in l or "error" in l] or [r.stderr.strip()[-200:]])[-1]
            except subprocess.TimeoutExpired:
                why = "no answer after 15 minutes"
        return scroll, name, None, time.time() - t, why

    failed, done = [], 0
    with ThreadPoolExecutor(3) as pool:
        for scroll, name, entry, dt, why in pool.map(run, todo):
            done += 1
            if entry is None:
                failed.append((name, why))
                print(f"[{done}/{len(todo)}] {scroll} {name}: FAILED — {why}", flush=True)
                continue
            (OUT / f"{name}.json").unlink(missing_ok=True)
            index["volumes"][name] = dict(entry, scroll=scroll)
            index_file.write_text(json.dumps(index, indent=1), encoding="utf-8")
            print(f"[{done}/{len(todo)}] {scroll} {name}: {entry['size'][2]} × {entry['size'][1]} × {entry['size'][0]} voxels, 1 for {entry['factor'][2]:.0f}, "
                  f"{(OUT / entry['file']).stat().st_size / 1e3:.0f} kB, {dt:.0f} s", flush=True)
    total = sum(f.stat().st_size for f in OUT.glob("*.webp"))
    print(f"{len(index['volumes'])} overviews, {total / 1e6:.1f} MB in {OUT}; {len(failed)} failed", flush=True)
    for n, e in failed:
        print(f"  {n}: {e}", flush=True)


if __name__ == "__main__":
    main()
