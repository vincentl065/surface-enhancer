"""Have the C++ tifxyz loader of VC3D read what Surface Enhancer exports (see docs/USING_WITH_VC3D.md).

    python tools_dev/check_with_vc3d_loader.py <folder of VC3D binaries (vc_tifxyz2obj + lib/)> [docker image]

The sample is prepared in a temporary folder, retouched (magnet, then a line through three points in a section, then
Extend the surface), and exported three ways: working grid, original node layout, and the original sample as a
reference. Each export is then converted to .obj by ``vc_tifxyz2obj`` — the tool of VC3D that loads a segment with
``load_quad_from_tifxyz`` — run in the Linux image the binaries were built in. What is compared: the tool ends without
error, and the vertices it wrote are the valid nodes of the export, at the same positions.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
IMAGE = "ghcr.io/scrollprize/vc3d-deps/linux:sha-0c371b1d472c5281b703d65517e980d945da693f"


def main():
    from surface_enhancer import tifxyz
    from surface_enhancer.config import load_settings
    from surface_enhancer.core.segment import Segment
    from surface_enhancer.export import export_segment
    from surface_enhancer.prepare import prepare_segment
    vc = Path(sys.argv[1]).resolve()
    image = sys.argv[2] if len(sys.argv) > 2 else IMAGE
    work = Path(tempfile.mkdtemp(prefix="sr_vc3d_"))
    settings = load_settings(work / "data", work / "cache", port=0).ensure()
    sample = ROOT / "sample" / "segment" / "sample_scroll1"
    prepare_segment(sample, str(ROOT / "sample" / "volume" / "sample_scroll1.zarr"), "sample", settings, voxel_um=7.91, densify_to=4)
    seg = Segment("sample", donnees=settings.segments_dir, cache=settings.segment_cache_dir / "sample")
    seg.geste("aimant", dict(points=[[20, 20], [30, 34]], rayon=10, borne=6))
    seg.geste("ligne", dict(axe="u", fixe=40, points=[[20, float(seg.h[40, 20]) + 5], [24, float(seg.h[40, 24]) + 11], [28, float(seg.h[40, 28]) + 3]], rayon=8, saut=3))
    try:
        seg.etendre(dict(cote="u1", largeur=0.2))
    except Exception as e:
        print("Extend the surface was not applied here:", e)
    out = work / "exports"
    out.mkdir()
    export_segment(seg, uuid="retouched_working", dest_dir=out, sidecar=False)
    export_segment(seg, uuid="retouched_original_layout", dest_dir=out, grid="original", sidecar=False)
    shutil.copytree(sample, out / "untouched_sample")
    script = "export LD_LIBRARY_PATH=/vc/bin/lib:$LD_LIBRARY_PATH; cd /w; for s in */; do s=${s%/}; echo \"== $s\"; /vc/bin/vc_tifxyz2obj /w/$s /w/$s.obj; echo \"exit $?\"; done"
    r = subprocess.run(["docker", "run", "--rm", "-v", f"{out}:/w", "-v", f"{vc}:/vc:ro", image, "bash", "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-3000:], r.stderr[-1500:])
    ok = True
    for d in sorted(p for p in out.iterdir() if p.is_dir()):
        obj = out / f"{d.name}.obj"
        P, valid, step, meta = tifxyz.read_grid(d)
        if not obj.exists():
            print(f"FAILED {d.name}: no .obj written")
            ok = False
            continue
        v = np.array([[float(x) for x in l.split()[1:4]] for l in obj.read_text().splitlines() if l.startswith("v ")], np.float64)
        ours = P[valid][:, ::-1].astype(np.float64)                      # (x, y, z)
        same_count = len(v) == len(ours)
        far = float(np.abs(np.sort(v, axis=0) - np.sort(ours, axis=0)).max()) if same_count else float("nan")
        good = same_count and far < 1e-2
        ok = ok and good
        print(("OK    " if good else "FAILED"), f"{d.name}: grid {valid.shape[0]} × {valid.shape[1]}, one node every {step} vx, {int(valid.sum())} valid nodes; "
              f"VC3D loaded {len(v)} vertices; largest coordinate difference {far:.4f} vx")
    print("kept in", work)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
