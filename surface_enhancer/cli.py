"""Command line of Surface Enhancer.

    python -m surface_enhancer open SURFACE [VOLUME]      ONE command: prepare if needed, start the server if needed, open the editor
    python -m surface_enhancer stop                       stop the server that `open` started
    python -m surface_enhancer serve                      start the local web interface
    python -m surface_enhancer sample                     prepare the tiny bundled sample (nothing to download)
    python -m surface_enhancer prepare SURFACE VOLUME     preload a segment (tifxyz folder or zip + OME-Zarr volume)
    python -m surface_enhancer list                       prepared segments
    python -m surface_enhancer volpkg PATH                volumes and segments of a VC3D volume package / project file
    python -m surface_enhancer export NAME                write the retouched surface as a NEW tifxyz segment
    python -m surface_enhancer replay NAME                replay the journal from the original and compare
    python -m surface_enhancer compare NAME               scan before / after + fibre-grid score
    python -m surface_enhancer render NAME                flat-page layers of the retouched surface (for an ink model)
    python -m surface_enhancer ink-layer NAME "Label=prediction.tif"   show an ink prediction in the editor
    python -m surface_enhancer densify SRC DST            resample a coarse grid (16 or 20 voxels) to a fine one
    python -m surface_enhancer flatten SRC DST            lay a retouched surface flat again (needs PyTorch)

Add --help after a command for its options.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .config import add_settings_arguments, settings_from_args


def _segment(a, settings, replay=False):
    from .core.segment import Segment, SegmentError
    try:
        return Segment(a.name, rejeu=replay, donnees=settings.segments_dir, cache=settings.segment_cache_dir / a.name)
    except SegmentError as e:
        raise SystemExit(str(e))


def cmd_serve(a):
    from .server import serve
    serve(settings_from_args(a), open_browser=a.open)


def _surface_argument(surface: str, settings) -> Path:
    """A tifxyz folder, or the zip of one (unzipped into the uploads folder)."""
    from . import tifxyz
    p = Path(surface).expanduser()
    if p.is_file() and p.suffix.lower() == ".zip":
        d = settings.ensure().uploads_dir / (time.strftime("%Y%m%d_%H%M%S_") + tifxyz.safe_name(p.stem))
        d.mkdir(parents=True)
        return tifxyz.extract_zip(p, d, settings.max_upload_mb << 20)
    return tifxyz.find_tifxyz(p)


def cmd_prepare(a):
    from . import tifxyz, vc3d
    from .prepare import PrepareError, Reporter, prepare_segment
    from .volume import VolumeError
    settings = settings_from_args(a)
    rep = Reporter(a.job_file)
    try:
        origin = json.loads(a.origin_json) if a.origin_json else None
        volume = a.volume
        if a.volpkg:
            pkg = vc3d.open_volpkg(a.volpkg)
            s = vc3d.find_segment(pkg, a.surface)
            if not s["loadable"]:
                raise PrepareError(f"segment “{s.get('id')}” cannot be loaded: {s['problem']}")
            surface = Path(s["path"])
            volume = volume if volume not in (None, "", "-") else vc3d.find_volume(pkg, a.volume_id)["location"]
            origin = dict(kind="volpkg", volpkg=pkg["path"], segment=s["id"], segments_dir=str(surface.parent), output_segments=pkg.get("output_segments"))
        else:
            if volume in (None, "", "-"):
                raise PrepareError("give the volume: a local .zarr folder, an https:// URL or an s3:// URL")
            surface = _surface_argument(a.surface, settings)
        name = a.name or tifxyz.safe_name(tifxyz.inspect(surface)["id"])
        prepare_segment(surface, volume, name, settings, mirror=a.mirror, face=a.face, ink_layers=a.ink_layer, marks=a.marks, offline=a.offline,
                        chunk_cache=a.chunk_cache, voxel_um=a.voxel_um, densify_to=a.densify_to, min_free_gb=a.min_free_gb,
                        redo=[x for x in a.redo.split(",") if x], origin=origin, workers=a.download_workers, report=rep)
        if not a.job_file:
            print(f"open it:  python -m surface_enhancer serve   →  http://127.0.0.1:{settings.port}/tabs.html?s={name}")
    except (PrepareError, tifxyz.TifxyzError, vc3d.VolpkgError, VolumeError, FileNotFoundError) as e:
        rep.finish("failed", str(e))
        raise SystemExit(1)
    except KeyboardInterrupt:
        rep.finish("cancelled", "interrupted — run the same command again to resume")
        raise SystemExit(130)
    except Exception as e:
        rep.finish("failed", f"{type(e).__name__}: {e}")
        raise


def cmd_sample(a):
    from .prepare import Reporter, prepare_segment
    settings = settings_from_args(a)
    from .config import sample_dir
    root = Path(a.sample_dir) if a.sample_dir else sample_dir()
    surface, volume = root / "segment" / "sample_scroll1", root / "volume" / "sample_scroll1.zarr"
    if not surface.is_dir() or not volume.is_dir():
        raise SystemExit(f"the sample data was not found in {root}: it ships with the source repository, in sample/ — run this command from the folder of the repository, or give --sample-dir")
    prepare_segment(surface, str(volume), a.name, settings, voxel_um=7.91, densify_to=4, report=Reporter(),
                    origin=dict(kind="path", path=str(surface), sample=True))
    print(f"\nsample ready. Start the interface:  python -m surface_enhancer serve\nthen open  http://127.0.0.1:{settings.port}/tabs.html?s={a.name}")


def _server_state(settings):
    """What answers on the port: ('ours', home) for a Surface Enhancer server on the same data folder, ('other', None) for something else, ('none', None)."""
    import urllib.request
    from .server import port_in_use
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{settings.port}/api/home", timeout=3) as r:
            h = json.loads(r.read())
        same = Path(h.get("settings", {}).get("data_dir", "")).resolve() == settings.data_dir.resolve()
        return ("ours" if same else "other-data"), h
    except Exception:
        return ("other" if port_in_use(settings.port) else "none"), None


def _start_server(settings) -> int:
    """Start `serve` detached (it survives this command) and wait until it answers; returns its process id."""
    import subprocess
    cmd = [sys.executable, "-X", "utf8", "-m", "surface_enhancer", "serve", "--port", str(settings.port), "--data-dir", str(settings.data_dir), "--cache-dir", str(settings.cache_dir)]
    log = open(settings.data_dir / "server.log", "ab")
    extra = dict(creationflags=0x00000008 | 0x00000200 | 0x08000000) if sys.platform == "win32" else dict(start_new_session=True)
    import os
    env = dict(os.environ)                                    # the server keeps the current folder (where the sample may be) and finds this package wherever it is
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, **extra)
    for _ in range(120):
        time.sleep(0.25)
        if _server_state(settings)[0] == "ours":
            (settings.data_dir / "server.json").write_text(json.dumps(dict(pid=p.pid, port=settings.port)), encoding="utf-8")
            return p.pid
        if p.poll() is not None:
            break
    raise SystemExit(f"the server did not start: see {settings.data_dir / 'server.log'}")


def cmd_open(a):
    """One command for a person or an AI assistant: SURFACE is a prepared segment name, or a tifxyz folder / zip (then VOLUME is needed)."""
    from . import tifxyz, vc3d
    from .prepare import PrepareError, Reporter, prepare_segment
    from .server import App
    from .volume import VolumeError
    settings = settings_from_args(a)
    settings.ensure()
    say = (lambda *x: None) if a.json else (lambda *x: print(*x, flush=True))
    out = dict(name=None, prepared_now=False, server=None, url=None)
    try:
        app = App(settings)
        known = {s["name"]: s for s in app.library()}
        as_path = Path(a.surface).expanduser()
        if a.surface in known and not a.volpkg and (not a.volume or not as_path.exists()):      # a prepared segment, by its name (even when a folder of that name is in sight)
            name = a.surface
            if not known[name]["ready"]:
                raise PrepareError(f"“{name}” is listed but its cache is missing: give its segment folder and volume again to prepare it")
        else:
            volume, origin = a.volume, None
            if a.volpkg:
                pkg = vc3d.open_volpkg(a.volpkg)
                seg = vc3d.find_segment(pkg, a.surface)
                if not seg["loadable"]:
                    raise PrepareError(f"segment “{seg.get('id')}” cannot be loaded: {seg['problem']}")
                surface = Path(seg["path"])
                volume = volume or vc3d.find_volume(pkg, a.volume_id)["location"]
                origin = dict(kind="volpkg", volpkg=pkg["path"], segment=seg["id"], segments_dir=str(surface.parent), output_segments=pkg.get("output_segments"))
            else:
                if not as_path.exists():
                    raise PrepareError(f"“{a.surface}” is neither a prepared segment ({', '.join(known) or 'none yet'}) nor a folder / zip on this computer")
                surface = _surface_argument(a.surface, settings)
            info = tifxyz.inspect(surface)
            name = a.name or tifxyz.safe_name(info["id"])
            same = name in known and known[name]["ready"] and Path(known[name]["source"] or "").resolve() == Path(surface).resolve()
            if not same:
                if not volume:
                    raise PrepareError("this segment is not prepared yet: give the scan volume it was traced on (a local .zarr folder, an https:// URL or an s3:// URL)")
                say(f"preparing {name} (the scan is read once along the surface; this can take minutes for a large page)…")
                prepare_segment(surface, volume, name, settings, mirror=a.mirror, voxel_um=a.voxel_um, densify_to=a.densify_to if a.densify_to is not None else (4 if info["step"] > 8 else None),
                                origin=origin, report=Reporter(quiet=True) if a.json else Reporter())
                out["prepared_now"] = True
        state, _ = _server_state(settings)
        if state in ("other", "other-data"):
            raise PrepareError(f"port {settings.port} is used by " + ("a Surface Enhancer server on another data folder" if state == "other-data" else "another program") + ": choose another one with --port")
        if state == "none":
            out["pid"] = _start_server(settings)
        out.update(name=name, server="started" if state == "none" else "already running", url=f"http://127.0.0.1:{settings.port}/tabs.html?s={name}")
    except (PrepareError, tifxyz.TifxyzError, vc3d.VolpkgError, VolumeError, FileNotFoundError) as e:
        if a.json:
            print(json.dumps(dict(error=str(e))))
            raise SystemExit(1)
        raise SystemExit(str(e))
    if not a.no_browser:
        import webbrowser
        webbrowser.open(out["url"])
    print(json.dumps(out) if a.json else f"{name} is open: {out['url']}   (server {out['server']}; stop it with: python -m surface_enhancer stop)")


def cmd_stop(a):
    settings = settings_from_args(a)
    f = settings.data_dir / "server.json"
    state, _ = _server_state(settings)
    if state != "ours" or not f.exists():
        print("no server started by `open` is running on this data folder" + (" (a server started by hand answers: stop it with Ctrl+C in its terminal)" if state == "ours" else ""))
        return
    import psutil
    j = json.loads(f.read_text(encoding="utf-8"))
    try:
        p = psutil.Process(int(j["pid"]))
        if "surface_enhancer" in " ".join(p.cmdline()):
            p.terminate()
            p.wait(10)
    except (psutil.Error, ValueError, KeyError):
        pass
    f.unlink(missing_ok=True)
    print("server stopped (every gesture was already saved)")


def cmd_list(a):
    from .server import App
    rows = App(settings_from_args(a)).library()
    if getattr(a, "json", False):
        print(json.dumps([dict(name=s["name"], ready=s["ready"], scroll=s["scroll"], size_mm=s["size_mm"], gestures=s["gestures"], source=s["source"], volume=s["volume"]) for s in rows]))
        return
    if not rows:
        print("no prepared segment yet — try:  python -m surface_enhancer sample")
    for s in rows:
        mm = f"{s['size_mm'][1]} × {s['size_mm'][0]} mm" if s["size_mm"] else f"{s['page'][1]} × {s['page'][0]} px"
        print(f"{s['name']:32s} {'ready' if s['ready'] else 'NOT READY':9s} {mm:>18s}  {s['gestures']:4d} gesture(s)  {s['version'] or '':5s} {s['cache_bytes'] / 1e9:6.2f} GB  {s['scroll']}")


def cmd_volpkg(a):
    from . import vc3d
    try:
        pkg = vc3d.open_volpkg(a.path)
    except vc3d.VolpkgError as e:
        raise SystemExit(str(e))
    if a.json:
        print(json.dumps(pkg, indent=1))
        return
    print(f"{pkg['name']} ({pkg['kind']}) — {pkg['path']}")
    print(f"volumes ({len(pkg['volumes'])}):")
    for v in pkg["volumes"]:
        print(f"  {v['id']:40s} {str(v.get('voxel_um') or '?'):>7s} µm  {v['location']}" + (f"   [{v['problem']}]" if v.get("problem") else ""))
    print(f"segments ({len(pkg['segments'])}), new segments go to: {pkg['output_segments']}")
    for s in pkg["segments"][: a.limit]:
        print(f"  {s.get('id', s['folder']):48s} {'ok ' if s['loadable'] else 'NO '} step {str(s.get('step', '?')):>5s}  {s.get('modified', ''):16s}" + (f"  [{s['problem']}]" if s.get("problem") else ""))
    for w in pkg["warnings"]:
        print("warning:", w)


def cmd_export(a):
    from .export import export_segment, export_to_segments_dir, download_bytes
    from . import vc3d
    settings = settings_from_args(a)
    seg = _segment(a, settings)
    try:
        if a.zip:
            name, body, _ = download_bytes(seg, "bundle", a.grid or "working")
            out = Path(a.zip) / name if Path(a.zip).is_dir() else Path(a.zip)
            out.write_bytes(body)
            print("written:", out)
            return
        if a.to_volpkg is not None:
            o = seg.cfg.get("origin") or {}
            dest = o.get("output_segments") or o.get("segments_dir")
            if a.to_volpkg:
                pkg = vc3d.open_volpkg(a.to_volpkg)
                dest = pkg.get("output_segments") or (pkg["segment_dirs"][0]["path"] if pkg["segment_dirs"] else None)
            if not dest:
                raise SystemExit("no VC3D segments folder known for this segment: give --to-volpkg <volume package, project file or segments folder>")
            r = export_to_segments_dir(seg, dest, uuid=a.id, grid=a.grid or "original")
        else:
            r = export_segment(seg, uuid=a.id, dest_dir=a.out, grid=a.grid or "working")
    except (FileExistsError, FileNotFoundError, ValueError, vc3d.VolpkgError) as e:
        raise SystemExit(str(e))
    print(json.dumps(r, indent=1))
    if r["vc3d_problems"]:
        print("VC3D would not load this folder:", "; ".join(r["vc3d_problems"]))
        raise SystemExit(2)
    print("VC3D check: ok (type, uuid, format, scale, bbox, x/y/z present and of equal size)")


def cmd_replay(a):
    import numpy as np
    from PIL import Image
    settings = settings_from_args(a)
    seg = _segment(a, settings, replay=True)
    f = seg.d / "journal.jsonl"
    lines = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []
    if a.until is not None:
        lines = lines[:a.until]
    worst = 0.0
    n = dict(geste=0, annuler=0, retablir=0)
    different = []
    for e in lines:
        t = e.get("type")
        if t == "geste":
            r = seg.etendre(e["params"], ident=e["id"]) if e["outil"] == "etendre" else seg.geste(e["outil"], e["params"], ident=e["id"])
            n[t] += 1
            z = np.load(seg.d / "gestes" / f"g{e['id']:06d}.npz")
            if r.get("rien") or list(seg._patchs[e["id"]]["bbox"]) != [int(x) for x in z["bbox"]]:
                different.append(e["id"])
                continue
            d = float(np.abs(seg._patchs[e["id"]]["apres"].astype(np.float32) - z["apres"].astype(np.float32)).max())
            worst = max(worst, d)
            if d > 1e-3:
                different.append(e["id"])
        elif t in ("annuler", "retablir"):
            seg.annuler(-1 if t == "annuler" else 1)
            n[t] += 1
    print(f"{n['geste']} gestures replayed, {n['annuler']} undos, {n['retablir']} redos; largest difference with the recorded gestures: {worst:.4f} vx" + (f"; different gestures: {different}" if different else ""))
    if a.out:
        np.save(a.out, seg.h)
        print("replayed offset field written to", a.out)
    if a.until is None:
        work = sorted(p for p in (seg.d / "versions").iterdir() if p.is_dir())[-1]
        h = np.load(work / ("decalage_etendu.npy" if seg.ext else "decalage.npy"))
        e = float(np.abs(h - seg.h).max()) if h.shape == seg.h.shape else 999.0
        zf = work / ("zones_etendu.png" if seg.ext else "zones.png")
        zok = (not zf.exists()) or np.array_equal(np.asarray(Image.open(zf).convert("L")) > 127, seg.zones)
        ok = e < 1e-3 and zok and not different
        print(("IDENTICAL" if ok else "DIFFERENT") + f": replayed surface against {work.name} — largest difference {e:.4f} vx, marked areas {'identical' if zok else 'different'}")
        sys.exit(0 if ok else 1)


def cmd_compare(a):
    from .tools.compare import compare
    settings = settings_from_args(a)
    seg = _segment(a, settings)
    out = a.out or seg.d / "compare" / time.strftime("%Y%m%d_%H%M%S")
    print(json.dumps(compare(seg, out), indent=1))


def cmd_render(a):
    from .export import render_layers
    settings = settings_from_args(a)
    seg = _segment(a, settings)
    out = a.out or seg.d / "layers" / time.strftime("%Y%m%d_%H%M%S")
    print(json.dumps(render_layers(seg, out, a.first, a.last, a.stack), indent=1))


def cmd_ink_layer(a):
    from .prepare import PrepareError, Reporter, add_ink_layers
    try:
        layers = add_ink_layers(a.name, a.layer, settings_from_args(a), Reporter())
    except (PrepareError, FileNotFoundError) as e:
        raise SystemExit(str(e))
    print("ink layers of", a.name, ":", ", ".join(c["nom"] for c in layers), "\n(restart the server, or reload the page, to see them)")


def cmd_densify(a):
    import numpy as np
    from . import tifxyz
    from .prepare import densify
    try:
        src = tifxyz.find_tifxyz(a.src)
        P, valid, step, meta = tifxyz.read_grid(src)
        factor = max(1, int(round(step / a.step)))
        if step % factor:
            raise tifxyz.TifxyzError(f"a grid of step {step} voxels cannot be resampled to about {a.step}: {step} is not a multiple of {factor}")
        P2, v2 = densify(P, valid, factor)
        dst = Path(a.dst)
        z, y, x = P2[..., 0], P2[..., 1], P2[..., 2]
        m = tifxyz.segment_meta(meta, dst.name, factor / step, tifxyz.bbox_xyz(x, y, z, v2), area_vx2_=tifxyz.area_vx2(P2, v2),
                                provenance=dict(tool="surface-enhancer densify", source_id=meta.get("uuid") or src.name, from_step_vx=step, to_step_vx=step // factor))
        tifxyz.write_tifxyz(dst, x, y, z, m, valid=v2)
    except (tifxyz.TifxyzError, FileExistsError) as e:
        raise SystemExit(str(e))
    print(f"{src}: {valid.shape[0]} × {valid.shape[1]} nodes every {step} vx → {v2.shape[0]} × {v2.shape[1]} nodes every {step // factor} vx; valid {100 * valid.mean():.0f} % → {100 * v2.mean():.0f} %\nwritten: {dst}")


def cmd_flatten(a):
    from .tools.flatten import flatten
    from . import tifxyz
    try:
        flatten(a.src, a.dst, device=a.device)
    except (tifxyz.TifxyzError, FileExistsError) as e:
        raise SystemExit(str(e))


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m surface_enhancer", description="Surface Enhancer — fix a papyrus segment (tifxyz) by hand, with the scan under your eyes.",
                                 epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"surface-enhancer {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="command")

    def cmd(name, fn, help_):
        p = sub.add_parser(name, help=help_, description=help_)
        add_settings_arguments(p)
        p.set_defaults(fn=fn)
        return p

    p = cmd("open", cmd_open, "ONE command: prepare the segment if needed, start the server if needed, open the editor in the browser")
    p.add_argument("surface", help="name of a prepared segment, or a tifxyz folder (x.tif, y.tif, z.tif, meta.json), or a .zip of it, or — with --volpkg — a segment id")
    p.add_argument("volume", nargs="?", help="OME-Zarr volume the segment was traced on (only needed the first time): local folder, https:// URL or s3:// URL")
    p.add_argument("--name", help="name of the segment in Surface Enhancer (default: its id)")
    p.add_argument("--volpkg", help="VC3D volume package / project file / segments folder that holds the segment")
    p.add_argument("--volume-id", help="with --volpkg: which volume of the package")
    p.add_argument("--densify-to", type=float, help="resample the grid to about this many voxels between nodes (default: 4 when the grid is coarser than 8)")
    p.add_argument("--voxel-um", type=float, help="voxel size in µm (read from the volume name when it is there)")
    p.add_argument("--mirror", action="store_true", help="show the page flipped left-right")
    p.add_argument("--port", type=int, help="port of the server (default 8800)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser (the URL is printed)")
    p.add_argument("--json", action="store_true", help="print one JSON object: {name, url, server, prepared_now} or {error} — for scripts and AI assistants")

    p = cmd("stop", cmd_stop, "stop the server that `open` started (nothing is lost: every gesture is saved at once)")
    p.add_argument("--port", type=int, help="port of the server (default 8800)")

    p = cmd("serve", cmd_serve, "start the local web interface")
    p.add_argument("--host", help="address to listen on (default 127.0.0.1; anything else exposes your files: there is no authentication)")
    p.add_argument("--port", type=int, help="port (default 8800)")
    p.add_argument("--open", action="store_true", help="open the page in the default browser")

    p = cmd("prepare", cmd_prepare, "preload a segment: reads the scan once along the surface normal")
    p.add_argument("surface", help="tifxyz folder (x.tif, y.tif, z.tif, meta.json), a .zip of it, or — with --volpkg — the id of a segment")
    p.add_argument("volume", nargs="?", help="OME-Zarr volume: local folder, https:// URL, s3:// URL, or PHercXXXX/volumes/<name>.zarr (public bucket)")
    p.add_argument("--name", help="name of the segment in Surface Enhancer (default: its id)")
    p.add_argument("--volpkg", help="VC3D volume package (folder), project file (.json) or segments folder that holds the segment")
    p.add_argument("--volume-id", help="with --volpkg: which volume of the package (needed when it holds several)")
    p.add_argument("--densify-to", type=float, help="resample the grid to about this many voxels between nodes before retouching (4 is a good value for 16–20 vx grids)")
    p.add_argument("--voxel-um", type=float, help="voxel size in µm (read from the volume name when it holds '-7.91um-')")
    p.add_argument("--mirror", action="store_true", help="show the page flipped left-right by default")
    p.add_argument("--face", default="forward", choices=["forward", "reverse"], help=argparse.SUPPRESS)
    p.add_argument("--ink-layer", action="append", default=[], metavar='"Label=file.tif"', help="ink prediction to show (image of the size of the page); repeatable")
    p.add_argument("--marks", help="image of problem areas to import (255 = problem; size of the page or of the grid)")
    p.add_argument("--offline", action="store_true", help="never download: scan blocks missing from the cache are left black")
    p.add_argument("--chunk-cache", help="exact folder holding (or receiving) the 128³ scan blocks <kz>_<ky>_<kx>.npy of this volume")
    p.add_argument("--download-workers", type=int, default=16, help="parallel downloads of scan blocks (default 16)")
    p.add_argument("--threads", type=int, help="compute threads (default 4)")
    p.add_argument("--min-free-gb", type=float, default=1.0, help="wait while free memory is below this (default 1)")
    p.add_argument("--redo", default="", help="redo these stages even if done: block,sheets,page,ink")
    p.add_argument("--job-file", help=argparse.SUPPRESS)
    p.add_argument("--origin-json", help=argparse.SUPPRESS)

    p = cmd("sample", cmd_sample, "prepare the tiny bundled sample (a 2 mm piece of Scroll 1; nothing to download)")
    p.add_argument("--name", default="sample", help="name of the prepared segment (default: sample)")
    p.add_argument("--sample-dir", help="folder holding the sample data (default: sample/ of the repository)")

    p = cmd("list", cmd_list, "list the prepared segments")
    p.add_argument("--json", action="store_true", help="one JSON array")

    p = cmd("volpkg", cmd_volpkg, "list the volumes and segments of a VC3D volume package / project file / segments folder")
    p.add_argument("path")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--json", action="store_true")

    p = cmd("export", cmd_export, "write the retouched surface as a NEW tifxyz segment (never over the original)")
    p.add_argument("name")
    p.add_argument("--id", help="id (= folder name) of the new segment (default: <source id>_rt<date>)")
    p.add_argument("--out", help="folder to write the segment into (default: the exports folder of the segment)")
    p.add_argument("--to-volpkg", nargs="?", const="", metavar="PATH", help="write it as a new segment of a VC3D package (default: the one it came from)")
    p.add_argument("--grid", choices=["working", "original"], help="node layout: the working grid, or the layout of the source segment (default: original for --to-volpkg, else working)")
    p.add_argument("--zip", metavar="FILE_OR_FOLDER", help="write one zip instead: segment + offset field + journal")

    p = cmd("replay", cmd_replay, "replay the journal of gestures from the original surface and check it gives the same surface")
    p.add_argument("name")
    p.add_argument("--until", type=int, help="replay only the first N journal lines")
    p.add_argument("--out", help="write the replayed offset field (.npy)")

    p = cmd("compare", cmd_compare, "scan before / after + fibre-grid score (images and summary.json)")
    p.add_argument("name")
    p.add_argument("--out")

    p = cmd("render", cmd_render, "flat-page layers of the retouched surface, for your own ink-detection model")
    p.add_argument("name")
    p.add_argument("--out")
    p.add_argument("--first", type=int, default=-8, help="first depth, in voxels along the normal (default -8)")
    p.add_argument("--last", type=int, default=8, help="last depth (default 8)")
    p.add_argument("--stack", action="store_true", help="one multi-page layers.tif instead of one file per depth")

    p = cmd("ink-layer", cmd_ink_layer, "show an ink prediction (image of the size of the page) in the editor")
    p.add_argument("name")
    p.add_argument("layer", nargs="+", metavar='"Label=file.tif"')

    p = cmd("densify", cmd_densify, "resample a coarse tifxyz grid to a finer one (new folder)")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--step", type=float, default=4.0, help="target voxels between nodes (default 4)")

    p = cmd("flatten", cmd_flatten, "lay a (retouched) surface flat again by cloth relaxation — needs PyTorch (new folder)")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--device", default="cpu", help="cpu (default) or cuda")
    return ap


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = build_parser()
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 0
    a.fn(a)
    return 0
