"""Scan before / after a retouch, with the fibre-grid score — no GPU, no model, read from the straightened block.

The fibre-grid score measures whether vertical AND horizontal papyrus fibres are visible together in a 32 px window
(share of the fine-detail energy along each fibre direction, the smaller of the two; best of four depths; rescaled
to 0–100 between the 5th and 95th percentile of the ORIGINAL surface, so that before and after share one scale).
A surface that sits inside one sheet shows the fibre grid; a surface that cuts through sheets or voids does not.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _numbers(img, values, cell, fmt="{:.0f}"):
    """Write the median of each block of ``cell`` × ``cell`` windows on the map (never colour alone)."""
    import cv2
    ny, nx = values.shape
    k = img.shape[0] / ny
    for j in range(cell // 2, ny, cell):
        for i in range(cell // 2, nx, cell):
            blk = values[max(0, j - cell // 2):j + cell // 2 + 1, max(0, i - cell // 2):i + cell // 2 + 1]
            if np.isfinite(blk).mean() > 0.6:
                t = fmt.format(float(np.nanmedian(blk)))
                p = (int(i * k - 5 * len(t)), int(j * k + 5))
                cv2.putText(img, t, p, cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(img, t, p, cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def _title(img, text):
    import cv2
    bar = np.full((34, img.shape[1], 3), 24, np.uint8)
    cv2.putText(bar, text[:max(8, img.shape[1] // 10)], (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def compare(seg, out_dir, max_width=2400) -> dict:
    """Write ``ct_before.png``, ``ct_after.png``, ``ct_before_after.jpg``, ``fibre_score_before_after.jpg`` and ``summary.json``."""
    import cv2
    from ..core.commun import DEMI
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    H, W = seg.H, seg.W
    before = np.zeros((H, W), np.uint8)
    after = np.zeros((H, W), np.uint8)
    for y0 in range(0, H, 256):
        y1 = min(H, y0 + 256)
        before[y0:y1] = np.asarray(seg.bloc[y0:y1, :, DEMI])
        after[y0:y1] = np.clip(seg.page_px(y0, y1, 0, W, [0])[..., 0] + 0.5, 0, 255).astype(np.uint8)
    flip = -1 if seg.cfg.get("miroir") else 1
    b8, a8 = seg.lut8[before][:, ::flip], seg.lut8[after][:, ::flip]
    cv2.imwrite(str(out_dir / "ct_before.png"), b8)
    cv2.imwrite(str(out_dir / "ct_after.png"), a8)
    f = min(1.0, max_width / (2 * W))
    small = [cv2.cvtColor(cv2.resize(im, None, fx=f, fy=f, interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR) for im in (b8, a8)]
    moved = int((seg.valide & (np.abs(seg.h) > 0.25)).sum())
    gap = np.full((small[0].shape[0] + 34, 8, 3), 24, np.uint8)
    cv2.imwrite(str(out_dir / "ct_before_after.jpg"), np.hstack([_title(small[0], "BEFORE - original surface"), gap, _title(small[1], f"AFTER - retouched ({moved} nodes moved)")]), [cv2.IMWRITE_JPEG_QUALITY, 90])

    F = seg._fib_pret()
    n0, n1 = seg._fib_note(F["q0"]), seg._fib_note(F["q"])
    summary = dict(segment=seg.nom, version=seg.version, nodes_moved=moved, offset_max_vx=round(float(np.abs(seg.h).max()), 2),
                   fibre_score=seg._fib_bilan(n0, n1), surface_score=seg.bilan(),
                   keys={"avant": "before", "apres": "after", "monte": "% of windows up by more than 10", "baisse": "% of windows down by more than 10",
                         "marquees": "marked areas", "reste": "rest of the page", "fenetres": "windows"})

    def heat(a, lo, hi, cmap):
        im = cv2.applyColorMap((np.clip((np.nan_to_num(a, nan=lo) - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8), cmap)
        im[~np.isfinite(a)] = 40
        k = max(2, min(8, int(900 / max(a.shape[1], 1))))
        im = cv2.resize(im[:, ::flip], None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)
        return _numbers(im, a[:, ::flip], max(5, 60 // k))
    if n0.size:
        diff = np.where(np.isfinite(n0) & np.isfinite(n1), n1 - n0, np.nan)
        p = summary["fibre_score"]["page"]
        cv2.imwrite(str(out_dir / "fibre_score_before_after.jpg"),
                    np.hstack([_title(heat(n0, 0, 100, cv2.COLORMAP_VIRIDIS), f"FIBRE SCORE BEFORE (0-100) - page {p.get('avant')}"),
                               _title(heat(n1, 0, 100, cv2.COLORMAP_VIRIDIS), f"AFTER - page {p.get('apres')}"),
                               _title(heat(diff, -30, 30, cv2.COLORMAP_CIVIDIS), "DIFFERENCE after - before (numbers; bright = better)")]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(folder=str(out_dir), fibre_score_page=summary["fibre_score"]["page"], nodes_moved=moved)
