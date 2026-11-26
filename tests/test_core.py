"""The editing core on the bundled sample: gestures, the no-step rule, undo, journal replay, export."""
import json
import subprocess
import sys

import numpy as np
import pytest
import tifffile

from conftest import ROOT, SAMPLE_SEGMENT
from surface_enhancer import tifxyz
from surface_enhancer.export import download_bytes, export_segment, render_layers


def biggest_step(seg, h):
    cu, cv = seg._marches_tout(h)
    return float(np.nanmax(np.abs(np.stack([cu, cv]))))


def test_prepared_layout(settings, prepared):
    d = settings.segments_dir / prepared
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    assert cfg["grille"] == [65, 65] and cfg["pas"] == 4 and cfg["densified_factor"] == 4 and cfg["blocs_absents"] == 0
    block = np.load(settings.segment_cache_dir / prepared / "bloc.npy", mmap_mode="r")
    assert block.shape == (257, 257, 81) and block[..., 40].mean() > 40, "the straightened block holds real scan data"
    assert (d / "versions" / "v000" / "source" / "x.tif").exists(), "the untouched upload is kept"
    for c in "xyz":                                                   # the source folder itself was not modified
        assert tifffile.imread(SAMPLE_SEGMENT / f"{c}.tif").shape == (17, 17)


def test_magnet_moves_towards_the_sheet_without_steps(segment):
    h0 = segment.h.copy()
    step0 = biggest_step(segment, h0)
    r = segment.geste("aimant", dict(points=[[30, 30], [36, 40]], rayon=12, borne=6))
    assert not r.get("rien") and 0 < r["deplacement_max"] <= 6.01
    assert biggest_step(segment, segment.h) <= max(1.0, step0) + 0.02, "a gesture never creates a step of more than 1 voxel"
    moved = np.abs(segment.h - h0) > 1e-3
    dist = lambda h: np.nanmin(np.abs(segment.pos - h[..., None]), -1)
    assert np.nanmean(dist(segment.h)[moved]) < np.nanmean(dist(h0)[moved]), "moved nodes are closer to a detected sheet"
    r = segment.annuler(-1)
    assert r["defait"] and np.array_equal(segment.h, h0), "undo restores the exact surface"
    segment.annuler(+1)
    assert not np.array_equal(segment.h, h0)


def test_random_gestures_keep_the_rule_and_undo_all(segment):
    rng = np.random.default_rng(7)
    h0 = segment.h.copy()
    limit = max(1.0, biggest_step(segment, h0)) + 0.02
    n0 = len(segment.pile)
    for _ in range(25):
        tool = rng.choice(["aimant", "pousser", "ligne", "bord"])
        pts = [[float(rng.uniform(0, 64)), float(rng.uniform(0, 64))] for _ in range(int(rng.integers(1, 4)))]
        if tool == "ligne":
            p = dict(axe=str(rng.choice(["u", "v"])), fixe=float(rng.uniform(2, 62)), rayon=float(rng.uniform(2, 14)),
                     points=[[float(rng.uniform(4, 60)), float(rng.uniform(-20, 20))] for _ in range(int(rng.integers(1, 4)))])
        elif tool == "pousser":
            p = dict(points=pts, rayon=float(rng.uniform(2, 12)), signe=int(rng.choice([-1, 1])), pas=1)
        else:
            p = dict(points=pts, rayon=float(rng.uniform(2, 12)), borne=float(rng.integers(2, 12)), bord=float(rng.choice([-2, 2])) if tool == "bord" else 0.0)
        segment.geste(str(tool), p)
        assert biggest_step(segment, segment.h) <= limit, f"{tool} created a step"
        assert np.abs(segment.h).max() <= 32.001
    while len(segment.pile) > n0:
        segment.annuler(-1)
    assert np.array_equal(segment.h, h0)


def test_automatic_preview_then_apply_is_one_gesture(segment):
    n0 = len(segment.pile)
    params = dict(borne=6, bord=0.0, zones=False, greffe=False)
    blob = segment.apercu("aimant_partout", params)
    assert len(blob) > 100 and len(segment.pile) == n0, "a preview writes nothing"
    r = segment.geste("aimant_partout", params)
    assert len(segment.pile) == n0 + 1 and r["auto"]["deplaces"] > 0 and r["auto"]["creees"] == 0
    fib = r["auto"]["fibres"]["page"]
    assert fib["avant"] is not None and fib["apres"] is not None


def test_export_only_changes_moved_nodes(segment, tmp_path):
    segment.geste("aimant", dict(points=[[20, 20]], rayon=8, borne=6))
    r = export_segment(segment, uuid="exp_working", dest_dir=tmp_path, sidecar=False)
    assert r["vc3d_problems"] == [] and r["shape"] == [65, 65] and r["nodes_moved"] > 0
    P, valid, step, meta = tifxyz.read_grid(tmp_path / "exp_working")
    P0, _, _, _ = tifxyz.read_grid(segment.d / "versions" / "v000" / "tifxyz")
    moved = segment.valide & (segment.h != 0)
    assert step == 4 and np.array_equal(P[~moved], P0[~moved]) and not np.allclose(P[moved], P0[moved])
    expected = segment.P0 + segment.h[..., None] * segment.N
    assert np.allclose(P[moved], expected[moved], atol=1e-3)
    prov = meta["surface_enhancer"]
    assert prov["source_id"] == "sample_scroll1" and prov["nodes_moved"] == int(moved.sum()) and prov["gestures"] == len(segment.pile)
    assert ":" not in prov["volume"] and "\\" not in prov["volume"] and "/" not in prov["volume"], "no local path leaks into the exported meta.json"
    # original node layout (one node every 16 voxels): same shape as the upload, untouched nodes bit-identical to it
    r2 = export_segment(segment, uuid="exp_original", dest_dir=tmp_path, grid="original", sidecar=False)
    assert r2["shape"] == [17, 17] and r2["vc3d_problems"] == []
    Po, _, so, mo = tifxyz.read_grid(tmp_path / "exp_original")
    Ps, _, _, _ = tifxyz.read_grid(SAMPLE_SEGMENT)
    sub = moved[::4, ::4]
    assert so == 16 and np.array_equal(Po[~sub], Ps[~sub]) and mo["scale"] == [1 / 16, 1 / 16]
    with pytest.raises(FileExistsError):
        export_segment(segment, uuid="exp_original", dest_dir=tmp_path, grid="original", sidecar=False)


def test_download_bundle_and_layers(segment, tmp_path):
    import io
    import zipfile
    segment.geste("pousser", dict(points=[[40, 40]], rayon=6, signe=-1, pas=1))
    name, body, ctype = download_bytes(segment, "bundle")
    assert name.endswith(".zip") and ctype == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(body)).namelist()
    uid = name[:-4]
    for f in ("meta.json", "x.tif", "y.tif", "z.tif"):
        assert f"{uid}/{f}" in names
    for f in ("offset_along_normal.npy", "journal.jsonl", "provenance.json", "marked_areas.png", "README.txt"):
        assert f"{uid}.retouch/{f}" in names
    off = np.load(io.BytesIO(download_bytes(segment, "offset")[1]))
    assert np.array_equal(off, segment.h)
    assert b'"outil": "pousser"' in download_bytes(segment, "journal")[1]
    r = render_layers(segment, tmp_path / "layers", -2, 2)
    assert r["layers"] == 5 and tifffile.imread(tmp_path / "layers" / "02.tif").shape == (257, 257)


def test_journal_replay_gives_the_same_surface(settings, segment):
    segment.geste("aimant", dict(points=[[10, 50], [14, 44]], rayon=7, borne=5))
    segment.geste("marquer", dict(points=[[30, 30]], rayon=5, valeur=1))
    segment.annuler(-1)
    out = subprocess.run([sys.executable, "-X", "utf8", "-m", "surface_enhancer", "replay", "sample", "--data-dir", str(settings.data_dir), "--cache-dir", str(settings.cache_dir)],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and "IDENTICAL" in out.stdout, out.stdout + out.stderr


def test_compare_writes_images(segment, tmp_path):
    from surface_enhancer.tools.compare import compare
    segment.geste("aimant", dict(points=[[32, 32]], rayon=20, borne=6))
    r = compare(segment, tmp_path / "cmp")
    for f in ("ct_before.png", "ct_after.png", "ct_before_after.jpg", "fibre_score_before_after.jpg", "summary.json"):
        assert (tmp_path / "cmp" / f).stat().st_size > 200
    assert r["nodes_moved"] > 0


def test_sheet_jump_map_finds_a_region_moved_to_the_next_sheet(segment):
    """Nothing is written: the sheet under the anchor is followed, and a region pushed onto the neighbouring sheet is reported as such."""
    import json
    import struct

    def read(anchor):
        b = segment.sauts(dict(ancre=anchor))
        n = struct.unpack("<I", b[:4])[0]
        e = json.loads(b[4:4 + n])
        d = e["tableaux"]["carte"]
        return e, np.frombuffer(b[4 + n + d["debut"]:4 + n + d["debut"] + d["octets"]], np.uint8).reshape(d["forme"])

    h0, gen = segment.h.copy(), segment.gen
    e, before = read([10, 10])
    assert before.shape == segment.h.shape and abs(sum(e["parts"].values()) - 100) < 0.5 and segment.gen == gen and np.array_equal(segment.h, h0)
    followed = before == 1
    assert followed.mean() > 0.2, "the reference sheet is followed over a good part of the sample"
    region = np.zeros_like(followed)
    region[36:56, 36:56] = True
    try:
        segment.h[region] += e["espacement"]                       # as if this region had been traced one sheet lower
        _, after = read([10, 10])
    finally:
        segment.h[:] = h0
    seen = after[region & followed]
    assert seen.size > 50 and np.isin(seen, (5, 6, 7)).mean() > 0.6, "most of the moved region is reported one sheet (or more) below"
    assert (after[followed & ~region] == 1).mean() > 0.9, "the rest of the followed surface is still reported on the reference sheet"
