# Sample data

A tiny piece of **Scroll 1 (PHerc. Paris 4)** — the scroll read by the 2023 Vesuvius Challenge Grand Prize — so that
the tool and its tests run without downloading a scan. About 2.7 MB.

| | |
|---|---|
| `segment/sample_scroll1/` | a tifxyz surface of 17 × 17 nodes, one node every 16 voxels (about 2 × 2 mm) |
| `volume/sample_scroll1.zarr/` | an OME-Zarr (zarr v2) with the shape of the real volume, holding **only** the voxels within ± 48 voxels of that surface; everything else reads as 0 |
| `sample.json` | where it comes from |

Coordinates are those of the real scan (7.91 µm per voxel), so the same surface also works against the full public
volume.

## Where it comes from

- Surface: a window of the public segment `20230702185753` of Scroll 1, read from its `.ppm` (one pixel out of 16):
  `https://dl.ash2txt.org/full-scrolls/Scroll1/PHercParis4.volpkg/paths/20230702185753/`
- Scan: `https://dl.ash2txt.org/full-scrolls/Scroll1/PHercParis4.volpkg/volumes_zarr_standardized/54keV_7.91um_Scroll1A.zarr`

It was made with `tools_dev/make_sample.py` (the exact window is in `sample.json`).

## Terms

This is data from the Vesuvius Challenge (EduceLab-Scrolls), **not** covered by the MIT licence of the code. It is
redistributed here as a small excerpt for testing, under the terms of the Vesuvius Challenge data
(<https://scrollprize.org/data>). If you use the scans, cite the Vesuvius Challenge and EduceLab as they ask.
