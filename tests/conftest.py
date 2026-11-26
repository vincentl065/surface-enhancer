"""Shared fixtures. Everything runs on the tiny bundled sample (sample/), in temporary folders, without network or GPU."""
import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))

SAMPLE_SEGMENT = ROOT / "sample" / "segment" / "sample_scroll1"
SAMPLE_VOLUME = ROOT / "sample" / "volume" / "sample_scroll1.zarr"


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: drives a headless Chrome (skipped when no Chrome is found)")


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    from surface_enhancer.config import load_settings
    base = tmp_path_factory.mktemp("sr")
    return load_settings(base / "data", base / "cache", port=0).ensure()


@pytest.fixture(scope="session")
def prepared(settings):
    """The sample, preloaded once for the whole test session (resampled from 16 to 4 voxels between nodes)."""
    from surface_enhancer.prepare import prepare_segment
    prepare_segment(SAMPLE_SEGMENT, str(SAMPLE_VOLUME), "sample", settings, voxel_um=7.91, densify_to=4)
    return "sample"


@pytest.fixture()
def segment(settings, prepared):
    """A freshly loaded sample segment; whatever the test does is undone afterwards."""
    from surface_enhancer.core.segment import Segment
    seg = Segment(prepared, donnees=settings.segments_dir, cache=settings.segment_cache_dir / prepared)
    start = len(seg.pile)
    yield seg
    while len(seg.pile) > start:
        seg.annuler(-1)


@pytest.fixture(scope="session")
def volpkg(tmp_path_factory):
    """A classic VC3D volume package folder built around the sample: volumes/<id>/ + paths/<segment>/."""
    root = tmp_path_factory.mktemp("pkg") / "sample.volpkg"
    (root / "paths").mkdir(parents=True)
    (root / "config.json").write_text(json.dumps(dict(name="Sample package", version=6)), encoding="utf-8")
    vol = root / "volumes" / "20230205180739"
    shutil.copytree(SAMPLE_VOLUME, vol)
    (vol / "meta.json").write_text(json.dumps(dict(type="vol", uuid="20230205180739", name="sample-7.91um", format="zarr", width=8096, height=7888, slices=14376, voxelsize=7.91)), encoding="utf-8")
    shutil.copytree(SAMPLE_SEGMENT, root / "paths" / "sample_scroll1")
    return root


@pytest.fixture(scope="session")
def server(settings, prepared):
    """The real HTTP server on a port that is free on every address."""
    from pilot import free_port
    from surface_enhancer.server import make_server
    settings.port = free_port(8812, 8839)
    srv = make_server(settings)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{settings.port}"
    for p in srv.app.procs.values():           # only the preparation jobs this server started itself
        if p.poll() is None:
            p.terminate()
    srv.shutdown()
    srv.server_close()
