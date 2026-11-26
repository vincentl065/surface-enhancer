"""Re-flatten a tifxyz surface after a retouch ("cloth relaxation"): same 3-D surface, new flat layout.

Moving nodes along the normal stretches the grid a little. This tool lays the surface flat again: every grid edge is a
spring whose rest length is its length in 3-D, a barrier keeps quads from flipping, and the 2-D positions are relaxed
(Adam) starting from the current layout. The result is written as a NEW tifxyz grid of the same size, in the SAME page
frame (rigid alignment on the old layout), so that images rendered before and after can be compared pixel to pixel,
up to the displacement of the relaxation. Each new node is a point of the old surface (bilinear between its nodes):
the sheet that is followed does not change, only the flattening.

Needs PyTorch (optional dependency; CPU is fine up to a few hundred thousand nodes).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .. import tifxyz


def relax_flat(P, valid, step, device="cpu", max_steps=4000, tol=1e-4, lr=0.5, log=print):
    """2-D positions (u = column axis, v = row axis, in voxels) of the valid nodes after relaxation. → uv (rows, cols, 2), NaN where invalid."""
    try:
        import torch
    except ImportError:
        raise SystemExit("the 'flatten' command needs PyTorch (pip install torch): it is an optional dependency")
    P = P.astype(np.float64)
    nr, nc = valid.shape
    idx = -np.ones((nr, nc), int)
    idx[valid] = np.arange(valid.sum())
    X0 = P[valid]

    def pairs(di, dj):
        I, J = np.meshgrid(np.arange(nr), np.arange(nc), indexing="ij")
        I2, J2 = I + di, J + dj
        m = (I2 >= 0) & (I2 < nr) & (J2 >= 0) & (J2 < nc)
        m[m] &= valid[I[m], J[m]] & valid[I2[m], J2[m]]
        return np.stack([idx[I[m], J[m]], idx[I2[m], J2[m]]], 1)

    E = np.concatenate([pairs(0, 1), pairs(1, 0), pairs(1, 1), pairs(1, -1)])
    L0 = np.linalg.norm(X0[E[:, 0]] - X0[E[:, 1]], axis=1)
    E, L0 = E[L0 > 1.0], L0[L0 > 1.0]
    q = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    Qi = np.argwhere(q)
    Q = np.stack([idx[Qi[:, 0], Qi[:, 1]], idx[Qi[:, 0], Qi[:, 1] + 1], idx[Qi[:, 0] + 1, Qi[:, 1] + 1], idx[Qi[:, 0] + 1, Qi[:, 1]]], 1)
    A0 = np.linalg.norm(np.cross(X0[Q[:, 2]] - X0[Q[:, 0]], X0[Q[:, 3]] - X0[Q[:, 1]]), axis=1)
    A0 = np.maximum(A0, 0.05 * np.median(A0))                       # zero-area quads (merged nodes) would divide by zero
    I_, J_ = np.nonzero(valid)
    G2 = np.stack([J_, I_], 1) * float(step)                        # the current flat layout: the grid itself
    uv0 = G2 - G2.mean(0)
    d1 = uv0[Q[:, 2]] - uv0[Q[:, 0]]
    d2 = uv0[Q[:, 3]] - uv0[Q[:, 1]]
    sgn = float(np.sign(np.median(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0])))
    f32 = torch.float32
    Et = torch.tensor(E, device=device)
    L0t = torch.tensor(L0, device=device, dtype=f32)
    Qt = torch.tensor(Q, device=device)
    A0t = torch.tensor(A0, device=device, dtype=f32)
    UV = torch.tensor(uv0, device=device, dtype=f32, requires_grad=True)
    opt = torch.optim.Adam([UV], lr=lr)
    sch = torch.optim.lr_scheduler.LinearLR(opt, 1.0, 0.02, max_steps)
    prev, it = None, 0
    t0 = time.time()
    for it in range(max_steps):
        opt.zero_grad()
        lg = (UV[Et[:, 0]] - UV[Et[:, 1]]).norm(dim=1)
        e = (((lg - L0t) / L0t) ** 2).mean()
        d1 = UV[Qt[:, 2]] - UV[Qt[:, 0]]
        d2 = UV[Qt[:, 3]] - UV[Qt[:, 1]]
        area = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) * sgn
        e = e + 20 * (torch.relu(0.2 - area / A0t) ** 2).mean()
        e.backward()
        opt.step()
        sch.step()
        if it % 200 == 199:
            v = float(e.item())
            if prev is not None and (prev - v) < tol * prev:
                break
            prev = v
    u = UV.detach().cpu().numpy().astype(np.float64)
    r = np.linalg.norm(u[E[:, 0]] - u[E[:, 1]], axis=1) / L0
    rg = np.linalg.norm(G2[E[:, 0]] - G2[E[:, 1]], axis=1) / L0
    stats = dict(nodes=int(len(X0)), springs=int(len(E)), steps=it + 1, seconds=round(time.time() - t0, 1), device=str(device),
                 stretched_over_10pct_before=float(np.mean(np.abs(rg - 1) > 0.1)), stretched_over_10pct_after=float(np.mean(np.abs(r - 1) > 0.1)),
                 rms_before=float(np.sqrt(np.mean((rg - 1) ** 2))), rms_after=float(np.sqrt(np.mean((r - 1) ** 2))))
    log(f"relaxation: {stats['steps']} steps in {stats['seconds']} s on {device} · springs off by more than 10 %: {stats['stretched_over_10pct_before']:.1%} → {stats['stretched_over_10pct_after']:.1%}")
    out = np.full((nr, nc, 2), np.nan)
    out[valid] = u
    return out, stats


def flatten(src, dst, device="cpu", log=print) -> dict:
    """Write ``dst`` (a NEW tifxyz folder): the surface of ``src`` laid flat again, same grid size, same page frame."""
    from scipy import ndimage as ndi
    from scipy.interpolate import griddata
    src = tifxyz.find_tifxyz(src)
    dst = Path(dst)
    P, valid, step, meta = tifxyz.read_grid(src)                    # P is (z, y, x)
    gh, gw = valid.shape
    UV, stats = relax_flat(P[..., ::-1], valid, step, device=device, log=log)
    ok = valid & np.isfinite(UV).all(-1)
    I, J = np.nonzero(ok)
    G = np.stack([J, I], 1).astype(np.float64) * step
    U = UV[ok].astype(np.float64)
    cu, cg = U.mean(0), G.mean(0)                                   # rigid alignment (rotation + translation) on the old layout
    Uu, _, Vt = np.linalg.svd((U - cu).T @ (G - cg))
    R = (Uu @ Vt).T
    if np.linalg.det(R) < 0:
        Vt[-1] *= -1
        R = (Uu @ Vt).T
    U2 = (U - cu) @ R.T + cg
    moved = np.linalg.norm(U2 - G, axis=1)
    gi, gj = np.mgrid[0:gh, 0:gw]
    target = np.stack([gj.ravel() * step, gi.ravel() * step], 1).astype(np.float64)
    mi = griddata(U2, I.astype(np.float64), target, method="linear").reshape(gh, gw)
    mj = griddata(U2, J.astype(np.float64), target, method="linear").reshape(gh, gw)
    good = np.isfinite(mi) & np.isfinite(mj)
    mi0, mj0 = np.where(good, mi, 0), np.where(good, mj, 0)
    idx = ndi.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    good &= ndi.map_coordinates(valid.astype(np.float32), [mi0, mj0], order=1) > 0.999
    Pf = P[idx[0], idx[1]].astype(np.float64)
    out = [np.where(good, ndi.map_coordinates(Pf[..., i], [mi0, mj0], order=1), -1).astype(np.float32) for i in range(3)]      # z, y, x
    z, y, x = out
    new = tifxyz.segment_meta(meta, dst.name, 1.0 / step, tifxyz.bbox_xyz(x, y, z, good), area_vx2_=tifxyz.area_vx2(np.stack(out, -1), good),
                              provenance=dict(tool="surface-enhancer flatten", source_id=meta.get("uuid") or src.name, **stats,
                                              median_shift_px=round(float(np.median(moved)), 2), max_shift_px=round(float(moved.max()), 1)))
    tifxyz.write_tifxyz(dst, x, y, z, new, valid=good)
    np.savez_compressed(dst / "flatten_inverse_map.npz", row=mi0.astype(np.float32), col=mj0.astype(np.float32), valid=good)
    r = dict(folder=str(dst), valid_before=int(valid.sum()), valid_after=int(good.sum()), median_shift_px=float(np.median(moved)), max_shift_px=float(moved.max()), **stats)
    log(json.dumps(r, indent=1))
    return r
