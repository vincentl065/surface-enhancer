# HTTP API

The web pages talk to the local server through this API; you can script it too. JSON in, JSON out, unless noted.
Errors come back as `{"error": "message for a human"}` with status 400 (your input), 403 (request not local),
404 (unknown thing), 409 (name conflict, segment not ready), 413 / 415 (upload too large / body not sent as
`application/json`), 500 (bug).

Requests are only accepted when the `Host` header is `127.0.0.1` / `localhost` and the `Origin`, if any, is local.

> Route names and everything outside a segment are in English. The payloads of the editing routes still use the
> French field names of the editing core (`outil`, `params`, `pile`, `bilan`…): they are listed below and in
> [DATA_LAYOUT.md](DATA_LAYOUT.md), and will be renamed in a later version ([STATUS.md](STATUS.md)).

## Library, upload, preparation

| | |
|---|---|
| `GET /api/home` | version, settings, prepared segments, recent jobs, recent VC3D packages, `sample_available` |
| `POST /api/upload?name=<file.zip>` | body = the zip (`Content-Type: application/zip`). → `{upload, folder, summary, suggested_name}`; `summary` has `grid`, `step`, `page`, `cache_bytes` (cost of the preload), `warnings` |
| `POST /api/inspect` `{path, densify_to?}` | the same summary for a folder on the computer |
| `POST /api/volume/check` `{volume}` | → `{location, shape, dtype, voxel_um, remote}` |
| `POST /api/prepare` | `{source, volume, name, densify_to?, mirror?, voxel_um?, ink_layers?, offline?, chunk_cache?, redo?, resume?}` with `source` = `{kind:"upload", id}` or `{kind:"path", path}` or `{kind:"volpkg", volpkg, segment, volume?}` → `{job, name, estimate}` |
| `POST /api/sample` | prepares the bundled sample |
| `GET /api/jobs`, `GET /api/jobs/<job>` | `{state: running / done / failed / cancelled / interrupted, stage, fraction, message, log}` |
| `POST /api/jobs/<job>/cancel` | stops a preparation this server started (it can be resumed) |
| `POST /api/volpkg/open` `{path}` | → `{kind, name, volumes[], segments[], segment_dirs[], output_segments, warnings[]}` |
| `POST /api/s/<name>/remove` `{confirm: "<name>"}` | moves the segment data to `trash/`, deletes its cache |

## One segment: `/api/s/<name>/…`

Read:

| | |
|---|---|
| `GET state` | sizes, versions, score summary (`bilan`), ink layers (`encre`), origin (`origine`), available automatic tools (`auto`) |
| `GET tile?n=<level>&y=&x=&c=<depth>` | JPEG tile (256 px) of the flat page of the retouched surface |
| `GET ink?nom=<key>&n=&y=&x=` | PNG tile of an ink layer |
| `GET sections?v=&u=&w=` | binary: the two sections through page pixel (v, u), the surface line, the detected sheets |
| `GET scores`, `GET fibres` | binary: score per tile; fibre-grid score per window |
| `GET worst?n=&marked=0/1` | lowest-scored tiles |
| `POST jumps` `{ancre: [row, col], saut?, pont?}` | binary: the sheet-jump map seen from that node (1 same sheet, 2–4 one / two / three sheets or more above, 5–7 below, 8 between two sheets, 9 not sure), with the share of each class and the list of zones; nothing is written |
| `GET locate` | `{volume, pas, n: [rows, cols], xyz: [...]}`: a light grid of the real positions (x, y, z) of the retouched surface, one node every `pas` page pixels, `null` where there is no surface; used to show the segment in the low-resolution overview of the scroll (`web/scrolls/`) |
| `GET marks` | marked areas, one byte per node |
| `GET patch3d?v=&u=&r=&c=&e=` (+ `whole=1&n=`) | binary: mesh, texture and sections for the 3D view |
| `GET progress` | what a long computation is doing |
| `GET download?what=bundle / segment / offset / journal&grid=working / original` | a file (zip, `.npy`, `.jsonl`) |
| `GET exports` | ids already exported |

Write (each one is saved at once):

| | |
|---|---|
| `POST gesture` `{outil, params}` | applies one gesture → what to refresh, new scores, `pile` (gestures applied) |
| `POST preview` `{outil, params}` | automatic tools: computes without writing (binary map; JSON for `etendre`) |
| `POST extend` `{params}` | applies an “Extend the surface” band |
| `POST undo`, `POST redo` | |
| `POST freeze` | freezes the working version, opens the next one |
| `POST export` `{target: "local" / "volpkg", segments_dir?, id?, grid?}` | writes a NEW tifxyz segment → `{folder, id, shape, nodes_moved, nodes_added, offset_max_vx, vc3d_problems[], retouch_folder}` |

Binary answers are: 4 bytes (little-endian length of the header), a JSON header, then the arrays named in
`header.tableaux` (`type`, `forme` = shape, `debut` = offset, `octets` = bytes).

Field names of the editing payloads: `outil` tool · `params` parameters · `pile` / `refaire` gestures applied / that
can be redone · `bilan` score summary (`page`, `marquees` marked areas, `reste` rest; `note` now, `note0` original,
`mauvais` tiles under 40) · `enregistre` time of the last save · `rien` nothing changed · `carreaux` tiles ·
`deplacement_max` largest move · `note_zone` score of the touched area [before, after]. Tool names and their
parameters: [DATA_LAYOUT.md](DATA_LAYOUT.md#journaljsonl).

## Example

```
curl -s -X POST -H "Content-Type: application/zip" --data-binary @segment.zip "http://127.0.0.1:8800/api/upload?name=segment.zip"
curl -s -X POST -H "Content-Type: application/json" http://127.0.0.1:8800/api/prepare \
     -d '{"source": {"kind": "upload", "id": "<upload>"}, "volume": "<volume address>", "name": "my_segment", "densify_to": 4}'
curl -s http://127.0.0.1:8800/api/jobs/<job>
curl -s -X POST -H "Content-Type: application/json" http://127.0.0.1:8800/api/s/my_segment/gesture \
     -d '{"outil": "aimant_partout", "params": {"borne": 6, "bord": 0, "zones": false, "greffe": true}}'
curl -s -OJ "http://127.0.0.1:8800/api/s/my_segment/download?what=bundle&grid=original"
```
