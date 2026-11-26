"""RETOUCHEUR DE SURFACE — briques communes (préparation, serveur, export).

Idée centrale : on ne retouche jamais la surface d'origine. On lit une fois le scan le long de la normale de la surface d'origine
(± DEMI voxels) : c'est le « bloc redressé » (hauteur × largeur × 81), où la surface d'origine est le plan du milieu. Une retouche est un
simple DÉCALAGE h (en voxels le long de cette normale) posé sur chaque nœud de la grille. La page à plat, les coupes, les scores et
l'export se recalculent à partir du bloc et de h, sans relire le scan : tout est instantané, sur le processeur seul.
"""
from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

DEMI = 40                 # le bloc couvre −40 … +40 voxels le long de la normale
ND = 2 * DEMI + 1
COUCHES = 8               # la page à plat se regarde de −8 à +8 voxels autour de la surface retouchée
HMAX = DEMI - COUCHES     # décalage maximal d'une retouche (au-delà : exporter puis préparer de nouveau)
CARREAU = 8               # un carreau de score = 8 nœuds de grille (8 × 4 vx × 9,362 µm ≈ 0,30 mm)
KPICS = 10                # feuilles repérées au plus dans un profil
NIVEAUX = 4               # niveaux réduits de la page (÷ 2 … ÷ 16)
TUILE = 256


# ───────────────────────────── grille tifxyz ─────────────────────────────
def trouver_tifxyz(d) -> Path:
    from ..tifxyz import find_tifxyz
    return find_tifxyz(d)


def charger_grille(t: Path):
    """→ P (hauteur, largeur, 3) en (z, y, x), valide, pas (voxels entre deux nœuds), méta."""
    from ..tifxyz import read_grid          # same validity rule as VC3D: z > 0, finite, optional mask.tif
    return read_grid(t)


def normales(P, valide, sigma=2.5):
    """Normale par nœud (même convention que le rendu de l'atelier : dérivée en largeur × dérivée en hauteur, composantes z, y, x), lissée
    sur `sigma` nœuds pour que les colonnes du bloc ne se croisent pas au-dessus d'une marche. → (P comblé, N)."""
    from scipy import ndimage
    idx = ndimage.distance_transform_edt(~valide, return_distances=False, return_indices=True)
    Pf = P[idx[0], idx[1]]
    du = np.gradient(Pf, axis=1); dv = np.gradient(Pf, axis=0)
    N = np.cross(du, dv)
    N /= np.linalg.norm(N, axis=-1, keepdims=True) + 1e-9
    m = valide.astype(np.float32)
    den = ndimage.gaussian_filter(m, sigma) + 1e-6
    N = np.stack([ndimage.gaussian_filter(N[..., i] * m, sigma) / den for i in range(3)], -1)
    N /= np.linalg.norm(N, axis=-1, keepdims=True) + 1e-9
    N = N[idx[0], idx[1]]
    return Pf.astype(np.float32), N.astype(np.float32)


def interp_noeuds(A, ys, xs, pas):
    """Valeurs d'un tableau posé sur les nœuds (hauteur, largeur[, c]) aux pixels (ys, xs) de la page (1 pixel = 1 voxel), en bilinéaire."""
    A3 = A if A.ndim == 3 else A[..., None]
    fy = np.asarray(ys, np.float32) / pas; i0 = np.clip(np.floor(fy).astype(np.int64), 0, A.shape[0] - 2); ty = (fy - i0)[:, None, None]
    fx = np.asarray(xs, np.float32) / pas; j0 = np.clip(np.floor(fx).astype(np.int64), 0, A.shape[1] - 2); tx = (fx - j0)[None, :, None]
    h = A3[i0]; b = A3[i0 + 1]
    r = (h[:, j0] * (1 - tx) + h[:, j0 + 1] * tx) * (1 - ty) + (b[:, j0] * (1 - tx) + b[:, j0 + 1] * tx) * ty
    return r if A.ndim == 3 else r[..., 0]


def valide_px(valide, ys, xs, pas):
    """Un pixel est rendu si les nœuds qui l'entourent (ceux dont le poids n'est pas nul) sont tous valides."""
    ys = np.asarray(ys); xs = np.asarray(xs)
    i0 = np.clip(ys // pas, 0, valide.shape[0] - 1); i1 = np.clip((ys + pas - 1) // pas, 0, valide.shape[0] - 1)
    j0 = np.clip(xs // pas, 0, valide.shape[1] - 1); j1 = np.clip((xs + pas - 1) // pas, 0, valide.shape[1] - 1)
    return valide[i0][:, j0] & valide[i0][:, j1] & valide[i1][:, j0] & valide[i1][:, j1]


def _numba():
    import numba
    return numba


_fonctions = {}


def echantillonneur():
    """Lecture trilinéaire du scan le long de la normale, compilée (numba), sur quelques fils seulement (le PC sert à autre chose)."""
    if "ech" not in _fonctions:
        nb = _numba()

        @nb.njit(parallel=True, cache=True, nogil=True)
        def ech(vol, oz, oy, ox, P, N, out, demi):
            Zs, Ys, Xs = vol.shape
            for i in nb.prange(P.shape[0]):
                for j in range(2 * demi + 1):
                    d = j - demi
                    z = P[i, 0] + d * N[i, 0] - oz; y = P[i, 1] + d * N[i, 1] - oy; x = P[i, 2] + d * N[i, 2] - ox
                    z0 = int(np.floor(z)); y0 = int(np.floor(y)); x0 = int(np.floor(x))
                    if z0 < 0 or y0 < 0 or x0 < 0 or z0 + 1 >= Zs or y0 + 1 >= Ys or x0 + 1 >= Xs:
                        out[i, j] = 0; continue
                    fz = z - z0; fy = y - y0; fx = x - x0
                    c00 = vol[z0, y0, x0] * (1 - fx) + vol[z0, y0, x0 + 1] * fx
                    c01 = vol[z0, y0 + 1, x0] * (1 - fx) + vol[z0, y0 + 1, x0 + 1] * fx
                    c10 = vol[z0 + 1, y0, x0] * (1 - fx) + vol[z0 + 1, y0, x0 + 1] * fx
                    c11 = vol[z0 + 1, y0 + 1, x0] * (1 - fx) + vol[z0 + 1, y0 + 1, x0 + 1] * fx
                    v = (c00 * (1 - fy) + c01 * fy) * (1 - fz) + (c10 * (1 - fy) + c11 * fy) * fz
                    out[i, j] = np.uint8(v + 0.5)
        _fonctions["ech"] = ech
    return _fonctions["ech"]


def chercheur_de_pics():
    """Repère les feuilles dans un profil le long de la normale : maxima locaux, classés par relief (hauteur au-dessus du creux le plus haut
    des deux côtés, dans ± fen voxels), au moins `ecart` voxels entre deux feuilles, position au dixième de voxel (parabole)."""
    if "pics" not in _fonctions:
        nb = _numba()

        @nb.njit(parallel=True, cache=True, nogil=True)
        def pics(prof, pos, force, seuil, ecart, fen, demi):
            n, nd = prof.shape; K = pos.shape[1]
            for i in nb.prange(n):
                p = prof[i]
                cj = np.empty(nd, np.int64); cp = np.empty(nd, np.float32); nc = 0
                for j in range(1, nd - 1):
                    if p[j] > p[j - 1] and p[j] >= p[j + 1]:
                        a = p[j]; b = p[j]
                        for q in range(max(0, j - fen), j):
                            if p[q] < a: a = p[q]
                        for q in range(j + 1, min(nd, j + fen + 1)):
                            if p[q] < b: b = p[q]
                        pr = p[j] - max(a, b)
                        if pr >= seuil:
                            cj[nc] = j; cp[nc] = pr; nc += 1
                gj = np.empty(K, np.int64); gp = np.empty(K, np.float32); ng = 0
                pris = np.zeros(nc, np.bool_)
                while ng < K:
                    m = -1; best = 0.0
                    for c in range(nc):
                        if not pris[c] and cp[c] > best:
                            best = cp[c]; m = c
                    if m < 0: break
                    pris[m] = True; ok = True
                    for g in range(ng):
                        if abs(gj[g] - cj[m]) < ecart: ok = False
                    if ok:
                        gj[ng] = cj[m]; gp[ng] = cp[m]; ng += 1
                for a_ in range(ng):                             # tri par position
                    for b_ in range(a_ + 1, ng):
                        if gj[b_] < gj[a_]:
                            t = gj[a_]; gj[a_] = gj[b_]; gj[b_] = t; u = gp[a_]; gp[a_] = gp[b_]; gp[b_] = u
                for g in range(K):
                    if g < ng:
                        j = gj[g]; den = p[j - 1] - 2 * p[j] + p[j + 1]
                        dx = 0.5 * (p[j - 1] - p[j + 1]) / den if den < -1e-6 else 0.0
                        pos[i, g] = j + dx - demi; force[i, g] = gp[g]
                    else:
                        pos[i, g] = np.nan; force[i, g] = 0.0
        _fonctions["pics"] = pics
    return _fonctions["pics"]


# ───────────────────────────── petits outils ─────────────────────────────
def fondu(x):
    """Fondu doux : 1 au centre, 0 à partir de x = 1 (demi-cosinus)."""
    x = np.clip(x, 0, 1)
    return 0.5 * (1 + np.cos(np.pi * x))


def enveloppe(f, pente=1.0):
    """Plus petite fonction ≥ f dont deux nœuds voisins ne diffèrent jamais de plus de `pente` voxel : élargit le fondu d'une retouche au lieu
    de laisser une marche (le point tiré garde sa valeur). Séparable : lignes puis colonnes."""
    g = np.array(f, np.float32, copy=True)
    for axe in (0, 1):
        v = np.moveaxis(g, axe, 0)
        for i in range(1, v.shape[0]): np.maximum(v[i], v[i - 1] - pente, out=v[i])
        for i in range(v.shape[0] - 2, -1, -1): np.maximum(v[i], v[i + 1] - pente, out=v[i])
    return g


def reduire2(a):
    """Moitié de la taille (moyenne 2 × 2) ; bord impair : dernière ligne / colonne répétée."""
    if a.shape[0] % 2: a = np.concatenate([a, a[-1:]], 0)
    if a.shape[1] % 2: a = np.concatenate([a, a[:, -1:]], 1)
    a = a.astype(np.float32)
    return (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]) * 0.25


def ecrire_atomique(chemin: Path, ecrire):
    """Écrit dans un fichier voisin puis le renomme : jamais de fichier à moitié écrit si le PC s'arrête."""
    chemin = Path(chemin); tmp = chemin.with_name(chemin.name + f".{os.getpid()}.tmp")
    ecrire(tmp); os.replace(tmp, chemin)


def ecrire_json(chemin: Path, obj):
    ecrire_atomique(chemin, lambda t: Path(t).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8"))


# ───────────────────────────── scan : adaptateur vers surface_enhancer.volume ─────────────────────────────
def Scan(volume, cache=None, reseau=True, max_blocs=160):
    """Ancien lecteur de blocs 128³ (cache local, puis dépôt public) : maintenant surface_enhancer.volume.VolumeReader.
    `cache` = le dossier exact des blocs (cfg["cache_scan"]), ou None pour un volume local lu directement.
    Mêmes compteurs qu'avant : lus_disque, lus_reseau, absents."""
    from ..volume import VolumeReader

    class _Scan(VolumeReader):
        lus_disque = property(lambda self: self.from_disk)
        lus_reseau = property(lambda self: self.from_source)
        absents = property(lambda self: self.missing)
        c = 128

        def bloc(self, k):
            return self.block(k)
    return _Scan(volume, chunk_cache=cache or None, network=reseau, max_blocks=max_blocs)
