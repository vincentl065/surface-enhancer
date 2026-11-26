# Using it with VC3D

VC3D (Volume Cartographer 3D, in the [`villa`](https://github.com/ScrollPrize/villa) repository) traces and grows
segments. Surface Enhancer takes one of those segments, lets you put it back on its sheet, and hands it back as a
**new** segment in the same volume package.

The integration is at the level of the **data**: both programs read and write the same folders.
There is **no plug-in inside the VC3D application** (see “What is not done” below).

## Round trip, step by step

1. **In VC3D**, trace or grow your segment as usual and save. Note the path of the volume package: the `.volpkg`
   folder (with `volumes/` and `paths/`), or the VC3D project file (`.json`).
2. **Start Surface Enhancer** (`surface-enhancer serve`) and open `http://127.0.0.1:8800/`.
3. In a *New tab*, under **I use VC3D: open a volume package instead**, paste the path and press **Open**. The volumes and the segments of the package
   are listed (most recent first; segments VC3D could not load are shown with the reason).
4. Choose the **volume** the segment was traced on, then **Prepare** on the segment. Grids coarser than 8 voxels
   between nodes are resampled to 4 voxels for the retouch. A progress bar follows the preload.
5. **Open** the segment, retouch it.
6. **Export / download… → Write into a VC3D volume package**. The segments folder of the package is already filled
   in. Keep “same node layout as your segment” to get back the grid VC3D had (same number of nodes, same step), or
   choose the working grid to keep every detail of the retouch. Optionally give the new segment an id.
7. **In VC3D**, reload the segments (**Reload Surfaces**). The new segment is listed under its id (by default
   `<original id>_rt<date>`), with its area. The original is still there, untouched. If the package is not open yet:
   VC3D attaches the **volume** and the **segments folder** separately — give it `…/volumes/<volume id>` (not the
   `.volpkg` folder itself, which it refuses as "not a valid volume location") and the `paths` folder.

Command-line equivalent:

```
python -m surface_enhancer volpkg /data/Scroll1.volpkg                       # what is inside
python -m surface_enhancer prepare 20230702185753 --volpkg /data/Scroll1.volpkg --name my_fix --densify-to 4
python -m surface_enhancer serve                                             # retouch in the browser
python -m surface_enhancer export my_fix --to-volpkg                         # new segment, back in the package
```

A segment that did not come from a package can be written into one too: give the folder in the export dialog, or
`export NAME --to-volpkg /data/Scroll1.volpkg`.

## What is written

`<segments folder>/<new id>/` with exactly:

| file | content |
|---|---|
| `x.tif`, `y.tif`, `z.tif` | 32-bit float, one sample per pixel, uncompressed, not tiled (what VC3D itself writes); invalid nodes are `-1` |
| `meta.json` | every field of the original `meta.json`, with `type: "seg"`, `uuid` (= folder name), `format: "tifxyz"`, `scale`, `bbox` recomputed, `area_vx2` / `area_cm2` recomputed, `name`, `date_last_modified`, and a `surface_enhancer` object (provenance: source id, version, number of gestures, nodes moved, largest offset) |
| `mask.tif` | only if the original had one (255 = valid) |
| small `*.json` / `*.txt` / `*.npy` companions of the original | copied as they are (for example `overlapping.json`) |

Only the nodes you moved differ from the original; all others keep the exact original value. No other TIFF is put
in the folder (VC3D registers every extra `*.tif` as a channel). The record of the retouch (offset field, journal of
gestures) stays in the Surface Enhancer data folder, under `exports/<new id>.retouch/`.

Safety: the folder is written under a temporary name next to its destination and renamed at the end; an existing
folder is never replaced; the original segment folder is never opened for writing.

## What was checked against the VC3D source, and how

Read in a local clone of `villa` (commit `a329895ea`, 8 October 2026), under `volume-cartographer/`:

| Rule followed here | Where it was read |
|---|---|
| `meta.json` must have `"type": "seg"` and a `"uuid"`; a segment is loadable when `"format"` is `"tifxyz"` and `x.tif`, `y.tif`, `z.tif` exist | `core/src/Segmentation.cpp` (`loadMetadata`, `canLoadSurface`) |
| `"scale": [sx, sy]` positive numbers; optional `"bbox": [[x0,y0,z0],[x1,y1,z1]]`; the surface id is the folder name (lazy load) or `uuid` (full load), hence folder name = `uuid` | `core/src/QuadSurface.cpp` (constructors, `load_quad_from_tifxyz_impl`) |
| a node is invalid when `z <= 0`; `mask.tif` (first channel < 255) invalidates more nodes and may be an integer multiple of the grid size | `core/src/QuadSurface.cpp` (`load_quad_from_tifxyz_impl`) |
| TIFFs: one sample per pixel, 8/16/32/64 bits; VC3D writes untiled, uncompressed floats, and sets `type`, `uuid`, `format`, `scale`, `bbox` on save | `core/src/QuadSurface.cpp` (`writeDataToDirectory`, `save`) |
| every other `*.tif` of the folder becomes an extra channel; an `overlapping/` sub-folder is refused | `core/src/QuadSurface.cpp` |
| classic package folder: `config.json` (name), `volumes/`, segments in `paths/`, `traces/`, `export/` | `core/src/VolpkgConvert.cpp` (`convertLocal`) |
| project file: `name`, `version`, `volumes`, `segments` (strings or `{location, tags}`), `output_segments`; relative paths from the folder of the file; remote volumes must be direct `.zarr` URLs | `core/src/VolumePkg.cpp` (`fromJson`, `resolveVolumeEntry`, `resolveSegmentsEntry`) |
| what counts as a volume folder; `meta.json` of a volume (`uuid`, `name`, `voxelsize`, `width`, `height`, `slices`) | `core/src/VolumePkg.cpp` (`isSingleZarrVolumeDir`), `core/src/Volume.cpp` |

Tested here:

- the automatic tests build a classic package around the sample, prepare its segment, write the retouch back and
  check every rule above on the result (`tests/test_vc3d.py`, `tests/test_tifxyz.py`);
- exported segments (working grid and original layout) were read back with the **Python tifxyz reader of the
  `villa` repository** (`vesuvius/src/vesuvius/tifxyz`), loaded from the clone: shape, scale, uuid, bounding box and
  valid nodes as expected (`tools_dev/check_with_villa_reader.py`);
- exported segments (working grid and original layout, after a magnet gesture and a line drawn in a section) were
  loaded by the **C++ loader of VC3D**: `vc_tifxyz2obj`, built from the `villa` source in its Linux build image, ends
  without error and writes exactly the valid nodes of the export, at the same positions (289 and 4 225 vertices,
  largest difference 0.0000 voxel) — `tools_dev/check_with_vc3d_loader.py`, 26 November 2026.

- **in the VC3D application itself** (26 November 2026): a small package built around the sample was attached
  (volume, then the `paths` folder); the original and the two exports (original node layout, and working grid one
  node every 4 voxels) are listed, the exports with their area (0.041 cm², the 2 × 2 mm of the sample), and the
  retouched segment is drawn in the surface view and in the XY and YZ slices, at the place of the original.

## What was NOT verified

- An export of a surface enlarged by `Extend the surface` has not been opened in VC3D, nor read by its loader.
- The clone that was read dates from 8 October 2026. VC3D moves fast; later versions may check more fields.
- Project files (`.json`) were tested with hand-made examples following `VolumePkg::fromJson`, not with a project
  saved by VC3D. Tags of entries are read but not interpreted (Open Data catalog entries, Lasagna datasets and
  normal grids are ignored).
- `area_cm2` is computed from the voxel size known to Surface Enhancer; whether VC3D recomputes or trusts it was
  not checked.
- Segments in the older `.obj` / `.ppm` layouts are listed as “not a tifxyz segment”; convert them with the VC3D
  tools first (`vc_obj2tifxyz`).

## What is not done

- No plug-in, panel or menu inside the Qt application of VC3D. Putting the magnet or the automatic tools inside VC3D
  would be a separate contribution to `villa`.
- Surface Enhancer does not drive VC3D (no use of its agent bridge), and VC3D does not start Surface Enhancer.
- Nothing is written to a remote package (S3); only local folders.
