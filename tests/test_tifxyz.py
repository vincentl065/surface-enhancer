import json
from surface_enhancer.prepare import estimate
import zipfile

import numpy as np
import pytest
import tifffile

from conftest import SAMPLE_SEGMENT
from surface_enhancer import tifxyz


def test_inspect_and_read_sample():
    info = tifxyz.inspect(SAMPLE_SEGMENT)
    assert info["grid"] == [17, 17] and info["step"] == 16 and info["page"] == [257, 257]
    P, valid, step, meta = tifxyz.read_grid(SAMPLE_SEGMENT)
    assert P.shape == (17, 17, 3) and valid.all() and step == 16 and meta["uuid"] == "sample_scroll1"
    assert tifxyz.validate_for_vc3d(SAMPLE_SEGMENT) == []


def test_write_roundtrip_and_never_overwrite(tmp_path):
    P, valid, step, meta = tifxyz.read_grid(SAMPLE_SEGMENT)
    valid = valid.copy()
    valid[0, :3] = False
    z, y, x = P[..., 0], P[..., 1], P[..., 2]
    m = tifxyz.segment_meta(meta, "copy_1", 1 / step, tifxyz.bbox_xyz(x, y, z, valid), area_vx2_=tifxyz.area_vx2(P, valid), voxel_um=7.91, provenance=dict(tool="test"))
    dst = tifxyz.write_tifxyz(tmp_path / "copy_1", x, y, z, m, valid=valid, mask=True, side_files={"note.json": b"{}"})
    assert tifxyz.validate_for_vc3d(dst) == []
    P2, valid2, step2, meta2 = tifxyz.read_grid(dst)
    assert step2 == step and np.array_equal(valid2, valid) and np.allclose(P2[valid], P[valid])
    assert (P2[~valid] == -1).all(), "invalid nodes are written as -1, -1, -1 like VC3D does"
    assert meta2["type"] == "seg" and meta2["format"] == "tifxyz" and meta2["uuid"] == "copy_1" and meta2["scale"] == [1 / 16, 1 / 16]
    assert len(meta2["bbox"]) == 2 and len(meta2["bbox"][0]) == 3 and meta2["area_cm2"] > 0
    with tifffile.TiffFile(dst / "x.tif") as t:                      # what VC3D itself writes: 32-bit float, uncompressed, not tiled
        p = t.pages[0]
        assert p.dtype == np.float32 and p.compression == 1 and not p.is_tiled
    with pytest.raises(FileExistsError):
        tifxyz.write_tifxyz(tmp_path / "copy_1", x, y, z, m, valid=valid)
    with pytest.raises(tifxyz.TifxyzError):                          # folder name and uuid must agree
        tifxyz.write_tifxyz(tmp_path / "other", x, y, z, m, valid=valid)
    with pytest.raises(tifxyz.TifxyzError):                          # a TIFF next to a segment would become a VC3D channel
        tifxyz.write_tifxyz(tmp_path / "copy_2", x, y, z, dict(m, uuid="copy_2"), side_files={"offset.tif": b""})
    assert not list(tmp_path.glob(".tmp_sr_*")), "no temporary folder is left behind"


def test_vc3d_validation_reports_problems(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    assert tifxyz.validate_for_vc3d(d) == ["meta.json is missing"]
    (d / "meta.json").write_text(json.dumps(dict(type="segment", uuid="x", scale=[0.05])), encoding="utf-8")
    problems = " | ".join(tifxyz.validate_for_vc3d(d))
    for needle in ('"type" must be "seg"', "differs from the folder name", '"format" must be "tifxyz"', '"scale" must be two positive numbers', "x.tif is missing"):
        assert needle in problems


def test_zip_upload_is_safe(tmp_path):
    z = tmp_path / "seg.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in SAMPLE_SEGMENT.iterdir():
            zf.write(f, f"my segment/{f.name}")
        zf.writestr("my segment/../../evil.txt", "x")
        zf.writestr("my segment/huge.bin", "x" * 1000)
    out = tifxyz.extract_zip(z, tmp_path / "up")
    assert out.name == "my_segment" and sorted(p.name for p in out.iterdir()) == ["meta.json", "x.tif", "y.tif", "z.tif"]
    assert not (tmp_path / "evil.txt").exists()
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "nothing")
    with pytest.raises(tifxyz.TifxyzError, match="no x.tif"):
        tifxyz.extract_zip(empty, tmp_path / "up2")
    notzip = tmp_path / "notzip.zip"
    notzip.write_text("hello")
    with pytest.raises(tifxyz.TifxyzError, match="not a readable zip"):
        tifxyz.extract_zip(notzip, tmp_path / "up3")
    with pytest.raises(tifxyz.TifxyzError, match="over the upload limit"):
        tifxyz.extract_zip(z, tmp_path / "up4", max_bytes=1000)


def test_bad_scale_is_explained(tmp_path):
    with pytest.raises(tifxyz.TifxyzError, match="integer number of voxels"):
        tifxyz.grid_step(dict(scale=[0.3, 0.3]))
    with pytest.raises(tifxyz.TifxyzError, match="different step"):
        tifxyz.grid_step(dict(scale=[0.05, 0.1]))


def test_the_scan_is_guessed_only_when_the_folder_names_it(tmp_path):
    """An id of a public scan in meta.json (VC3D writes it as target_volume) or in the folder name is certain; a name of a scroll with one scan too; nothing else is guessed."""
    import shutil
    from surface_enhancer.detect import guess_scan, _scans
    scans = _scans()
    assert len(scans) > 60
    one = next(s for s in scans if s["scroll"] == "PHerc0125")

    def folder(name, **meta):
        d = tmp_path / name
        shutil.copytree(SAMPLE_SEGMENT, d)
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        m = {k: v for k, v in m.items() if k in ("type", "format", "scale", "bbox")}
        m.update(uuid=name.split("-on-")[0], **meta)
        (d / "meta.json").write_text(json.dumps(m), encoding="utf-8")
        return d

    g = guess_scan(folder("traced_in_vc3d", target_volume=one["name"] + ".zarr"))
    assert g and g["url"] == one["url"] and g["sure"] and "target_volume" in g["how"]
    g = guess_scan(folder(f"seg-on-{one['id']}-9.36um.tifxyz"))
    assert g and g["url"] == one["url"] and "name of the folder" in g["how"]
    assert guess_scan(folder("PHerc0125_by_name"))["scroll"] == "PHerc0125"          # the only public scan of that scroll
    assert guess_scan(folder("nothing_says_where")) is None
    assert estimate(folder("in_the_summary", volume=one["id"]))["scan_guess"]["url"] == one["url"]
