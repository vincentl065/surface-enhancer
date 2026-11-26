"""Local web server of Surface Enhancer (standard library only).

It listens on 127.0.0.1 by default: nothing leaves the machine. Home page: prepared segments, upload, VC3D volume
packages. Editor: ``/editor.html?s=<segment>``. The HTTP API is described in docs/HTTP_API.md.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid as uuidlib
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, tifxyz, vc3d
from .config import Settings, sample_dir
from .prepare import PrepareError, estimate
from .volume import VolumeError, describe, normalize_location

WEB = Path(__file__).resolve().parent / "web"
PACKAGE_PARENT = Path(__file__).resolve().parents[1]
SAMPLE = sample_dir()
USER_ERRORS = (ValueError, FileExistsError, FileNotFoundError, PrepareError, PermissionError)


class ApiError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class App:
    """Everything the server knows: settings, opened segments, background preparation jobs."""

    def __init__(self, settings: Settings, max_open: int = 4):
        self.settings = settings.ensure()
        self.max_open = max_open
        self.open: OrderedDict = OrderedDict()
        self.lock = threading.RLock()
        self.procs: dict = {}

    # ───────────── library ─────────────
    def _state(self) -> dict:
        try:
            return json.loads(self.settings.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, **changes) -> None:
        s = self._state()
        s.update(changes)
        tmp = self.settings.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.settings.state_file)

    def remember_volpkg(self, path: str) -> None:
        r = [p for p in self._state().get("recent_volpkgs", []) if p != path]
        self._save_state(recent_volpkgs=([path] + r)[:8])

    def segment_summary(self, d: Path) -> dict | None:
        try:
            cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        cache = self.settings.segment_cache_dir / d.name
        if not (cache / "bloc.npy").exists():
            cache = Path(cfg.get("cache", cache))
        ready = (cache / "bloc.npy").exists() and (cache / "pics_pos.npy").exists() and (cache / "page_L1.npy").exists()
        versions = sorted(p.name for p in (d / "versions").iterdir() if p.is_dir()) if (d / "versions").is_dir() else []
        gestures, modified = 0, cfg.get("prepare")
        if versions:
            try:
                m = json.loads((d / "versions" / versions[-1] / "meta.json").read_text(encoding="utf-8"))
                gestures, modified = int(m.get("gestes_appliques", 0)), m.get("modifiee") or modified
            except (OSError, ValueError):
                pass
        H, W = cfg.get("page", [0, 0])
        um = float(cfg.get("um") or 0)
        try:
            cache_bytes = (cache / "bloc.npy").stat().st_size if ready else 0
        except OSError:
            cache_bytes = 0
        exports = sorted(p.name for p in (d / "exports").iterdir() if p.is_dir() and not p.name.endswith(".retouch")) if (d / "exports").is_dir() else []
        return dict(name=d.name, ready=bool(ready), page=[H, W], size_mm=[round(H * um / 1000, 1), round(W * um / 1000, 1)] if um else None, grid=cfg.get("grille"),
                    step=cfg.get("pas"), volume=cfg.get("volume"), scroll=(re.search(r"PHerc\w+", str(cfg.get("volume", ""))) or [""])[0], prepared=cfg.get("prepare"),
                    modified=modified, gestures=gestures, version=versions[-1] if versions else None, versions=len(versions), cache_bytes=cache_bytes,
                    origin=cfg.get("origin") or {}, source=cfg.get("surface"), missing_blocks=int(cfg.get("blocs_absents") or 0), exports=exports[-5:],
                    problem=None if ready else f"its cache is missing ({cache}): prepare it again")

    def library(self) -> list:
        out = []
        if self.settings.segments_dir.is_dir():
            for d in sorted(self.settings.segments_dir.iterdir()):
                if d.is_dir():
                    s = self.segment_summary(d)
                    if s:
                        out.append(s)
        out.sort(key=lambda s: s.get("modified") or "", reverse=True)
        return out

    def segment(self, name: str):
        from .core.segment import Segment, SegmentError
        tifxyz.check_name(name)
        with self.lock:
            if name in self.open:
                self.open.move_to_end(name)
                return self.open[name]
            if not (self.settings.segments_dir / name / "config.json").exists():
                raise ApiError(f"no prepared segment named “{name}”", 404)
            try:
                seg = Segment(name, donnees=self.settings.segments_dir, cache=self.settings.segment_cache_dir / name)
            except SegmentError as e:
                raise ApiError(str(e), 409)
            self.open[name] = seg
            while len(self.open) > self.max_open:
                self.open.popitem(last=False)
            return seg

    def remove_segment(self, name: str) -> dict:
        """Move the small data of a segment to ``<data>/trash/`` (recoverable) and delete its big cache (re-creatable)."""
        tifxyz.check_name(name)
        d = self.settings.segments_dir / name
        if not d.is_dir():
            raise ApiError(f"no segment named “{name}”", 404)
        with self.lock:
            seg = self.open.pop(name, None)
            if seg is not None:
                for a in ("bloc", "pyr", "encre"):
                    try:
                        setattr(seg, a, None)
                    except Exception:
                        pass
                del seg
            import gc
            gc.collect()
            trash = self.settings.data_dir / "trash" / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"
            trash.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(trash))
            cache = self.settings.segment_cache_dir / name
            freed = sum(f.stat().st_size for f in cache.rglob("*") if f.is_file()) if cache.is_dir() else 0
            shutil.rmtree(cache, ignore_errors=True)
            return dict(removed=name, kept_in=str(trash), cache_freed_bytes=int(freed))

    # ───────────── uploads ─────────────
    def receive_upload(self, stream, length: int, filename: str) -> dict:
        limit = self.settings.max_upload_mb * (1 << 20)
        if length <= 0:
            raise ApiError("empty upload: choose the .zip of a segment folder (x.tif, y.tif, z.tif, meta.json)")
        if length > limit:
            raise ApiError(f"this file is {length / 1e6:.0f} MB: over the upload limit of {self.settings.max_upload_mb} MB (use the local path instead, or raise max_upload_mb)", 413)
        token = time.strftime("%Y%m%d_%H%M%S_") + uuidlib.uuid4().hex[:6]
        d = self.settings.uploads_dir / token
        d.mkdir(parents=True)
        z = d / "upload.zip"
        left = length
        with open(z, "wb") as f:
            while left > 0:
                b = stream.read(min(left, 1 << 20))
                if not b:
                    break
                f.write(b)
                left -= len(b)
        try:
            if left:
                raise ApiError("the upload was cut before the end: try again")
            folder = tifxyz.extract_zip(z, d, limit)
            info = estimate(folder)
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        z.unlink(missing_ok=True)
        if folder.name in ("upload", ""):
            folder = folder.rename(d / tifxyz.safe_name(Path(filename).stem or "segment"))
            info = estimate(folder)
        return dict(upload=token, folder=folder.name, summary=info, suggested_name=tifxyz.safe_name(info["id"] if info["id"] != folder.name else folder.name))

    def upload_folder(self, token: str) -> Path:
        if not re.fullmatch(r"[0-9A-Za-z_]+", token or ""):
            raise ApiError("unknown upload")
        d = self.settings.uploads_dir / token
        if not d.is_dir():
            raise ApiError("this upload is gone: upload the zip again", 404)
        return tifxyz.find_tifxyz(d)

    # ───────────── preparation jobs ─────────────
    def start_prepare(self, p: dict) -> dict:
        src = p.get("source") or {}
        kind = src.get("kind")
        origin = dict(kind=kind)
        volume = (p.get("volume") or "").strip()
        if kind == "upload":
            surface = self.upload_folder(src.get("id", ""))
            origin.update(upload=src.get("id"), folder=surface.name)
        elif kind == "path":
            surface = tifxyz.find_tifxyz(Path(str(src.get("path", "")).strip().strip('"')).expanduser())
            origin.update(path=str(surface), sample=SAMPLE in surface.parents)
        elif kind == "volpkg":
            pkg = vc3d.open_volpkg(src.get("volpkg", ""))
            s = vc3d.find_segment(pkg, src.get("segment", ""))
            if not s["loadable"]:
                raise ApiError(f"segment “{s.get('id')}” cannot be loaded: {s['problem']}")
            surface = Path(s["path"])
            if not volume:
                volume = vc3d.find_volume(pkg, src.get("volume"))["location"]
            origin.update(volpkg=pkg["path"], segment=s["id"], segments_dir=str(surface.parent), output_segments=pkg.get("output_segments"))
            self.remember_volpkg(pkg["path"])
        else:
            raise ApiError('source.kind must be "upload", "path" or "volpkg"')
        info = estimate(surface, p.get("densify_to"))
        volume = normalize_location(volume)
        name = tifxyz.check_name((p.get("name") or "").strip() or tifxyz.safe_name(info["id"]))
        existing = self.settings.segments_dir / name / "config.json"
        if existing.exists() and not p.get("resume"):
            old = json.loads(existing.read_text(encoding="utf-8"))
            if Path(old.get("surface", "")).resolve() != Path(info["path"]).resolve():
                raise ApiError(f"a segment named “{name}” already exists (prepared from another surface): choose another name", 409)
        for j in self.jobs():
            if j["state"] == "running" and j.get("name") == name:
                raise ApiError(f"“{name}” is already being prepared", 409)
        job = time.strftime("%Y%m%d_%H%M%S_") + name
        jf = self.settings.jobs_dir / f"{job}.json"
        cmd = [sys.executable, "-X", "utf8", "-u", "-m", "surface_enhancer", "prepare", str(surface), volume, "--name", name,
               "--data-dir", str(self.settings.data_dir), "--cache-dir", str(self.settings.cache_dir), "--threads", str(self.settings.threads),
               "--job-file", str(jf), "--origin-json", json.dumps(origin)]
        if self.settings.config_file:
            cmd += ["--config", self.settings.config_file]
        if p.get("mirror"):
            cmd.append("--mirror")
        if p.get("densify_to"):
            cmd += ["--densify-to", str(float(p["densify_to"]))]
        if p.get("voxel_um"):
            cmd += ["--voxel-um", str(float(p["voxel_um"]))]
        if p.get("offline"):
            cmd.append("--offline")
        if p.get("chunk_cache"):
            cmd += ["--chunk-cache", str(p["chunk_cache"])]
        for layer in p.get("ink_layers") or []:
            cmd += ["--ink-layer", str(layer)]
        if p.get("redo"):
            cmd += ["--redo", str(p["redo"])]
        jf.write_text(json.dumps(dict(state="running", stage="starting", fraction=0.0, message="starting…", name=name, started=time.strftime("%Y-%m-%d %H:%M:%S"), log=[])), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PACKAGE_PARENT) + os.pathsep + env.get("PYTHONPATH", "")
        log = open(self.settings.jobs_dir / f"{job}.log", "ab")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.procs[job] = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(PACKAGE_PARENT), creationflags=flags)
        log.close()
        with self.lock:
            self.open.pop(name, None)
        return dict(job=job, name=name, estimate=info)

    def job(self, job: str) -> dict:
        if not re.fullmatch(r"[0-9A-Za-z_.\-]+", job or ""):
            raise ApiError("unknown job", 404)
        jf = self.settings.jobs_dir / f"{job}.json"
        j = None
        for _ in range(3):                       # the file is replaced atomically, but be patient on Windows
            try:
                j = json.loads(jf.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                time.sleep(0.05)
        if j is None:
            raise ApiError("unknown job", 404)
        j["job"] = job
        j.setdefault("name", job[16:])
        proc = self.procs.get(job)
        if j.get("state") == "running" and (proc is None or proc.poll() is not None):
            tail = ""
            try:
                tail = (self.settings.jobs_dir / f"{job}.log").read_text(encoding="utf-8", errors="replace")[-1500:]
            except OSError:
                pass
            last = [l for l in tail.strip().splitlines() if l.strip()][-1:] or [""]
            j.update(state="failed" if proc is not None else "interrupted",
                     message=(last[0][:400] if proc is not None else "the server was restarted while this preparation was running: start it again, it resumes where it stopped"), log_tail=tail)
            try:
                jf.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return j

    def jobs(self) -> list:
        out = []
        for f in sorted(self.settings.jobs_dir.glob("*.json"), reverse=True)[:12]:
            try:
                out.append(self.job(f.stem))
            except ApiError:
                pass
        return out

    def cancel(self, job: str) -> dict:
        proc = self.procs.get(job)
        j = self.job(job)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            j.update(state="cancelled", message="cancelled — start it again to resume where it stopped")
            (self.settings.jobs_dir / f"{job}.json").write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        return j

    def home(self) -> dict:
        s = self.settings
        free = shutil.disk_usage(s.cache_dir).free if s.cache_dir.exists() else 0
        return dict(version=__version__, settings=dict(data_dir=str(s.data_dir), cache_dir=str(s.cache_dir), host=s.host, port=s.port, cache_free_bytes=int(free),
                                                      max_upload_mb=s.max_upload_mb, config_file=s.config_file),
                    segments=self.library(), jobs=self.jobs(), recent_volpkgs=self._state().get("recent_volpkgs", []),
                    sample_available=(SAMPLE / "segment" / "sample_scroll1" / "x.tif").is_file() and (SAMPLE / "volume" / "sample_scroll1.zarr").is_dir())


def _local_only(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app: App = None

    def log_message(self, *a):                # quiet console
        pass

    # ───────────── plumbing ─────────────
    def _send(self, body: bytes, ctype="application/json; charset=utf-8", code=200, cache="no-store", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"), code=code)

    def _error(self, e):
        if isinstance(e, ApiError):
            return self._json(dict(error=str(e)), e.code)
        if isinstance(e, (tifxyz.TifxyzError, vc3d.VolpkgError, VolumeError)) or isinstance(e, USER_ERRORS):
            return self._json(dict(error=str(e)), 400)
        traceback.print_exc()
        self._json(dict(error=f"internal error: {type(e).__name__}: {e}"), 500)

    def _guard(self) -> bool:
        """Local tool: refuse requests that come through another site or another host name (CSRF, DNS rebinding)."""
        s = self.app.settings
        if not _local_only(s.host):
            return True
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]")
        if host not in ("127.0.0.1", "localhost", "::1"):
            self._json(dict(error="this server only answers on 127.0.0.1 / localhost"), 403)
            return False
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost", "::1"):
            self._json(dict(error="cross-site request refused"), 403)
            return False
        return True

    def _body_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n and not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self.rfile.read(n)
            raise ApiError("send JSON (Content-Type: application/json)", 415)
        if n > 64 << 20:
            raise ApiError("request too large", 413)
        raw = self.rfile.read(n) if n else b""
        try:
            j = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError("the request body is not valid JSON")
        if not isinstance(j, dict):
            raise ApiError("a JSON object is expected")
        return j

    # ───────────── GET ─────────────
    def do_GET(self):
        if not self._guard():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        r = u.path
        try:
            if r == "/api/home":
                return self._json(self.app.home())
            if r == "/api/library":
                return self._json(self.app.library())
            if r == "/api/jobs":
                return self._json(self.app.jobs())
            m = re.fullmatch(r"/api/jobs/([^/]+)", r)
            if m:
                return self._json(self.app.job(unquote(m.group(1))))
            m = re.fullmatch(r"/api/s/([^/]+)/([a-z0-9]+)", r)
            if m:
                return self._segment_get(self.app.segment(unquote(m.group(1))), m.group(2), q)
            if r.startswith("/api/"):
                return self._json(dict(error="unknown route"), 404)
            f = (WEB / (r.lstrip("/") or "tabs.html")).resolve()          # the address of the tool is the window with its tabs
            if WEB.resolve() not in f.parents or not f.is_file():
                return self._send(b"not found", "text/plain; charset=utf-8", 404)
            ctype = (mimetypes.guess_type(f.name)[0] or "application/octet-stream") + ("; charset=utf-8" if f.suffix in (".html", ".js", ".css", ".svg") else "")
            return self._send(f.read_bytes(), ctype)
        except Exception as e:
            self._error(e)

    def _segment_get(self, seg, action, q):
        import numpy as np
        if action == "state":
            return self._json(seg.etat())
        if action == "tile":
            b = seg.tuile(int(q["n"]), int(q["y"]), int(q["x"]), int(q.get("c", 0)))
            return self._send(b, "image/jpeg", cache="max-age=86400") if b else self._send(b"", "text/plain", 404)
        if action == "ink":
            b = seg.tuile_encre(q["nom"], int(q["n"]), int(q["y"]), int(q["x"]))
            return self._send(b, "image/png", cache="max-age=86400") if b else self._send(b"", "text/plain", 404)
        if action == "sections":
            return self._send(seg.coupes(float(q["v"]), float(q["u"]), int(float(q.get("w", 160)))), "application/octet-stream")
        if action == "scores":
            return self._send(seg.scores_binaire(), "application/octet-stream")
        if action == "worst":
            return self._json(seg.pires(int(q.get("n", 60)), q.get("marked") == "1"))
        if action == "marks":
            return self._send(seg.zones.astype(np.uint8).tobytes(), "application/octet-stream")
        if action == "patch3d":
            if q.get("whole") == "1":
                return self._send(seg.segment3d(float(q["v"]), float(q["u"]), int(float(q.get("c", 0))), q.get("e", ""), int(float(q.get("n", 400)))), "application/octet-stream")
            return self._send(seg.patch3d(float(q["v"]), float(q["u"]), int(float(q.get("r", 80))), int(float(q.get("c", 0))), q.get("e", "")), "application/octet-stream")
        if action == "locate":
            return self._json(seg.situer())
        if action == "progress":
            return self._json(seg.avancement or {})
        if action == "fibres":
            return self._send(seg.fibres_binaire(), "application/octet-stream")
        if action == "download":
            from .export import download_bytes
            with seg.verrou:
                name, body, ctype = download_bytes(seg, q.get("what", "bundle"), q.get("grid", "working"))
            return self._send(body, ctype, extra={"Content-Disposition": f'attachment; filename="{name}"'})
        if action == "exports":
            d = seg.d / "exports"
            return self._json(sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.endswith(".retouch")) if d.is_dir() else [])
        raise ApiError("unknown route", 404)

    # ───────────── POST ─────────────
    def do_POST(self):
        if not self._guard():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        r = u.path
        try:
            if r == "/api/upload":
                return self._json(self.app.receive_upload(self.rfile, int(self.headers.get("Content-Length") or 0), q.get("name", "segment.zip")))
            body = self._body_json()
            if r == "/api/inspect":
                return self._json(estimate(Path(str(body.get("path", "")).strip().strip('"')).expanduser(), body.get("densify_to")))
            if r == "/api/volume/check":
                return self._json(describe(body.get("volume", "")))
            if r == "/api/prepare":
                return self._json(self.app.start_prepare(body))
            if r == "/api/sample":
                return self._json(self.app.start_prepare(dict(source=dict(kind="path", path=str(SAMPLE / "segment" / "sample_scroll1")), volume=str(SAMPLE / "volume" / "sample_scroll1.zarr"),
                                                              name=body.get("name") or "sample", densify_to=4, voxel_um=7.91, resume=True)))
            if r == "/api/volpkg/open":
                pkg = vc3d.open_volpkg(body.get("path", ""))
                self.app.remember_volpkg(pkg["path"])
                return self._json(pkg)
            m = re.fullmatch(r"/api/jobs/([^/]+)/cancel", r)
            if m:
                return self._json(self.app.cancel(unquote(m.group(1))))
            m = re.fullmatch(r"/api/s/([^/]+)/([a-z0-9]+)", r)
            if m:
                name, action = unquote(m.group(1)), m.group(2)
                if action == "remove":
                    if body.get("confirm") != name:
                        raise ApiError("type the name of the segment to confirm")
                    return self._json(self.app.remove_segment(name))
                return self._segment_post(self.app.segment(name), action, body)
            self._json(dict(error="unknown route"), 404)
        except Exception as e:
            self._error(e)

    def _segment_post(self, seg, action, body):
        if action == "gesture":
            return self._json(seg.geste(body["outil"], body.get("params", {})))
        if action == "preview":
            if body.get("outil") == "etendre":            # the band is computed, nothing is written; answered as JSON
                return self._json(seg.apercu_extension(body.get("params", {})))
            return self._send(seg.apercu(body["outil"], body.get("params", {})), "application/octet-stream")
        if action == "extend":
            return self._json(seg.etendre(body.get("params", {})))
        if action == "jumps":
            return self._send(seg.sauts(body), "application/octet-stream")
        if action == "undo":
            return self._json(seg.annuler(-1))
        if action == "redo":
            return self._json(seg.annuler(+1))
        if action == "freeze":
            return self._json(seg.figer())
        if action == "export":
            from .export import export_segment, export_to_segments_dir
            target = body.get("target", "local")
            uid = (body.get("id") or "").strip() or None
            with seg.verrou:
                if target == "volpkg":
                    o = seg.cfg.get("origin") or {}
                    dest = (body.get("segments_dir") or "").strip() or o.get("output_segments") or o.get("segments_dir")
                    if not dest:
                        raise ApiError("no VC3D segments folder known for this segment: give the folder (the paths/ folder of your volume package)")
                    return self._json(export_to_segments_dir(seg, dest, uuid=uid, grid=body.get("grid", "original")))
                return self._json(export_segment(seg, uuid=uid, grid=body.get("grid", "working")))
        raise ApiError("unknown route", 404)


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):          # a browser closing a connection is not an error worth a traceback
        import sys as _sys
        if isinstance(_sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def make_server(settings: Settings) -> ThreadingHTTPServer:
    app = App(settings)
    handler = type("BoundHandler", (Handler,), dict(app=app))
    srv = QuietServer((settings.host, settings.port), handler)
    srv.daemon_threads = True
    srv.app = app
    return srv


def port_in_use(port: int) -> list:
    """Processes listening on this port on ANY address (a check on 127.0.0.1 alone is not enough on Windows)."""
    try:
        import psutil
    except ImportError:
        return []
    out = []
    try:
        for c in psutil.net_connections("tcp"):
            if c.laddr and c.laddr.port == port and c.status == "LISTEN":
                out.append(c.pid)
    except (psutil.Error, PermissionError):
        pass
    return out


def serve(settings: Settings, open_browser=False) -> None:
    busy = port_in_use(settings.port)
    if busy:
        raise SystemExit(f"port {settings.port} is already used by another program (process {busy[0]}): choose another one with --port")
    srv = make_server(settings)
    host = "127.0.0.1" if _local_only(settings.host) else settings.host
    url = f"http://{host}:{settings.port}/tabs.html"
    print(f"Surface Enhancer {__version__} — {url}", flush=True)
    print(f"  data  {settings.data_dir}\n  cache {settings.cache_dir}", flush=True)
    if not _local_only(settings.host):
        print("  WARNING: listening on a non-local address. There is no authentication: anyone who can reach this port can read and write local files through it.", flush=True)
    print("  Ctrl+C to stop; every gesture is already saved.", flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
