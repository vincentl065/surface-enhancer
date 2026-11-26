"""Preload of a segment: read the scan ONCE along the normal of the surface, then everything is instant in the page.

Stages (each one resumes or is skipped when already done):

1. surface   read the tifxyz grid, optionally resample it to a finer grid, compute smoothed normals;
2. chunks    (remote volume only) download in parallel the 128³ blocks the surface touches;
3. block     the "straightened block": for every pixel of the flat page, the scan from −40 to +40 voxels along the normal;
4. sheets    for every grid node, where the papyrus sheets are along the normal (peaks of the profile);
5. page      reduced levels of the flat page (17 depths), display contrast;
6. ink       optional ink-prediction layers (images of the size of the page).

Nothing is written into the folder of the original surface. Small files go to ``<data>/segments/<name>/``, big ones to
``<cache>/segments/<name>/`` (about 81 bytes per pixel of the flat page: 1.8 GB for a 5 000 × 4 500 px page).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np

from . import tifxyz
from .config import Settings
from .core.commun import (COUCHES, DEMI, KPICS, ND, NIVEAUX, TUILE, chercheur_de_pics, echantillonneur, ecrire_json, interp_noeuds, normales, reduire2, valide_px)
from .volume import VolumeReader, blocks_touched, describe, is_remote, normalize_location, voxel_size_um

FORMAT_VERSION = 1


class PrepareError(RuntimeError):
    """The preload cannot go on; the message is meant for the user."""


class Reporter:
    """Progress sink: prints a line, and/or writes the state of a background job to a JSON file the server reads."""

    def __init__(self, job_file=None, quiet=False):
        self.job_file = Path(job_file) if job_file else None
        self.quiet = quiet
        self.state = dict(state="running", stage="", fraction=0.0, message="", started=time.strftime("%Y-%m-%d %H:%M:%S"), log=[])
        self._last = 0.0

    def __call__(self, stage, fraction, message, force=False):
        self.state.update(stage=stage, fraction=round(float(np.clip(fraction, 0, 1)), 4), message=message, updated=time.strftime("%H:%M:%S"))
        if not self.quiet:
            print(time.strftime("%H:%M:%S"), f"[{stage} {100 * fraction:3.0f} %]", message, flush=True)
        self.write(force)

    def note(self, message):
        self.state["log"] = (self.state["log"] + [time.strftime("%H:%M:%S ") + message])[-40:]
        if not self.quiet:
            print(time.strftime("%H:%M:%S"), message, flush=True)
        self.write(True)

    def finish(self, state, message, **more):
        self.state.update(state=state, message=message, finished=time.strftime("%Y-%m-%d %H:%M:%S"), **more)
        if state == "done":
            self.state["fraction"] = 1.0
        if not self.quiet:
            print(time.strftime("%H:%M:%S"), ("DONE: " if state == "done" else "FAILED: ") + message, flush=True)
        self.write(True)

    def write(self, force=False):
        if self.job_file is None or (not force and time.time() - self._last < 0.4):
            return
        self._last = time.time()
        try:
            ecrire_json(self.job_file, self.state)
        except OSError:
            pass


def wait_for_memory(min_gb, report, budget=[300.0]):
    """Wait while free memory is under ``min_gb`` (at most ~5 minutes in total, then go on anyway)."""
    try:
        import psutil
    except ImportError:
        return
    said = False
    while budget[0] > 0:
        free = psutil.virtual_memory().available / 1e9
        if free >= min_gb:
            break
        if not said:
            report.note(f"free memory {free:.1f} GB < {min_gb} GB: waiting (lower --min-free-gb to skip)…")
            said = True
        time.sleep(10)
        budget[0] -= 10


def densify(P, valid, factor: int):
    """Resample a grid ``factor`` times finer in each direction (same surface, bilinear). Holes stay holes: a new node is
    valid only when the original nodes around it all are."""
    from scipy import ndimage as ndi
    gh, gw = valid.shape
    idx = ndi.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    Pf = P[idx[0], idx[1]].astype(np.float64)
    yy, xx = np.meshgrid(np.linspace(0, gh - 1, (gh - 1) * factor + 1), np.linspace(0, gw - 1, (gw - 1) * factor + 1), indexing="ij")
    v2 = ndi.map_coordinates(valid.astype(np.float32), [yy, xx], order=1) > 0.999
    out = np.stack([ndi.map_coordinates(Pf[..., i], [yy, xx], order=1) for i in range(3)], -1).astype(np.float32)
    out[~v2] = -1.0
    return out, v2


def sample_points(reader, ech, Pp, Np, out, limit=180e6):
    """Read the scan at Pp + d·Np (d = −DEMI … +DEMI). When the bounding box is too big (folded surface), split the points in two."""
    a = Pp + DEMI * Np
    b = Pp - DEMI * Np
    lo = np.floor(np.minimum(a, b).min(0)).astype(np.int64) - 1
    hi = np.ceil(np.maximum(a, b).max(0)).astype(np.int64) + 3
    if float(np.prod(hi - lo)) > limit and len(Pp) > 256:
        axis = int(np.argmax(hi - lo))
        o = np.argsort(Pp[:, axis], kind="stable")
        m = len(o) // 2
        for part in (o[:m], o[m:]):
            sub = np.empty((len(part), ND), np.uint8)
            sample_points(reader, ech, np.ascontiguousarray(Pp[part]), np.ascontiguousarray(Np[part]), sub, limit)
            out[part] = sub
        return
    vol, lo = reader.region(lo, hi)
    ech(vol, int(lo[0]), int(lo[1]), int(lo[2]), Pp, Np, out, DEMI)


def stage_block(P0, N, valid, step, reader, cache: Path, min_gb, redo, report, span=(0.0, 1.0)):
    gh, gw = valid.shape
    H, W = (gh - 1) * step + 1, (gw - 1) * step + 1
    f = cache / "bloc.npy"
    ff = cache / "bloc_fait.npy"
    tiles = [(y, x) for y in range(0, H, TUILE) for x in (range(0, W, TUILE) if (y // TUILE) % 2 == 0 else reversed(range(0, W, TUILE)))]
    if f.exists() and ff.exists() and not redo:
        block = np.load(f, mmap_mode="r+")
        done = np.load(ff)
        if block.shape != (H, W, ND) or len(done) != len(tiles):
            raise PrepareError(f"{f} does not match this surface any more (the surface or its grid changed): run again with --redo block")
    else:
        block = np.lib.format.open_memmap(f, mode="w+", dtype=np.uint8, shape=(H, W, ND))
        done = np.zeros(len(tiles), bool)
    if done.all():
        report("block", span[1], "straightened block: already done")
        return
    ech = echantillonneur()
    t0 = time.time()
    n0 = int(done.sum())
    for i, (y0, x0) in enumerate(tiles):
        if done[i]:
            continue
        if i % 8 == 0:
            wait_for_memory(min_gb, report)
        y1, x1 = min(y0 + TUILE, H), min(x0 + TUILE, W)
        ys = np.arange(y0, y1)
        xs = np.arange(x0, x1)
        ok = valide_px(valid, ys, xs, step)
        if ok.any():
            Pp = np.ascontiguousarray(interp_noeuds(P0, ys, xs, step)[ok], np.float32)
            Np = interp_noeuds(N, ys, xs, step)[ok]
            Np = np.ascontiguousarray(Np / (np.linalg.norm(Np, axis=-1, keepdims=True) + 1e-9), np.float32)
            out = np.empty((len(Pp), ND), np.uint8)
            sample_points(reader, ech, Pp, Np, out)
            buf = np.zeros((y1 - y0, x1 - x0, ND), np.uint8)
            buf[ok] = out
            block[y0:y1, x0:x1] = buf
        done[i] = True
        if i % 10 == 9 or i == len(tiles) - 1:
            block.flush()
            np.save(ff, done)
        k = int(done.sum())
        left = (time.time() - t0) / max(k - n0, 1) * (len(tiles) - k)
        report("block", span[0] + (span[1] - span[0]) * k / len(tiles),
               f"straightened block: tile {k} of {len(tiles)} · scan blocks: {reader.from_disk} from the cache, {reader.from_source} read from the volume, {reader.missing} missing · about {left / 60:.1f} min left")
    block.flush()
    np.save(ff, done)
    del block


def stage_sheets(valid, step, cache: Path, report, span):
    """Mean profile around each node (2·step × 2·step pixels), smoothed along the normal, then sheet detection (peaks)."""
    from scipy import ndimage
    gh, gw = valid.shape
    block = np.load(cache / "bloc.npy", mmap_mode="r")
    H, W, _ = block.shape
    prof = np.lib.format.open_memmap(cache / "profils.npy", mode="w+", dtype=np.uint8, shape=(gh, gw, ND))
    pos = np.full((gh, gw, KPICS), np.nan, np.float32)
    strength = np.zeros((gh, gw, KPICS), np.float32)
    ech = block[::16, ::16, DEMI - 8:DEMI + 9]
    v = ech[ech > 0]
    p1, p99 = (np.percentile(v, [1, 99]) if v.size else (0, 255))
    contrast = float(max(p99 - p1, 1))
    threshold = 0.035 * contrast
    peaks = chercheur_de_pics()
    B = 16
    win = max(1, min(step, 8))
    dec = np.arange(-win, win)
    for i0 in range(0, gh, B):
        i1 = min(i0 + B, gh)
        ya = max(0, step * i0 - win)
        yb = min(H, step * (i1 - 1) + win)
        S = np.asarray(block[ya:yb])
        som = np.zeros((i1 - i0, gw, ND), np.float32)
        cnt = np.zeros((i1 - i0, gw), np.float32)
        for a in dec:
            yy = np.clip(step * np.arange(i0, i1) + a, ya, yb - 1) - ya
            for b in dec:
                xx = np.clip(step * np.arange(gw) + b, 0, W - 1)
                blk = S[yy][:, xx]
                m = blk[:, :, DEMI - 2:DEMI + 3].max(-1) > 0
                som += blk * m[..., None]
                cnt += m
        p = som / np.maximum(cnt, 1)[..., None]
        p = ndimage.gaussian_filter1d(p, 1.2, axis=-1, mode="nearest")
        prof[i0:i1] = np.clip(p + 0.5, 0, 255).astype(np.uint8)
        n = (i1 - i0) * gw
        po = np.empty((n, KPICS), np.float32)
        fo = np.empty((n, KPICS), np.float32)
        peaks(np.ascontiguousarray(p.reshape(n, ND)), po, fo, np.float32(threshold), 5, 10, DEMI)
        pos[i0:i1] = po.reshape(i1 - i0, gw, KPICS)
        strength[i0:i1] = fo.reshape(i1 - i0, gw, KPICS) / contrast
        report("sheets", span[0] + (span[1] - span[0]) * i1 / gh, f"detecting the sheets along the normal: row {i1} of {gh}")
    pos[~valid] = np.nan
    strength[~valid] = 0
    prof.flush()
    del prof
    np.save(cache / "pics_pos.npy", pos.astype(np.float32))
    np.save(cache / "pics_force.npy", strength.astype(np.float32))
    nb = np.isfinite(pos).sum(-1)[valid]
    report.note(f"sheets: scan contrast {contrast:.0f} grey levels; {nb.mean():.2f} sheets per node on average within ± {DEMI} voxels, {(nb == 0).mean() * 100:.1f} % of the nodes with none")
    return dict(contraste=contrast, seuil_relief=threshold, p1=float(p1), p99=float(p99))


def _reduce_level(src, dst_f: Path, band=256):
    h, w = src.shape[:2]
    h2, w2 = (h + 1) // 2, (w + 1) // 2
    dst = np.lib.format.open_memmap(dst_f, mode="w+", dtype=np.uint8, shape=(h2, w2) + tuple(src.shape[2:]))
    for y in range(0, h2, band):
        dst[y:y + band] = np.clip(reduire2(np.asarray(src[2 * y:2 * (y + band)])) + 0.5, 0, 255).astype(np.uint8)
    dst.flush()
    return dst


def stage_page(cache: Path, report, span):
    """Pyramid of the flat page (depths −8 … +8) for the original surface; the server updates it where you retouch."""
    block = np.load(cache / "bloc.npy", mmap_mode="r")

    class View:                                   # depths −8 … +8 of the block, read by bands
        shape = (block.shape[0], block.shape[1], 2 * COUCHES + 1)

        def __getitem__(self, s):
            return block[s, :, DEMI - COUCHES:DEMI + COUCHES + 1]
    src = View()
    for L in range(1, NIVEAUX + 1):
        src = _reduce_level(src, cache / f"page_L{L}.npy")
        report("page", span[0] + (span[1] - span[0]) * L / NIVEAUX, f"flat page: reduced level {L} of {NIVEAUX}")
    v = np.asarray(np.load(cache / "page_L2.npy", mmap_mode="r")[:, :, COUCHES])
    v = v[v > 0]
    return [float(x) for x in np.percentile(v, [0.5, 99.9])] if v.size else [0.0, 255.0]


def stage_ink(layers, H, W, cache: Path, report, start=0):
    """Ink layers: 8-bit images of the size of the page (probability of ink), one per reader. → list for config.json."""
    import tifffile
    out = []
    (cache / "encre").mkdir(exist_ok=True)
    for i, (name, path) in enumerate(layers):
        try:
            a = tifffile.imread(str(path)) if str(path).lower().endswith((".tif", ".tiff")) else None
            if a is None:
                from PIL import Image
                Image.MAX_IMAGE_PIXELS = None
                a = np.asarray(Image.open(path).convert("L"))
        except Exception as e:
            report.note(f"ink layer “{name}” skipped: unreadable ({path}): {e}")
            continue
        if a.ndim == 3:
            a = a[..., 0]
        if a.shape != (H, W):
            report.note(f"ink layer “{name}” skipped: its size is {a.shape[1]} × {a.shape[0]} px, the page is {W} × {H} px")
            continue
        if a.dtype != np.uint8:
            a = np.clip(a.astype(np.float32) / max(float(a.max()), 1) * 255, 0, 255).astype(np.uint8)
        key = f"c{start + i}"
        np.save(cache / "encre" / f"{key}_L0.npy", a)
        v = a[a > 0][::7]
        ramp = [float(x) for x in np.percentile(v, [86, 99.7])] if v.size else [0.0, 255.0]      # display ramp: 86th → 99.7th percentile
        s = a
        for L in range(1, NIVEAUX + 1):
            s = np.clip(reduire2(s) + 0.5, 0, 255).astype(np.uint8)
            np.save(cache / "encre" / f"{key}_L{L}.npy", s)
        out.append(dict(cle=key, nom=name, source=str(path), seuils=ramp))
        report.note(f"ink layer “{name}”: {path}")
    return out


def estimate(surface, densify_to=None) -> dict:
    """What a preload will cost, before starting it: page size, cache size on disk."""
    info = tifxyz.inspect(surface)
    step = info["step"]
    gh, gw = info["grid"]
    factor = max(1, int(round(step / densify_to))) if densify_to and step > densify_to else 1
    if step % factor:
        factor = 1
    wstep = step // factor
    H, W = (gh - 1) * step + 1, (gw - 1) * step + 1
    ngh, ngw = (gh - 1) * factor + 1, (gw - 1) * factor + 1
    cache_bytes = int(H * W * ND * 1.0 + H * W * (2 * COUCHES + 1) / 3 + ngh * ngw * (ND + KPICS * 8))
    try:                                                       # which public scan it was traced on, when the folder says so
        from .detect import guess_scan
        scan = guess_scan(info["path"])
    except Exception:
        scan = None
    return dict(info, working_step=wstep, densify_factor=factor, working_grid=[ngh, ngw], page=[H, W], cache_bytes=cache_bytes, scan_guess=scan)


def prepare_segment(surface, volume, name, settings: Settings, *, mirror=False, face="forward", ink_layers=(), marks=None, offline=False,
                    chunk_cache=None, level=0, voxel_um=None, densify_to=None, min_free_gb=1.0, redo=(), origin=None, workers=16, report=None) -> dict:
    """Run the whole preload. ``report``: a Reporter (or None for silence). Returns the config of the prepared segment."""
    report = report or Reporter(quiet=True)
    redo = set(redo or ())
    tifxyz.check_name(name)
    settings.ensure()
    import numba
    numba.set_num_threads(max(1, min(int(settings.threads), numba.config.NUMBA_NUM_THREADS)))
    report("surface", 0.0, "reading the surface…", True)
    src = tifxyz.find_tifxyz(surface)
    P, valid, step, meta = tifxyz.read_grid(src)
    volume = normalize_location(volume)
    if level != 0:
        raise PrepareError("only the full-resolution level (0) of the volume is supported for now")
    um = float(voxel_um) if voxel_um else (voxel_size_um(volume) or None)
    d = settings.segments_dir / name
    cache = settings.segment_cache_dir / name
    old = json.loads((d / "config.json").read_text(encoding="utf-8")) if (d / "config.json").exists() else None
    if old and Path(old.get("surface", "")).resolve() != src.resolve() and "block" not in redo:
        raise PrepareError(f"a segment named “{name}” already exists and was prepared from another surface ({old.get('surface')}): choose another name")
    for p in (d, d / "base", d / "versions", d / "gestes", d / "historique", d / "exports", cache):
        p.mkdir(parents=True, exist_ok=True)

    factor = 1
    if densify_to and step > densify_to:
        factor = max(1, int(round(step / float(densify_to))))
        if step % factor:
            raise PrepareError(f"cannot resample a grid of step {step} voxels to about {densify_to}: {step} is not a multiple of {factor}")
    src_step = step
    if factor > 1:
        P, valid = densify(P, valid, factor)
        step = src_step // factor
        report.note(f"grid resampled from one node every {src_step} voxels to one every {step} voxels ({valid.shape[0]} × {valid.shape[1]} nodes)")
    gh, gw = valid.shape
    H, W = (gh - 1) * step + 1, (gw - 1) * step + 1
    if min(gh, gw) < 9:
        raise PrepareError(f"this surface is too small ({gh} × {gw} nodes): at least 9 × 9 nodes are needed")
    need = H * W * ND * 1.45
    free = shutil.disk_usage(cache).free
    if not (cache / "bloc_fait.npy").exists() and free < need:
        raise PrepareError(f"not enough room in the cache folder {cache}: about {need / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free (choose another --cache-dir)")
    size_mm = f" ({H * um / 1000:.1f} × {W * um / 1000:.1f} mm)" if um else ""
    report.note(f"original surface (never modified): {src} · {gh} × {gw} nodes, one every {step} voxels → page {W} × {H} px{size_mm}, {valid.mean() * 100:.0f} % valid nodes")
    P0, N = normales(P, valid)
    np.save(d / "base" / "P0.npy", P0)
    np.save(d / "base" / "N.npy", N)
    np.save(d / "base" / "valide.npy", valid)
    ok = valid[:, 1:] & valid[:, :-1]
    cross = [float((np.linalg.norm(q[:, 1:] - q[:, :-1], axis=-1)[ok] < step * 0.25).mean() * 100) if ok.any() else 0.0 for q in (P0 + DEMI * N, P0 - DEMI * N)]
    if max(cross) > 2:
        report.note(f"note: strongly curved surface — {max(cross):.1f} % of neighbouring columns nearly cross at ± {DEMI} voxels (sections will look pinched there)")

    v0 = d / "versions" / "v000"
    if not v0.exists():                           # copy of the original surface: the frozen reference
        (v0 / "tifxyz").mkdir(parents=True)
        if factor > 1:
            (v0 / "source").mkdir()
            for f in src.iterdir():
                if f.is_file() and f.stat().st_size < 200e6:
                    shutil.copy2(f, v0 / "source" / f.name)
            import tifffile
            for i, c in enumerate("zyx"):
                tifffile.imwrite(str(v0 / "tifxyz" / f"{c}.tif"), P[..., i].astype(np.float32))
            m2 = dict(meta)
            m2["scale"] = [1.0 / step, 1.0 / step]
            ecrire_json(v0 / "tifxyz" / "meta.json", m2)
        else:
            for f in src.iterdir():
                if f.is_file() and f.stat().st_size < 200e6:
                    shutil.copy2(f, v0 / "tifxyz" / f.name)
        ecrire_json(v0 / "meta.json", dict(version="v000", figee=True, role="copy of the original surface, never modified", source=str(src), creee=time.strftime("%Y-%m-%d %H:%M:%S")))
    v1 = d / "versions" / "v001"
    if not v1.exists():
        v1.mkdir()
        np.save(v1 / "decalage.npy", np.zeros((gh, gw), np.float32))
        ecrire_json(v1 / "meta.json", dict(version="v001", figee=False, parent="v000", evenements=0, creee=time.strftime("%Y-%m-%d %H:%M:%S")))

    if marks:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        z = np.asarray(Image.open(marks).convert("L"))
        if z.shape == (H, W):
            zn = z[::step, ::step] > 127
        elif z.shape == (gh, gw):
            zn = z > 127
        else:
            raise PrepareError(f"marks image: its size is {z.shape[1]} × {z.shape[0]} px; expected {W} × {H} (page) or {gw} × {gh} (grid nodes)")
        work = sorted(p for p in (d / "versions").iterdir() if p.is_dir())[-1]
        Image.fromarray((zn & valid).astype(np.uint8) * 255).save(work / "zones.png")
        Image.fromarray((zn & valid).astype(np.uint8) * 255).save(d / "base" / "zones_depart.png")
        report.note(f"problem areas imported: {(zn & valid).sum() / max(valid.sum(), 1) * 100:.0f} % of the page")

    reader = VolumeReader(volume, settings.volume_cache_dir, chunk_cache=chunk_cache, level=level, network=not offline)
    block_done = (cache / "bloc_fait.npy").exists() and bool(np.load(cache / "bloc_fait.npy").all()) and "block" not in redo
    a, b = 0.02, 0.85
    if reader.remote and not offline and not block_done:
        keys = blocks_touched(P0, N, valid, DEMI)
        todo = reader.missing_keys(keys)
        report("chunks", a, f"{len(keys)} scan blocks (128³) touched by the surface, {len(todo)} to download from {volume}")
        if todo:
            r = reader.prefetch(keys, workers=workers, progress=lambda k, n: report("chunks", a + 0.38 * k / n, f"downloading scan blocks: {k} of {n}"))
            report.note(f"scan blocks: {r['downloaded']} downloaded in {r['seconds']} s, {r['failed']} failed")
            if r["failed"] == len(todo) and len(todo) > 0:
                raise PrepareError("no scan block could be downloaded: " + ("; ".join(reader.errors) or "network unreachable") + " — check the volume address and your connection (behind a TLS-inspecting proxy, set ca_bundle in the config file)")
        a = 0.40
    wait_for_memory(min_free_gb, report)
    stage_block(P0, N, valid, step, reader, cache, min_free_gb, "block" in redo, report, (a, b))
    if reader.errors:
        report.note("some scan blocks could not be read: " + "; ".join(reader.errors[:3]))
    state_f = cache / "preparation.json"
    state = json.loads(state_f.read_text(encoding="utf-8")) if state_f.exists() else {}
    if "pics" not in state or redo & {"sheets", "block"}:
        state["pics"] = stage_sheets(valid, step, cache, report, (0.85, 0.93))
        ecrire_json(state_f, state)
    if "lut" not in state or redo & {"page", "block"}:
        state["lut"] = stage_page(cache, report, (0.93, 0.98))
        ecrire_json(state_f, state)
    layers = []
    for c in ink_layers or ():
        nm, _, path = str(c).partition("=")
        if not path:
            raise PrepareError(f'ink layer {c!r}: write it as "Displayed name=path/to/prediction.tif"')
        layers.append((nm.strip(), Path(path.strip())))
    if "encre" not in state or redo & {"ink"} or layers:
        report("ink", 0.98, "ink layers…")
        state["encre"] = stage_ink(layers, H, W, cache, report) if layers else state.get("encre", [])
        ecrire_json(state_f, state)

    cfg = dict(format_version=FORMAT_VERSION, nom=name, surface=str(src), volume=volume, cache=str(cache), um=um or 0.0, um_known=bool(um), pas=step, grille=[gh, gw], page=[H, W],
               demi=DEMI, couches=COUCHES, miroir=bool(mirror), face=face, encre=state.get("encre", []), lut=state["lut"], pics=state["pics"], meta_origine=meta,
               prepare=time.strftime("%Y-%m-%d %H:%M:%S"), blocs_absents=int(reader.missing), source_step=src_step, densified_factor=factor, level=level,
               chunk_cache=str(chunk_cache) if chunk_cache else None, cache_scan=str(reader.dir) if reader.dir else None, origin=origin or dict(kind="path", path=str(src)))
    if not um:
        cfg["um"] = 7.91
        report.note("voxel size unknown (not in the volume name): 7.91 µm assumed for the millimetre scales — give --voxel-um to fix it")
    ecrire_json(d / "config.json", cfg)
    if reader.missing:
        report.note(f"warning: {reader.missing} scan blocks were missing (shown black); run the preparation again with --redo block once the volume is reachable")
    report.finish("done", f"segment “{name}” is ready", segment=name, missing_blocks=int(reader.missing))
    return cfg


def add_ink_layers(name, layers, settings: Settings, report=None) -> list:
    """Add ink-prediction layers to an already prepared segment (the hook for "re-read the ink with your own model")."""
    report = report or Reporter(quiet=True)
    d = settings.segments_dir / name
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    cache = settings.segment_cache_dir / name
    if not (cache / "bloc.npy").exists():
        cache = Path(cfg["cache"])
    H, W = cfg["page"]
    old = cfg.get("encre", [])
    pairs = []
    for c in layers:
        nm, _, path = str(c).partition("=")
        if not path:
            raise PrepareError(f'ink layer {c!r}: write it as "Displayed name=path/to/prediction.tif"')
        pairs.append((nm.strip(), Path(path.strip())))
    start = 1 + max([int(c["cle"][1:]) for c in old] + [-1])
    new = stage_ink(pairs, H, W, cache, report, start=start)      # keys stay unique next to the layers already there
    cfg["encre"] = old + new
    ecrire_json(d / "config.json", cfg)
    return cfg["encre"]
