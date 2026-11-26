# What is written on disk

Two roots (see [CONFIGURATION.md](CONFIGURATION.md)): the **data** folder (small, precious: your work) and the
**cache** folder (big, disposable: rebuilt by preparing again).

> The names inside a segment folder, and the vocabulary of the journal, are still in French (format version 1). They
> are listed here with their meaning; a later version will rename them with a migration. See [STATUS.md](STATUS.md).

## Data folder

```
<data>/
  state.json                     recently opened VC3D packages
  uploads/<token>/<folder>/      unzipped uploads (x.tif, y.tif, z.tif, meta.json, mask.tif only)
  jobs/<job>.json, <job>.log     state and log of each preparation
  trash/<name>_<date>/           segments removed from the home page (moved here, not deleted)
  segments/<name>/
    config.json                  how the segment was prepared (see below)
    base/P0.npy, N.npy, valide.npy     hole-filled node positions (z, y, x), smoothed normals, validity — of the ORIGINAL surface
    base/zones_depart.png        problem areas imported at preparation, if any
    base/fibres_origine.npz      fibre-grid measure of the original surface (computed on first use)
    versions/v000/tifxyz/        copy of the original surface on the working grid: the frozen reference
    versions/v000/source/        untouched copy of what you gave, when the grid was resampled
    versions/vNNN/decalage.npy   OFFSET FIELD of that version: float32 per node, voxels along the original normal
    versions/vNNN/zones.png      marked problem areas (255 = marked), one pixel per node
    versions/vNNN/meta.json      figee (frozen), parent, evenements (journal lines applied), modifiee (last change)
    versions/vNNN/decalage_etendu.npy, zones_etendu.png     the same on the enlarged grid, once the surface was extended
    journal.jsonl                every gesture, undo and redo, in order (see below)
    gestes/gNNNNNN.npz           before / after of the rectangle touched by gesture N (what undo restores)
    extensions/eNNNNNN.npz       the band added by an “Extend the surface” gesture
    historique/                  safety copies of the offset field every 25 gestures
    exports/<id>/                exported tifxyz segments
    exports/<id>.retouch/        record of that export: offset_along_normal.npy, journal.jsonl, marked_areas.png, provenance.json
    compare/, layers/            outputs of the `compare` and `render` commands
```

The highest `vNNN` is the working version. “Freeze this version” makes it read-only and opens the next one.
The retouched surface is always `P0 + offset × N` (node by node); the original files are never rewritten.

### config.json

| key | meaning |
|---|---|
| `format_version` | 1 |
| `nom` | name of the segment |
| `surface` | folder of the original tifxyz |
| `volume` | address of the scan volume |
| `cache` | cache folder at preparation time (the configured cache folder is tried first) |
| `cache_scan`, `chunk_cache` | folder of the downloaded 128³ scan blocks |
| `um`, `um_known` | voxel size in µm, and whether it was really known |
| `pas` | voxels between two nodes of the working grid |
| `grille`, `page` | working grid (rows, columns) in nodes; flat page (rows, columns) in pixels (1 pixel = 1 voxel) |
| `source_step`, `densified_factor` | step of the grid you gave; how many times finer the working grid is |
| `demi`, `couches` | half-depth of the straightened block (40); half-range of the page depth slider (8) |
| `miroir` | show the page flipped left-right by default |
| `encre` | ink layers: `cle` (key), `nom` (label), `source`, `seuils` (display ramp) |
| `lut`, `pics` | display contrast; statistics of the sheet detection |
| `meta_origine` | the `meta.json` of the original segment, kept for the export |
| `blocs_absents` | scan blocks that were missing during the preload |
| `origin` | where it came from: `kind` = `upload` / `path` / `volpkg`, and for a package `volpkg`, `segment`, `segments_dir`, `output_segments` |

### journal.jsonl

One JSON object per line. `type` is `geste` (gesture), `annuler` (undo), `retablir` (redo) or `version` (freeze).
A gesture has `id`, `t` (time), `outil` (tool), `params`, `champ` (`h` = offset field, `zones` = marked areas,
`grille` = grid enlarged), `bbox` (node rectangle v0, v1, u0, u1), `note_zone` (score of the touched area before,
after), `deplacement_max` (largest move, voxels), and `auto` (summary) for automatic tools.

| `outil` | tool | main `params` |
|---|---|---|
| `ligne` | line dragged in a section | `axe` (`u` across the width / `v` along the height), `fixe` (row or column of the section, in nodes), `points` [[position, depth]], `rayon` (reach, nodes) |
| `aimant` | magnet | `points` [[v, u]] (nodes), `rayon`, `borne` (largest move, voxels) |
| `bord` | edge magnet | same + `bord` (signed distance from the core of the sheet, voxels) |
| `pousser` | brush ± 1 voxel | `points`, `rayon`, `signe`, `pas` |
| `feuille` | shift one sheet | `traits` (painted strokes), `sens` (−1 above, +1 below), `recoller` |
| `marquer` | mark / erase a problem area | `points`, `rayon`, `valeur` |
| `suivre` | Follow the sheet from here | `ancre` [v, u], `saut`, `pont`, `seuil`, `taux`, `bord`, `greffe` |
| `aimant_partout` | Magnet everywhere | `borne`, `bord`, `zones` (marked areas only), `greffe` (keep only the winning parts) |
| `marches` | Remove steps | `seuil`, `ancre` |
| `fibres` | Best fibres | `portee`, `zones`, `greffe` |
| `etendre` | Extend the surface | `cote` (side), `largeur` (mm), `saut`, `pont`, `taux` |

`python -m surface_enhancer replay NAME` recomputes every gesture from its parameters, in order, and compares with
what was recorded: the journal alone is enough to redo a retouch.

## Cache folder

```
<cache>/
  volumes/<volume name>-<hash>/<kz>_<ky>_<kx>.npy     downloaded scan blocks (128³, 8-bit), shared by all segments of that volume
  segments/<name>/
    bloc.npy                 the straightened block: page rows × page columns × 81 depths (−40 … +40 voxels along the normal)
    bloc_fait.npy            which tiles of the block are done (lets the preload resume)
    profils.npy              mean profile along the normal around each node
    pics_pos.npy, pics_force.npy    detected sheets per node: depth and strength (up to 10)
    page_L1 … page_L4.npy    reduced levels of the flat page, 17 depths
    encre/<key>_L0 … L4.npy  ink layers and their reduced levels
    ext_<name>_NNNNNN_bloc.npy      scan of a band added by “Extend the surface”
    preparation.json         which stages are done
```
