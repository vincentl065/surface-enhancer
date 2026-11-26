# Changelog

## 1.0.0 — first public version

First publishable form of the tool.

- One command to start (`python -m surface_enhancer serve`), one to try the bundled sample (`sample`).
- Home page: prepared segments, upload of a zipped tifxyz folder or a folder on the computer, any OME-Zarr volume
  (local, `https://`, `s3://`), background preload with a progress bar, cancel and resume.
- VC3D volume packages: open a `.volpkg` folder, a project file or a folder of segments; prepare a segment from it;
  write the retouch back as a new segment.
- Editor: flat page, two sections, 3D view, scores; manual tools (line in the section, magnet, edge magnets, brush,
  shift one sheet, problem areas); automatic tools with preview (Follow the sheet, Magnet everywhere, Remove steps,
  Best fibres, Extend the surface); unlimited undo; built-in help; export dialog; empty and error states; layout for
  laptop screens; nothing shown by colour alone.
- Export: new tifxyz segment (working grid or the node layout of the source), zip bundle with the offset field and
  the journal of gestures, provenance in `meta.json`.
- Tools: `replay`, `compare`, `render`, `ink-layer`, `densify`, `flatten`.
- No hard-coded path: data folder, cache folder, host and port by flag, environment variable or config file.
- Tests: 27, on a 2.7 MB sample of Scroll 1, including one end-to-end journey in a headless Chrome.
- Editor: a right-click on the page pins the sections, a second right-click releases them (a left click no longer
  pins). Each section has its own view: wheel to zoom around the mouse, right-click + drag to move, a Recenter button.
- Home page: a segment is given as a zip, a folder or a VC3D package. The list of published segments was removed.
- Editor: "Where in the scroll", under the two sections: one low-resolution slice across the scroll and one along
  it, with the segment in orange and the point as a yellow dot. The overviews of the public scans ship with the tool
  (`web/scrolls/`, built by `tools_dev/make_overviews.py`), so nothing is downloaded; a scan without overview shows
  nothing.
- Editor, left panel redesigned (`web/panneau.js`, `web/panneau.css`): five foldable groups with icons (by hand,
  automatic, display, quality, history), tools as tiles, the options of each tool shown with it, undo / redo always
  in sight, and an ⓘ on every control: a card with what it does, how to use it and a small animation.
- Section: hovering shows the exact point of the surface a click will grab. A line drawn through several points now
  goes through them (slope up to 3 voxels per node for this gesture; it was capped at 1).
- Editor: a **Segment** menu next to the name of the segment: import, open another segment, save as a version, export, close.
- Tabs (`tabs.html`): several segments open at once, each in its own tab that keeps its view; `+` opens another prepared segment, the Segment menu closes the tab. The home page and the command line now open segments there.
- Finish pass on every page (`web/fini.css`): one radius and one control height, hairlines instead of boxes, drawn sliders, check boxes and selects, quieter chrome.
- Command line: `open` (one command: prepare if needed, start the server if needed, open the editor; `--json` for scripts and AI assistants), `stop`, `list --json`. See `docs/FOR_AI_ASSISTANTS.md`.
- Home page: the scan is chosen for you when the segment folder names it (scan id in `meta.json`, as VC3D writes it, or in the folder name; `surface_enhancer/detect.py`). The geometry alone is not used: it does not decide.
- No separate home page any more: "New tab" (the + of the tab strip, and what the window shows when no segment is open) holds your segments and Add a segment. The server address is now `/tabs.html`.
- **Find sheet jumps** (Quality group, key J): the sheet under the pinned point is followed without jumping and the surface is compared with it — on the reference sheet, N sheets above or below, or not sure. Nothing is written. Route `jumps`.
