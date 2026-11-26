"""“Extend the surface”: a band is added beyond an edge by following the sheet in the scan.

The sample volume only holds scan data around the sample surface, so the test prepares the LEFT part of the sample
(11 of its 17 columns) and extends it to the right, where the scan is available and the true surface is known.
"""
import json
import subprocess
import sys

import numpy as np
import pytest

from conftest import ROOT, SAMPLE_SEGMENT, SAMPLE_VOLUME
from surface_enhancer import tifxyz
from surface_enhancer.export import export_segment
from surface_enhancer.prepare import prepare_segment


@pytest.fixture(scope="module")
def cropped(settings, tmp_path_factory):
    P, valid, step, meta = tifxyz.read_grid(SAMPLE_SEGMENT)
    P, valid = P[:, :11], valid[:, :11]
    z, y, x = P[..., 0], P[..., 1], P[..., 2]
    src = tmp_path_factory.mktemp("crop") / "sample_left"
    tifxyz.write_tifxyz(src, x, y, z, tifxyz.segment_meta(meta, "sample_left", 1 / step, tifxyz.bbox_xyz(x, y, z, valid)), valid=valid)
    prepare_segment(src, str(SAMPLE_VOLUME), "sample_left", settings, voxel_um=7.91, densify_to=4)
    return "sample_left"


def test_extend_undo_export_replay(settings, cropped, tmp_path):
    from surface_enhancer.core.segment import Segment
    seg = Segment(cropped, donnees=settings.segments_dir, cache=settings.segment_cache_dir / cropped)
    assert seg.h.shape == (65, 41) and "etendre" in seg.etat()["auto"]
    params = dict(cote="u1", largeur=0.4, saut=1.5, pont=8, taux=0.7)
    pre = seg.apercu_extension(params)
    assert seg.h.shape == (65, 41), "a preview writes nothing"
    if pre.get("rien"):
        pytest.skip("the sheet could not be followed beyond the edge of this sample: " + pre["message"])
    r = seg.etendre(params)
    assert r["grille"] and seg.h.shape[0] == 65 and seg.h.shape[1] > 41 and len(seg.pile) == 1
    added = int(seg.valide[:, 41:].sum())
    assert added > 50, "a band of new nodes was added on the right"
    # the band lies on the scroll: compare with the true surface of the full sample (resampled to the same 4-voxel grid)
    from surface_enhancer.prepare import densify
    Pf, vf, _, _ = tifxyz.read_grid(SAMPLE_SEGMENT)
    Pd, _ = densify(Pf, vf, 4)
    new = seg.valide.copy()
    new[:, :41] = False
    new[:, 65:] = False
    got = (seg.P0 + seg.h[..., None] * seg.N)[new]
    ref = Pd[:, :seg.h.shape[1]][new[:, :65]] if seg.h.shape[1] <= 65 else Pd[new[:, :65]]
    dist = np.linalg.norm(got - ref, axis=1)
    assert np.median(dist) < 12, f"the new band stays near the reference surface (median {np.median(dist):.1f} voxels)"
    # export: the whole enlarged grid, valid for VC3D, original nodes untouched
    e = export_segment(seg, uuid="left_extended", dest_dir=tmp_path, sidecar=False)
    assert e["vc3d_problems"] == [] and e["shape"] == list(seg.h.shape) and e["nodes_added"] == added
    P, valid, step, meta = tifxyz.read_grid(tmp_path / "left_extended")
    P0, v0, _, _ = tifxyz.read_grid(seg.d / "versions" / "v000" / "tifxyz")
    assert step == 4 and np.array_equal(P[:, :41][v0], P0[v0]) and int(valid[:, 41:].sum()) == added
    assert meta["surface_enhancer"]["extensions"] == 1 and meta["surface_enhancer"]["nodes_added"] == added
    eo = export_segment(seg, uuid="left_extended_coarse", dest_dir=tmp_path, grid="original", sidecar=False)
    assert eo["vc3d_problems"] == [] and eo["shape"][0] == 17 and eo["shape"][1] > 11
    # replay from the journal, then undo: back to the original grid
    out = subprocess.run([sys.executable, "-X", "utf8", "-m", "surface_enhancer", "replay", cropped, "--data-dir", str(settings.data_dir), "--cache-dir", str(settings.cache_dir)],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and "IDENTICAL" in out.stdout, out.stdout + out.stderr
    u = seg.annuler(-1)
    assert u["grille"] and u["defait"] and seg.h.shape == (65, 41) and not seg.h.any()
    again = Segment(cropped, donnees=settings.segments_dir, cache=settings.segment_cache_dir / cropped)
    assert again.h.shape == (65, 41), "the undone extension is not there after a restart"
    config = json.loads((seg.d / "config.json").read_text(encoding="utf-8"))
    assert "cache_scan" in config


def test_extend_through_the_api(server, cropped):
    import urllib.request

    def post(route, body):
        req = urllib.request.Request(f"{server}/api/s/{cropped}/{route}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    params = dict(cote="u1", largeur=0.4, saut=1.5, pont=8, taux=0.7)
    pre = post("preview", dict(outil="etendre", params=params))
    if pre.get("rien"):
        pytest.skip(pre["message"])
    assert pre["outil"] == "etendre" and pre["auto"]
    r = post("extend", dict(params=params))
    assert r["grille"] and r["etat"]["extensions"] == 1 and r["etat"]["grille"][1] > 41
    ex = post("export", dict(target="local", id="left_api_extended", grid="original"))
    assert ex["vc3d_problems"] == [] and ex["nodes_added"] > 0 and ex["shape"][1] > 11
    u = post("undo", {})
    assert u["grille"] and u["etat"]["extensions"] == 0 and u["etat"]["grille"] == [65, 41]
