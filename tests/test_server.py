"""The HTTP API, through real requests: upload a zip, prepare it in the background, edit, download."""
import io
import json
import time
import urllib.error
import urllib.request
import zipfile

import numpy as np
import pytest

from conftest import SAMPLE_SEGMENT, SAMPLE_VOLUME


def call(url, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def jcall(url, body=None, **kw):
    code, raw, _ = call(url, body, **kw)
    return code, json.loads(raw)


def sample_zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as zf:
        for f in SAMPLE_SEGMENT.iterdir():
            zf.write(f, f"sample_scroll1/{f.name}")
    return b.getvalue()


def wait_job(server, job, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        code, j = jcall(f"{server}/api/jobs/{job}")
        assert code == 200
        if j["state"] != "running":
            return j
        time.sleep(0.5)
    raise AssertionError("the preparation did not finish in time")


def test_home_and_static_pages(server):
    code, home = jcall(f"{server}/api/home")
    assert code == 200 and home["sample_available"] and any(s["name"] == "sample" and s["ready"] for s in home["segments"])
    for page, needle in (("/", b"tabs.js"), ("/index.html", b"Your segments"), ("/tabs.html", b"tabs.js"), ("/editor.html", b"Export the retouched surface"), ("/home.js", b"refresh"), ("/style.css", b"Okabe")):
        code, raw, _ = call(server + page)
        assert code == 200 and needle in raw
    assert call(server + "/../surface_enhancer/server.py")[0] == 404
    assert call(server + "/api/nothing")[0] == 404


def test_requests_from_elsewhere_are_refused(server):
    assert jcall(f"{server}/api/home", headers={"Host": "attacker.example"})[0] == 403
    assert jcall(f"{server}/api/prepare", {}, headers={"Origin": "https://attacker.example"})[0] == 403
    code, j = call(f"{server}/api/prepare", raw=b"{}", headers={"Content-Type": "text/plain"})[:2]
    assert code == 415


def test_locate_gives_the_position_in_the_scan(server):
    code, j = jcall(f"{server}/api/s/sample/locate")
    pts = [p for p in j["xyz"] if p]
    assert code == 200 and len(j["xyz"]) == j["n"][0] * j["n"][1] and pts and all(len(p) == 3 for p in pts) and j["pas"] >= 1
    idx = json.loads(call(server + "/scrolls/index.json")[1])
    assert idx["volumes"] and all(call(f"{server}/scrolls/{v['file']}")[0] == 200 for v in list(idx["volumes"].values())[:2])


def test_clear_errors(server):
    code, j = jcall(f"{server}/api/s/does_not_exist/state")
    assert code == 404 and "no prepared segment" in j["error"]
    code, j = jcall(f"{server}/api/inspect", dict(path="/definitely/not/here"))
    assert code == 400 and "not a folder" in j["error"]
    code, j = jcall(f"{server}/api/volume/check", dict(volume="/definitely/not/here.zarr"))
    assert code == 400 and "volume not found" in j["error"]
    code, j = jcall(f"{server}/api/volpkg/open", dict(path="/definitely/not/here.volpkg"))
    assert code == 400 and "not found" in j["error"]
    code, j = jcall(f"{server}/api/upload?name=x.zip", raw=b"this is not a zip", headers={"Content-Type": "application/zip"})
    assert code == 400 and "not a readable zip" in j["error"]
    code, j = jcall(f"{server}/api/prepare", dict(source=dict(kind="path", path=str(SAMPLE_SEGMENT)), volume="", name="x"))
    assert code == 400 and "no volume given" in j["error"]
    code, j = jcall(f"{server}/api/prepare", dict(source=dict(kind="path", path=str(SAMPLE_SEGMENT)), volume=str(SAMPLE_VOLUME), name="bad name!"))
    assert code == 400 and "letters, digits" in j["error"]


def test_upload_prepare_edit_download(server, settings):
    code, vol = jcall(f"{server}/api/volume/check", dict(volume=str(SAMPLE_VOLUME)))
    assert code == 200 and vol["shape"] == [14376, 7888, 8096] and vol["dtype"] == "uint8" and not vol["remote"]
    code, up = jcall(f"{server}/api/upload?name=sample_scroll1.zip", raw=sample_zip(), headers={"Content-Type": "application/zip"})
    assert code == 200 and up["summary"]["grid"] == [17, 17] and up["summary"]["step"] == 16 and up["summary"]["cache_bytes"] > 5e6
    code, started = jcall(f"{server}/api/prepare", dict(source=dict(kind="upload", id=up["upload"]), volume=str(SAMPLE_VOLUME), name="uploaded", densify_to=4, voxel_um=7.91))
    assert code == 200, started
    j = wait_job(server, started["job"])
    assert j["state"] == "done" and j["fraction"] == 1.0, j
    base = f"{server}/api/s/uploaded"
    code, st = jcall(base + "/state")
    assert code == 200 and st["grille"] == [65, 65] and st["densifie"] == 4 and st["origine"]["kind"] == "upload"
    assert call(base + "/tile?n=0&y=0&x=0&c=0")[1][:2] == b"\xff\xd8", "tiles are JPEG"
    assert len(call(base + "/sections?v=128&u=128&w=60")[1]) > 5000 and len(call(base + "/scores")[1]) > 500
    assert len(call(base + "/patch3d?v=128&u=128&whole=1")[1]) > 10000
    code, g = jcall(base + "/gesture", dict(outil="aimant", params=dict(points=[[30, 30]], rayon=10, borne=6)))
    assert code == 200 and g["pile"] == 1 and g["deplacement_max"] > 0
    code, g = jcall(base + "/gesture", dict(outil="nonsense", params={}))
    assert code == 400 and "unknown tool" in g["error"]
    code, raw, headers = call(base + "/download?what=bundle&grid=original")
    assert code == 200 and "attachment" in headers["Content-Disposition"]
    zf = zipfile.ZipFile(io.BytesIO(raw))
    root = [n for n in zf.namelist() if n.endswith("/meta.json")][0].split("/")[0]
    meta = json.loads(zf.read(f"{root}/meta.json"))
    assert meta["uuid"] == root and meta["scale"] == [0.0625, 0.0625] and meta["surface_enhancer"]["nodes_moved"] > 0
    off = np.load(io.BytesIO(zf.read(f"{root}.retouch/offset_along_normal.npy")))
    assert off.shape == (65, 65) and np.abs(off).max() > 0
    assert jcall(base + "/undo", {})[1]["pile"] == 0 and jcall(base + "/redo", {})[1]["pile"] == 1
    code, ex = jcall(base + "/export", dict(target="local", id="uploaded_v1", grid="working"))
    assert code == 200 and ex["vc3d_problems"] == [] and ex["shape"] == [65, 65]
    code, ex2 = jcall(base + "/export", dict(target="local", id="uploaded_v1"))
    assert code == 400 and "already exists" in ex2["error"]
    code, ex3 = jcall(base + "/export", dict(target="volpkg"))
    assert code == 400 and "no VC3D segments folder" in ex3["error"]
    # a second segment with the same name from another surface is refused, not silently replaced
    code, j = jcall(f"{server}/api/prepare", dict(source=dict(kind="path", path=str(SAMPLE_SEGMENT)), volume=str(SAMPLE_VOLUME), name="uploaded"))
    assert code == 409 and "already exists" in j["error"]
    # remove: needs the name typed, keeps the small data in the trash, frees the cache
    assert jcall(base + "/remove", dict(confirm="nope"))[0] == 400
    code, rm = jcall(base + "/remove", dict(confirm="uploaded"))
    assert code == 200 and rm["cache_freed_bytes"] > 5e6 and (settings.data_dir / "trash").is_dir()
    assert jcall(base + "/state")[0] == 404


def test_volpkg_through_the_api(server, volpkg):
    code, pkg = jcall(f"{server}/api/volpkg/open", dict(path=str(volpkg)))
    assert code == 200 and "sample_scroll1" in [s["id"] for s in pkg["segments"]] and pkg["volumes"][0]["id"] == "20230205180739"
    code, started = jcall(f"{server}/api/prepare", dict(source=dict(kind="volpkg", volpkg=str(volpkg), segment="sample_scroll1"), volume="", name="pkg_api", densify_to=4))
    assert code == 200, started
    assert wait_job(server, started["job"])["state"] == "done"
    base = f"{server}/api/s/pkg_api"
    jcall(base + "/gesture", dict(outil="pousser", params=dict(points=[[30, 30]], rayon=8, signe=-1, pas=1)))
    code, ex = jcall(base + "/export", dict(target="volpkg", id="sample_scroll1_api"))
    assert code == 200 and ex["vc3d_problems"] == [] and (volpkg / "paths" / "sample_scroll1_api" / "meta.json").is_file() and ex["shape"] == [17, 17]
    assert volpkg.as_posix() in " ".join(jcall(f"{server}/api/home")[1]["recent_volpkgs"]).replace("\\", "/")
