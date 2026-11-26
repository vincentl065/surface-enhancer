# For AI assistants (and scripts)

This page is written for an assistant that has a terminal on the user's computer and is asked something like
"open this segment in Surface Enhancer". Everything is local: no account, no key, nothing is uploaded.

## Install

From a clone of the repository (the tool is not on PyPI):

```
pip install .
```

This gives the command `surface-enhancer` (the same as `python -m surface_enhancer`). Python 3.10 or later.

## Open a segment: one command

```
surface-enhancer open <SEGMENT> [<VOLUME>] --json
```

- `<SEGMENT>` is a **tifxyz folder** (it holds `x.tif`, `y.tif`, `z.tif`, `meta.json`), a `.zip` of that folder, or the
  **name** of a segment that was prepared before.
- `<VOLUME>` is the scan the segment was traced on: a local OME-Zarr folder, an `https://` URL or an `s3://` URL.
  It is only needed the first time a segment is opened. The tool cannot guess it: ask the user if you do not know it.
- The command prepares the segment if it is not prepared yet (the scan is read once along the surface: seconds for a
  few millimetres, minutes to an hour for a page of several centimetres read over the network), starts the local
  server if it is not running, opens the editor in the user's browser, and prints **one JSON object**:

```json
{"name": "my_segment", "prepared_now": true, "server": "started", "url": "http://127.0.0.1:8800/tabs.html?s=my_segment", "pid": 1234}
```

On failure it prints `{"error": "a sentence for a human"}` and exits with status 1. Give that sentence to the user.

Useful options: `--name <name>` (letters, digits, `_ - .`), `--no-browser` (only print the address), `--port <n>`,
`--volpkg <VC3D package>` (then `<SEGMENT>` is a segment id of that package and the volume comes from the package),
`--voxel-um <µm>` when the voxel size is not written in the volume name.

Several segments can be open at once: call `open` again; each one gets its own tab in the same page.

## Other commands

| | |
|---|---|
| `surface-enhancer list --json` | the prepared segments: `[{name, ready, scroll, size_mm, gestures, source, volume}]` |
| `surface-enhancer open <name> --json` | open a prepared segment again (nothing to prepare) |
| `surface-enhancer sample` then `open sample` | the bundled 2 mm sample, to try without any data |
| `surface-enhancer export <name>` | write the retouched surface as a NEW tifxyz segment (prints JSON); `--to-volpkg` writes it into a VC3D package |
| `surface-enhancer compare <name>` | scan before / after and the fibre-grid score (prints JSON, writes images) |
| `surface-enhancer stop` | stop the server that `open` started |

`--data-dir` and `--cache-dir` (on every command) choose where prepared segments and the big cache live; by default
`~/.surface-enhancer/`. Preparing needs about 81 bytes of cache per pixel of the flat page.

## What you should not do

- Do not write into the original segment folder: the tool never does, and exports are always new folders.
- Do not start two servers on the same data folder. `open` reuses the one that is running.
- The retouch itself is done by the user in the browser. There is no command that retouches a surface for them;
  what you can do afterwards is `export` and `compare`.
