# Status — what works, what was not verified, what is missing

Version 1.0.0, the first public version. The core has been used on real pages; several tools are recent. Expect
rough edges, and tell us (issues and pull requests are welcome).

## Works, and how it is tested

| | tested by |
|---|---|
| tifxyz read / write following the VC3D rules; safe zip upload | `tests/test_tifxyz.py` |
| the scan a segment was traced on, guessed only when the folder names it | `tests/test_tifxyz.py` |
| preload from a local OME-Zarr; resample of coarse grids | every test (fixture), `tests/test_core.py` |
| editing core: manual tools, automatic tools, exact undo, journal replay; the magnet and the automatic tools never create a step | `tests/test_core.py` |
| Find sheet jumps: nothing written; a region moved to the next sheet is reported as such | `tests/test_core.py` |
| Extend the surface: band added, undo, export of the enlarged grid, replay | `tests/test_extend.py` |
| export: only moved nodes change; original node layout; zip bundle; layers for an ink model; before / after | `tests/test_core.py` |
| VC3D packages: classic folder, project file, plain folder; round trip into `paths/` as a new segment | `tests/test_vc3d.py` |
| HTTP API: upload → prepare (background job) → edit → download; errors; requests from elsewhere refused | `tests/test_server.py` |
| the command `open` (prepare, start the server, give the address), `list --json`, `stop` | `tests/test_cli.py` |
| the pages in a real browser at 1366 × 768: add a segment (folder or zip), VC3D package, editor, help, 3D, export, download, tabs | `tests/e2e/test_browser.py` |
| exports read by the Python tifxyz reader of `villa` | by hand, `tools_dev/check_with_villa_reader.py` |
| exports loaded by the C++ loader of VC3D (`vc_tifxyz2obj`): same nodes, same positions | by hand, `tools_dev/check_with_vc3d_loader.py` |
| exports opened in the VC3D application: listed with their area, drawn in the surface view and in the XY / YZ slices | by hand, on a package built around the sample (`USING_WITH_VC3D.md`) |
| remote volumes (`https://`, `s3://`): an 18 × 12 mm piece of a public Scroll 1 segment prepared over the network (557 scan blocks, 14 minutes) | by hand |

## Not verified yet

- **An export of a surface enlarged by *Extend the surface*, opened in VC3D.** The other exports were opened in the
  application; this one was not, and was not read by its loader either.
- **Linux and macOS.** Developed and tested on Windows 11 with Python 3.12 only. Nothing is Windows-specific by
  design (pathlib everywhere, no GPU, no compiled extension).
- **A whole page of several centimetres prepared with this code.** The largest so far is 18 × 12 mm.
- **Find sheet jumps on real, known jumps.** It finds a jump made on purpose; on a hard page more than half of the
  surface can come out as "not sure".
- Older versions of the dependencies (`requirements.txt` holds the tested ones).

## Known gaps

- **French inside.** The editing core (`surface_enhancer/core/*.py`), `web/app.js`, `web/vue3d.js` and
  `web/panneau.js` keep French identifiers and comments, and very dense lines; so do the names inside a segment
  folder, the journal vocabulary and the fields of the editing payloads. All of it is documented in English
  (`DATA_LAYOUT.md`, `HTTP_API.md`), and everything a user sees or types is English. Renaming is mechanical but
  must come with a format-version bump and a migration of existing segments (`MERGE.md`).
- A retouch is limited to ± 32 voxels around the original surface; there is no re-reading of the scan around a
  retouched zone yet.
- The preload needs the whole flat page on disk (81 bytes per pixel); there is no partial / windowed preload.
- Only level 0 of the volume; 16-bit volumes are reduced to 8 bits by dropping the low byte.
- *Extend the surface* (marked beta in the interface) reads the scan again and needs the volume to be reachable.
- A line drawn by hand in a section may be steep (up to 12 voxels between two neighbouring nodes): the score counts
  it as a step, and *Remove steps* may flatten it.
- One editor per segment is assumed; two browser windows on the same segment do not see each other's gestures until
  reloaded.
- Up to four segments are kept open in memory by the server (the least recently used is closed).
- Tabs: each tab is one page in its own frame, kept in memory by the browser. The list of open tabs is remembered
  per browser, not on the server.
- The low-resolution overviews of the scans (`web/scrolls/`, 67 public scans, 15 MB) are matched by the folder name
  of the volume: a renamed local copy shows no "Where in the scroll" view. One public scan has none (PHercParis3,
  `20260427095331-2.400um…`: its coarsest level is too large for `tools_dev/make_overviews.py` as written).
- No VC3D plug-in (see `USING_WITH_VC3D.md`).

## Ideas

- Re-reading the scan around a retouched zone, to go beyond ± 32 voxels without preparing the segment again.
- Following a sheet from a line drawn in a section (or from several trusted points) instead of from one point.
- Fibre or surface predictions as an extra signal for the magnet and for the sheet-jump map.
- Ink re-reading on the retouched zone from the editor, through a user-supplied command; a depth sweep judged on ink.
- A `vc_*`-style command or a VC3D panel for the magnet and the automatic tools (a contribution to `villa`).
- True x / y / z planes of the scan next to the sections along the surface.
