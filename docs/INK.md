# Re-read the ink with your own model

Surface Enhancer does not include an ink-detection model or weights. It gives you the two ends of the pipe:

```
retouched surface ──render──▶ flat layers ──your model──▶ prediction image ──ink-layer──▶ shown in the editor
```

## 1. Layers of the retouched surface

```
python -m surface_enhancer render NAME --first -8 --last 8 --out layers/
```

writes one 8-bit TIFF per depth (`00.tif` is the first depth), of the size of the flat page, read from the
straightened block along the normal of the surface — no access to the scan, a few seconds. `layers.json` lists the
depths (0 = the retouched surface; negative = towards the top of the sections). `--stack` writes one multi-page
`layers.tif` instead. Depths can go from −40 to +40; where the surface was moved far, the deepest layers reach the
end of the block and are clamped (`"clamped": true`).

To render with another tool instead (for example `vc_render_tifxyz` of VC3D, at any depth), export the segment
(`export NAME`, or the zip from the page) and render the exported tifxyz.

## 2. Your model

Run any model that takes a stack of layers and returns one image of the same height and width (probability of ink).
Which side of the sheet carries the ink is not known to this tool: try both ranges of depths (for example −8 … 0
and 0 … +8), and use the edge magnets to sit on the right face.

## 3. Show the prediction in the editor

```
python -m surface_enhancer ink-layer NAME "My model, after retouch=prediction.tif"
```

The image must have exactly the size of the flat page (TIFF or PNG; it is scaled to 8 bits). Reload the editor: the
layer is in the **Ink** list (key **E**), drawn in yellow on the darkened scan, in 2D and in 3D. Several layers can
be added (before / after, two models). The same option exists at preload time: `prepare … --ink-layer "Label=file"`.

A layer is tied to the surface it was predicted on. Layers predicted on the original surface are still shown after
you retouch — in the right place on the page, but not re-read.

## Judging a retouch without a model

`python -m surface_enhancer compare NAME` writes the scan before / after and the fibre-grid score (0–100: are the
vertical and the horizontal fibres of the papyrus visible together?) as images with numbers, plus `summary.json`.
