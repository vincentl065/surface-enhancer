# Where each piece comes from, and how to merge upstream changes

Surface Enhancer started as a private workshop tool (French, single segment, paths of one machine). This repository
is the publishable form. The workshop tool is still being developed; this page says what was taken from it, what was
rewritten, and how to pull its next changes without redoing the work by hand.

`docs/upstream_hashes.txt` holds the SHA-256 of every workshop file at the time it was last taken.

## Taken as they are, then patched by script

| here | workshop file | changes applied |
|---|---|---|
| `surface_enhancer/core/commun.py` | `commun.py` | hard-coded folders removed; tifxyz reading delegated to `tifxyz.py`; the block reader `Scan` replaced by an adapter to `volume.VolumeReader` |
| `surface_enhancer/core/segment.py` | `segment.py` | package imports; data and cache folders passed in; English error messages; export delegated to `export.py`; a few more fields in the state |
| `surface_enhancer/core/auto.py` | `auto.py` | package imports; one comment naming private folders removed |
| `surface_enhancer/core/auto_noyaux.py` | `auto_noyaux.py` | none |
| `surface_enhancer/core/extension.py` | `extension.py` | package imports; scan sampling taken from `prepare.py` |
| `surface_enhancer/web/app.js` | `site/app.js` | routes under `/api/s/<segment>/` with English names; `error` key; hooks for the help and export dialogs |
| `surface_enhancer/web/vue3d.js` | `site/vue3d.js` | none |
| `surface_enhancer/web/panneau.js`, `panneau.css` | `site/panneau.js`, `site/panneau.css` | none: they build the whole left panel (groups, icons, ⓘ cards) inside `<div id="panneauCorps">`, before `app.js` runs |

The changes are **not** made by hand: `tools_dev/patch_core.py` and `tools_dev/patch_web.py` copy the workshop
files and apply a list of exact replacements. Each replacement must match exactly once; when the workshop changed a
line that is patched, the script stops and prints that line.

```
python tools_dev/patch_core.py <workshop folder>
python tools_dev/patch_web.py  <workshop folder>/site
python -m pytest tests
```

This was done twice already: for the automatic tools (Follow the sheet, Magnet everywhere, Remove steps, Best
fibres, fibre score layer, whole-segment 3D view), then for **Extend the surface**, which arrived while this
repository was being built — the second merge needed four anchors updated, two routes, and the export adapted to an
enlarged grid.

## Rewritten here (same method, new code)

| here | replaces | notes |
|---|---|---|
| `prepare.py` | `preparer.py` | same stages and numbers; progress reporting, resume, disk check, parallel download first, optional resample; no machine-specific path |
| `volume.py` | the `Scan` class, `precharger_blocs.py` | local / https / s3 OME-Zarr, block cache per volume, parallel prefetch |
| `server.py` | `serveur.py`, `demarrer.py` | several segments, home page, uploads, background jobs, VC3D packages, downloads, request guard |
| `cli.py` (`replay`) | `rejouer.py` | same checks |
| `cli.py` (`densify`), `prepare.densify` | `densifier_tifxyz.py` | also available at preload time |
| `tools/flatten.py` | `ragdoll_tifxyz.py` + the relaxation script it called | one self-contained module, CPU by default |
| `tools/compare.py` | `ct_avant_apres.py` | uses the fibre-grid measure already in `core/auto.py`; no external script |
| `web/editor.html` | `site/index.html` | the panel itself comes from `panneau.js`; here: header of the panel, help and export dialogs, empty state |
| `web/style.css` | `site/style.css` | workshop stylesheet + additions at the end |
| `web/index.html`, `home.js`, `editor_extra.js`, `tifxyz.py`, `vc3d.py`, `export.py`, `config.py` | — | new |
| `tests/e2e/pilot.py` | `essais/pilote.py` | English, any Chrome path, file inputs, downloads |

## Not taken

- The ink-reading scripts of the workshop: they depend on models and weights that cannot be redistributed. The hook
  is documented instead (`docs/INK.md`: `render`, then `ink-layer`).
- One-off scripts tied to particular segments (figures, review sheets, launchers).
- `auto_champs.py` (offset fields the automatic tools would give, computed outside the server for one segment): its
  generic part is already reachable here — `POST preview` computes without writing, and `replay --out` writes an
  offset field. To take over only if a batch "compute and save the proposals" command is wanted.
- The workshop's own browser tests (`essais/essai_*.py`): they drive the single-segment French server. Their checks
  were re-expressed in `tests/` (the no-step rule, exact undo, replay, preview-then-apply, extend, export).

## State of the merge

Everything the workshop had delivered when this repository was last synchronised is in: automatic tools (phase 1)
and Extend the surface (phase 2). Nothing is waiting. `docs/upstream_hashes.txt` is the reference for the next diff.

## When the workshop changes again

1. Run the two patch scripts on the workshop folder. If one stops, update the anchor it names (and nothing else).
2. New element ids in `site/index.html`: add them to `web/editor.html` (compare the two files; ids are identical).
3. New routes in `serveur.py`: add them to `_segment_get` / `_segment_post` in `server.py` with an English name, and
   the matching replacement in `patch_web.py` (the script refuses to finish while `app.js` still calls an old route).
4. New files read from or written into a segment folder: add them to `docs/DATA_LAYOUT.md`; if they affect the
   surface, to `export.py`.
5. Update `docs/upstream_hashes.txt`, run the tests, add a line to `CHANGELOG.md`.

Once the workshop is retired, drop the patch scripts and translate the core in place (`STATUS.md`).
