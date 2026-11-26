"""Cross-check an exported segment with the tifxyz reader of the ScrollPrize ``villa`` repository (developer tool).

    python tools_dev/check_with_villa_reader.py <villa clone> <tifxyz folder> [<tifxyz folder> ...]

The reader (``vesuvius/src/vesuvius/tifxyz``) is loaded straight from the clone, without installing anything.
It prints what that reader sees: grid shape, scale, uuid, bounding box, number of valid nodes.
"""
import importlib.util
import sys
from pathlib import Path

villa, folders = Path(sys.argv[1]), sys.argv[2:]
pkg_dir = villa / "vesuvius" / "src" / "vesuvius" / "tifxyz"
spec = importlib.util.spec_from_file_location("villa_tifxyz", pkg_dir / "__init__.py", submodule_search_locations=[str(pkg_dir)])
mod = importlib.util.module_from_spec(spec)
sys.modules["villa_tifxyz"] = mod
spec.loader.exec_module(mod)
for f in folders:
    s = mod.read_tifxyz(f)
    valid = getattr(s, "_valid_mask", None)
    print(Path(f).name, "| shape", s._x.shape, "| scale", s._scale, "| uuid", s.uuid, "| bbox", [round(float(v), 1) for v in s.bbox] if s.bbox is not None else None,
          "| valid nodes", int(valid.sum()) if valid is not None else "?")
print("read by the villa reader: OK")
