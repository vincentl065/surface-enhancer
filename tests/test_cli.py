"""The one-line command: prepare, start the server, give the address — as a person or an AI assistant would call it."""
import json
import subprocess
import sys
import urllib.request

from conftest import ROOT, SAMPLE_SEGMENT, SAMPLE_VOLUME


def run(*args, timeout=240):
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "surface_enhancer", *map(str, args)], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def test_open_prepares_starts_the_server_and_gives_the_address(tmp_path):
    from pilot import free_port
    where = ["--data-dir", tmp_path / "data", "--cache-dir", tmp_path / "cache"]
    port = free_port(8860, 8879)
    try:
        code, out, err = run("open", SAMPLE_SEGMENT, SAMPLE_VOLUME, "--name", "cli_sample", "--voxel-um", "7.91", "--port", port, "--no-browser", "--json", *where)
        assert code == 0, err
        j = json.loads(out.splitlines()[-1])
        assert j["name"] == "cli_sample" and j["prepared_now"] and j["server"] == "started" and j["url"].endswith("/tabs.html?s=cli_sample")
        with urllib.request.urlopen(j["url"], timeout=10) as r:
            assert r.status == 200
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/s/cli_sample/state", timeout=30) as r:
            assert json.loads(r.read())["nom"] == "cli_sample"
        code, out, _ = run("open", "cli_sample", "--port", port, "--no-browser", "--json", *where)          # second time: by its name, nothing to prepare
        j = json.loads(out.splitlines()[-1])
        assert code == 0 and not j["prepared_now"] and j["server"] == "already running"
        (ROOT / "cli_sample").mkdir(exist_ok=True)                    # a folder of the same name in the current folder must not hide the prepared segment
        try:
            code, out, _ = run("open", "cli_sample", "--port", port, "--no-browser", "--json", *where)
        finally:
            (ROOT / "cli_sample").rmdir()
        assert code == 0 and json.loads(out.splitlines()[-1])["name"] == "cli_sample"
        code, out, _ = run("list", "--json", *where)
        assert code == 0 and [s["name"] for s in json.loads(out)] == ["cli_sample"]
        code, out, _ = run("open", "no_such_segment", "--port", port, "--no-browser", "--json", *where)
        assert code == 1 and "neither a prepared segment" in json.loads(out.splitlines()[-1])["error"]
    finally:
        code, out, _ = run("stop", "--port", port, *where)
    assert "stopped" in out
