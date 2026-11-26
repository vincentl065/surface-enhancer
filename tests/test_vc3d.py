"""VC3D round trip at the data level: open a volume package, prepare one of its segments, write the retouch back as a NEW segment."""
import hashlib
import json
import shutil

import numpy as np
import pytest

from surface_enhancer import tifxyz, vc3d
from surface_enhancer.export import export_to_segments_dir
from surface_enhancer.prepare import prepare_segment


def digest(folder):
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(folder.iterdir()) if f.is_file()}


def test_open_classic_volpkg_folder(volpkg):
    pkg = vc3d.open_volpkg(volpkg)
    assert pkg["kind"] == "folder" and pkg["name"] == "Sample package"
    assert [v["id"] for v in pkg["volumes"]] == ["20230205180739"] and pkg["volumes"][0]["voxel_um"] == 7.91
    by = {s["id"]: s for s in pkg["segments"]}
    assert by["sample_scroll1"]["loadable"] and by["sample_scroll1"]["step"] == 16
    assert pkg["output_segments"] == str(volpkg / "paths")
    assert vc3d.find_volume(pkg, None)["location"] == str(volpkg / "volumes" / "20230205180739")


def test_open_project_file_and_plain_folder(volpkg, tmp_path):
    proj = tmp_path / "scroll.volpkg.json"
    proj.write_text(json.dumps(dict(name="As project", version=1, segments=[str(volpkg / "paths")], output_segments=str(volpkg / "paths"),
                                    volumes=[str(volpkg / "volumes"), dict(location="https://dl.ash2txt.org/full-scrolls/Scroll1/PHercParis4.volpkg/volumes_zarr_standardized/54keV_7.91um_Scroll1A.zarr", tags=["x"]),
                                             "https://example.org/not-a-zarr-folder/"])), encoding="utf-8")
    pkg = vc3d.open_volpkg(proj)
    assert pkg["kind"] == "project" and pkg["name"] == "As project" and len(pkg["segments"]) >= 1
    remote = [v for v in pkg["volumes"] if v["remote"]]
    assert len(remote) == 2 and remote[0]["voxel_um"] == 7.91 and remote[0]["problem"] is None and remote[1]["problem"]
    plain = vc3d.open_volpkg(volpkg / "paths")
    assert plain["kind"] == "segments-folder" and plain["volumes"] == []
    with pytest.raises(vc3d.VolpkgError, match="no usable volume"):
        vc3d.find_volume(plain, None)
    with pytest.raises(vc3d.VolpkgError, match="neither a volume package"):
        vc3d.open_volpkg(tmp_path)


def test_broken_segments_are_listed_with_a_reason(volpkg, tmp_path):
    root = tmp_path / "p.volpkg"
    shutil.copytree(volpkg / "paths", root / "paths")
    (root / "paths" / "no_tifs").mkdir()
    (root / "paths" / "no_tifs" / "meta.json").write_text(json.dumps(dict(type="seg", uuid="no_tifs", format="tifxyz", scale=[0.05, 0.05])), encoding="utf-8")
    (root / "paths" / "old_kind").mkdir()
    (root / "paths" / "old_kind" / "meta.json").write_text(json.dumps(dict(type="seg", uuid="old_kind", format="obj")), encoding="utf-8")
    by = {s["id"]: s for s in vc3d.open_volpkg(root)["segments"]}
    assert by["sample_scroll1"]["loadable"] and not by["no_tifs"]["loadable"] and "missing" in by["no_tifs"]["problem"] and "not a tifxyz" in by["old_kind"]["problem"]


def test_round_trip_into_the_package(volpkg, settings):
    from surface_enhancer.core.segment import Segment
    pkg = vc3d.open_volpkg(volpkg)
    seg_info = vc3d.find_segment(pkg, "sample_scroll1")
    before = digest(volpkg / "paths" / "sample_scroll1")
    origin = dict(kind="volpkg", volpkg=pkg["path"], segment=seg_info["id"], segments_dir=str(volpkg / "paths"), output_segments=pkg["output_segments"])
    prepare_segment(seg_info["path"], vc3d.find_volume(pkg, None)["location"], "from_pkg", settings, densify_to=4, origin=origin, voxel_um=7.91)
    seg = Segment("from_pkg", donnees=settings.segments_dir, cache=settings.segment_cache_dir / "from_pkg")
    assert seg.etat()["origine"]["output_segments"] == str(volpkg / "paths")
    seg.geste("aimant_partout", dict(borne=6, bord=0.0, zones=False, greffe=False))
    r = export_to_segments_dir(seg, seg.cfg["origin"]["output_segments"], uuid="sample_scroll1_fixed")
    new = volpkg / "paths" / "sample_scroll1_fixed"
    assert r["vc3d_problems"] == [] and new.is_dir()
    assert digest(volpkg / "paths" / "sample_scroll1") == before, "the original segment is untouched"
    assert sorted(p.name for p in new.iterdir()) == ["meta.json", "x.tif", "y.tif", "z.tif"], "a plain segment: no stray file, no extra TIFF"
    meta = json.loads((new / "meta.json").read_text(encoding="utf-8"))
    assert meta["type"] == "seg" and meta["uuid"] == new.name and meta["format"] == "tifxyz" and meta["scale"] == [0.0625, 0.0625]
    assert meta["volume_id"] == "20230205180739", "unknown fields of the source meta.json are kept"
    assert r["shape"] == [17, 17], "written back with the node layout VC3D had"
    P, valid, step, _ = tifxyz.read_grid(new)
    lo, hi = np.array(meta["bbox"][0]), np.array(meta["bbox"][1])
    xyz = P[valid][:, ::-1]
    assert np.allclose(xyz.min(0), lo, atol=1e-3) and np.allclose(xyz.max(0), hi, atol=1e-3), "bbox is [[x0, y0, z0], [x1, y1, z1]] of the valid nodes"
    again = {s["id"]: s for s in vc3d.open_volpkg(volpkg)["segments"]}
    assert again["sample_scroll1_fixed"]["loadable"] and again["sample_scroll1_fixed"]["retouched"] and not again["sample_scroll1"]["retouched"]
    with pytest.raises(FileExistsError):                              # never over an existing segment, original or not
        export_to_segments_dir(seg, volpkg / "paths", uuid="sample_scroll1")
    with pytest.raises(FileExistsError):
        export_to_segments_dir(seg, volpkg / "paths", uuid="sample_scroll1_fixed")
