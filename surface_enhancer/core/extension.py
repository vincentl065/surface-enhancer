"""RETOUCHEUR DE SURFACE — EXTENSION d'un segment par une bande, sur un côté.

Principe (calculer) : la surface avance par petites bandes de quelques nœuds, rangée par rangée, au-delà de son bord :
  1. chaque rangée est prolongée en gardant sa direction ET sa courbure (parabole ajustée sur ses 16 derniers nœuds, lissée entre rangées) ;
  2. on lit le scan pour ces seuls nœuds neufs (le long de la normale, ± 40 vx : même lecteur de blocs que preparer.py, cache local d'abord,
     dépôt public sinon) et on y repère les feuilles ;
  3. on suit la feuille depuis le bord existant (auto_noyaux.suivre_graines : les nœuds du bord sont les ancres), sans rien inventer ;
  4. la bande suivante repart de la surface SUIVIE. Une rangée s'arrête dès que la feuille n'est plus suivie de façon continue (moins de `taux`
     des nœuds sur un pic à 3 nœuds à la ronde) ou plus sûre sur plus de `pont` nœuds, et finit sur son dernier nœud sûr.
La bande naît donc posée sur la feuille (son décalage h est celui du suivi). Le calcul ne modifie rien dans le segment.

Les côtés : « u1 » = au-delà de la dernière colonne de la grille, « u0 » = avant la première, « v1 » = après la dernière rangée, « v0 » = avant
la première. Tout le calcul se fait dans un repère retourné où l'on avance toujours vers les colonnes croissantes (vue / retour).

Dans le segment (classe Extension, ajoutée à Segment) : une extension est UN geste du journal (annulable). Les fichiers d'origine ne changent
jamais : la grille agrandie est refaite en mémoire à partir de la base + la liste des extensions appliquées (donnees/<nom>/extensions/eNNNNNN.npz,
pixels du scan de la bande dans le cache : ext_NNNNNN_bloc.npy). Un segment sans extension se charge exactement comme avant."""
from __future__ import annotations

import gc
import json
import os
import time
from pathlib import Path

import numpy as np

from .commun import (CARREAU, COUCHES, DEMI, HMAX, KPICS, ND, NIVEAUX, Scan, chercheur_de_pics, echantillonneur, ecrire_atomique, ecrire_json, interp_noeuds, normales,
                    valide_px)

COTES = ("u1", "u0", "v1", "v0")
TR = 256                     # les pixels lus d'une bande sont rangés par tranches de 256 rangées de pixels


def vue(a, cote):
    """Tableau de nœuds ou de pixels (2 premiers axes = rangée, colonne) vu dans le repère où l'on avance vers les colonnes croissantes."""
    if cote == "u1": return a
    if cote == "u0": return a[:, ::-1]
    if cote == "v1": return a.swapaxes(0, 1)
    return a.swapaxes(0, 1)[:, ::-1]


def retour(a, cote):
    """Inverse de vue."""
    if cote == "u1": return a
    if cote == "u0": return a[:, ::-1]
    if cote == "v1": return a.swapaxes(0, 1)
    return a[:, ::-1].swapaxes(0, 1)


def marches_de(P, N, val):
    """Marche signée (le long de la normale) de chaque arête ↔ et ↕ d'un morceau de grille ; 0 là où l'arête n'existe pas."""
    cu = np.zeros(val.shape, np.float64); cv = np.zeros(val.shape, np.float64)
    d = P[:, 1:] - P[:, :-1]; nm = N[:, 1:] + N[:, :-1]; nm = nm / (np.linalg.norm(nm, axis=-1, keepdims=True) + 1e-9); cu[:, :-1] = np.where(val[:, 1:] & val[:, :-1], (d * nm).sum(-1), 0)
    d = P[1:] - P[:-1]; nm = N[1:] + N[:-1]; nm = nm / (np.linalg.norm(nm, axis=-1, keepdims=True) + 1e-9); cv[:-1] = np.where(val[1:] & val[:-1], (d * nm).sum(-1), 0)
    return cu, cv


def repere_de(P, N, val):
    """Hauteur G de la surface au-dessus d'une base lisse (voir Auto._repere) pour un morceau de grille."""
    from scipy import fft as sfft
    gh, gw = val.shape; cu, cv = marches_de(P, N, val); d = np.zeros((gh, gw)); d[:, 1:] += cu[:, :-1]; d[:, :-1] -= cu[:, :-1]; d[1:] += cv[:-1]; d[:-1] -= cv[:-1]
    lam = (2 - 2 * np.cos(np.pi * np.arange(gh) / gh))[:, None] + (2 - 2 * np.cos(np.pi * np.arange(gw) / gw))[None, :]; lam[0, 0] = 1.0
    g = sfft.dctn(d, type=2, norm="ortho") / lam; g[0, 0] = 0.0
    return np.ascontiguousarray(sfft.idctn(g, type=2, norm="ortho").astype(np.float32))


class Bande:
    """Pixels du scan lus pour une bande, dans le repère retourné : un morceau rectangulaire par tranche de 256 rangées de pixels (le bord d'un
    segment est rarement droit : chaque tranche a ses propres colonnes), bout à bout dans UN fichier .npy à plat."""

    def __init__(self, fichier, Hpx, xa, xb, creer=False):
        self.Hpx = int(Hpx); self.xa = np.asarray(xa, np.int64); self.xb = np.maximum(np.asarray(xb, np.int64), self.xa); self.fichier = Path(fichier); nt = len(self.xa)
        self.ny = np.array([min(self.Hpx, (c + 1) * TR) - c * TR for c in range(nt)], np.int64); self.off = np.concatenate([[0], np.cumsum(self.ny * (self.xb - self.xa))])
        self.m = np.lib.format.open_memmap(self.fichier, mode="w+", dtype=np.uint8, shape=(max(int(self.off[-1]), 1), ND)) if creer else np.load(self.fichier, mmap_mode="r")

    def morceau(self, c):
        return self.m[self.off[c]:self.off[c + 1]].reshape(self.ny[c], self.xb[c] - self.xa[c], ND)

    def lire_points(self, ys, xs):
        """Colonnes de pixels (le long de la normale) aux points (ys, xs) ; zéro là où rien n'a été lu."""
        o = np.zeros((len(ys), ND), np.uint8); c = ys // TR; ok = (ys >= 0) & (ys < self.Hpx); ok &= (xs >= self.xa[np.clip(c, 0, len(self.xa) - 1)]) & (xs < self.xb[np.clip(c, 0, len(self.xa) - 1)])
        for k in np.unique(c[ok]):
            i = np.where(ok & (c == k))[0]; o[i] = self.morceau(k)[ys[i] - k * TR, xs[i] - self.xa[k]]
        return o

    def fermer(self, supprimer=False):
        self.m = None
        if supprimer:
            try: self.fichier.unlink()
            except OSError: pass


def pics_noeuds(bande, rr, cc, pas, seuil, contraste):
    """Feuilles repérées pour les nœuds (rr, cc), comme preparer.etape_pics : profil moyen sur 2 pas × 2 pas pixels autour du nœud (pixels lus
    seulement), lissé le long de la normale. → positions, forces (un nœud par ligne)."""
    from scipy import ndimage
    n = len(rr); som = np.zeros((n, ND), np.float32); cnt = np.zeros(n, np.float32)
    for a in range(-pas, pas):
        ys = np.clip(rr * pas + a, 0, bande.Hpx - 1)
        for b in range(-pas, pas):
            blk = bande.lire_points(ys, cc * pas + b); m = blk[:, DEMI - 2:DEMI + 3].max(-1) > 0; som += blk * m[:, None]; cnt += m
    p = ndimage.gaussian_filter1d(som / np.maximum(cnt, 1)[:, None], 1.2, axis=-1, mode="nearest"); po = np.empty((n, KPICS), np.float32); fo = np.empty((n, KPICS), np.float32)
    if n: chercheur_de_pics()(np.ascontiguousarray(p), po, fo, np.float32(seuil), 5, 10, DEMI)
    fo /= contraste; po[cnt < 1] = np.nan; fo[cnt < 1] = 0
    return po, fo


def calculer(seg, cote, n, saut=1.5, pont=8, bande=8, contexte=12, taux=0.7, reseau=True, dire=None, fichier=None):
    """Calcule une bande de `n` nœuds au plus sur le côté `cote` du segment `seg` (rien n'est modifié dans seg).
    → dictionnaire : pad (nœuds ajoutés à la grille : haut, bas, gauche, droite), rect (rectangle de la bande dans la NOUVELLE grille),
      masque / P0 / N / h / pos / force / sur (tableaux du rectangle), pixels (objet Bande, repère retourné) + pixels_dec (son décalage en
      colonnes de pixels), et les chiffres (rangées parties, arrêtées, part sûre, surface en mm²)."""
    from scipy import ndimage as ndi
    from ..prepare import sample_points as rendre_points
    from .auto_noyaux import recaler, suivre_graines
    import numba
    assert cote in COTES; t0 = time.time(); p = seg.pas; dire = dire or (lambda *a: None); C = int(contexte); n = int(n)
    numba.set_num_threads(max(1, min(4, numba.config.NUMBA_NUM_THREADS)))
    val0 = vue(seg.valide, cote); R, Wt = val0.shape; f0 = np.where(val0.any(1), Wt - 1 - np.argmax(val0[:, ::-1], 1), -1)
    if not (f0 >= 0).any(): raise ValueError("no surface to extend")
    c0 = int(max(0, f0[f0 >= 0].min() - C - 4)); Ww = Wt - c0 + n

    def fen(a, vide):
        w = np.full((R, Ww) + a.shape[2:], vide, a.dtype); w[:, :Wt - c0] = vue(a, cote)[:, c0:]; return w
    P = fen(seg.P0, 0).astype(np.float32); N = fen(seg.N, 0).astype(np.float32); val = fen(seg.valide, False); h = fen(seg.h, 0).astype(np.float32); pos = fen(seg.pos, np.nan); force = fen(seg.force, 0)
    f = np.where(f0 >= 0, f0 - c0, -1); fd = f.copy(); neuf = np.zeros((R, Ww), bool); sur = np.zeros((R, Ww), bool); aveugle = np.zeros(R, np.int64)
    ctx = np.array([val[r, max(0, f[r] - 5):f[r] + 1].sum() if f[r] >= 0 else 0 for r in range(R)]); actif = ctx >= 3; parties = int(actif.sum())
    if not parties: raise ValueError("the edge of the surface is too ragged on this side to be extended")
    # où la surface se tient par rapport au cœur de la feuille, près du bord (pour que la bande s'y tienne aussi)
    e = pos - h[..., None]; ae = np.where(np.isfinite(e), np.abs(e), np.inf); en = np.take_along_axis(e, ae.argmin(-1)[..., None], -1)[..., 0]
    pres = val & np.isfinite(en) & (np.abs(en) <= 4) & (np.arange(Ww)[None, :] >= (f - C)[:, None]); bord = float(-np.median(en[pres])) if pres.sum() >= 30 else 0.0; hlim = float(HMAX - abs(bord))
    # pixels à lire : par tranche de 256 rangées de pixels, du premier pixel après le bord le plus en retrait jusqu'à n nœuds après le plus avancé
    Hpx = (R - 1) * p + 1; nt = -(-Hpx // TR); xa = np.zeros(nt, np.int64); xb = np.zeros(nt, np.int64)
    for c in range(nt):
        r0, r1 = (c * TR) // p, min(R - 1, -(-(min(Hpx, (c + 1) * TR) - 1) // p)); ff = f[r0:r1 + 1][actif[r0:r1 + 1]]
        if len(ff): xa[c] = int(ff.min()) * p + 1; xb[c] = min(Ww - 1, int(ff.max()) + n) * p + 1
    tmp = Path(fichier) if fichier else seg.cache / f"ext_tmp_{os.getpid()}_{int(time.time())}.npy"; B = Bande(tmp, Hpx, xa, xb, creer=True)
    scan = Scan(seg.cfg["volume"], seg.cfg.get("cache_scan"), reseau=reseau, max_blocs=48); ech = echantillonneur()
    seuil = float(seg.cfg["pics"]["seuil_relief"]); contraste = float(seg.cfg["pics"]["contraste"]); conflits = 0; lus = 0; discontinues = 0; tps = dict(geometrie=0.0, scan=0.0, pics=0.0, suivi=0.0); tt = time.time()
    for etape in range(0, n, bande):
        rg = np.where(actif)[0]
        if not len(rg): break
        s = min(bande, n - etape); dire(f"Extending: strip {etape // bande + 1} of {-(-n // bande)} ({len(rg)} rows still going)…", 0.05 + 0.9 * etape / n)
        # 1. prolonger chaque rangée : parabole sur ses 16 derniers nœuds (surface suivie), direction et courbure lissées entre rangées
        m = 16; j = np.arange(-m + 1, 1); cols = f[rg][:, None] + j[None, :]; okc = (cols >= 0) & val[rg[:, None], np.maximum(cols, 0)]; cc = np.maximum(cols, 0)
        Sj = (P[rg[:, None], cc] + h[rg[:, None], cc][..., None] * N[rg[:, None], cc]).astype(np.float64); w = okc.astype(np.float64); phi = np.stack([np.ones(m), j, j * j], -1).astype(np.float64)
        A = np.einsum("rm,ma,mb->rab", w, phi, phi); A[:, 2, 2] += 40.0; A[:, 1, 1] += 1e-3; A[:, 0, 0] += 1e-6; b = np.einsum("rm,ma,rmc->rac", w, phi, Sj); co = np.linalg.solve(A, b)
        tb = np.zeros((R, 3)); tc = np.zeros((R, 3)); ma = np.zeros(R); tb[rg] = co[:, 1]; tc[rg] = co[:, 2]; ma[rg] = 1; den = ndi.gaussian_filter1d(ma, 4.0, mode="nearest") + 1e-9
        tb = ndi.gaussian_filter1d(tb, 4.0, axis=0, mode="nearest") / den[:, None]; tc = ndi.gaussian_filter1d(tc, 4.0, axis=0, mode="nearest") / den[:, None]
        lg = np.linalg.norm(tb, axis=-1, keepdims=True); tb = tb / np.maximum(lg, 1e-6) * np.clip(lg, 0.7 * p, 1.3 * p)                       # un pas de grille, à 30 % près
        bandeau = np.zeros((R, Ww), bool)
        for k in range(1, s + 1):
            c = f[rg] + k; ok = c < Ww; r_ = rg[ok]; c_ = c[ok]; S0 = P[r_, f[r_]] + h[r_, f[r_]][:, None] * N[r_, f[r_]]
            P[r_, c_] = (S0 + tb[r_] * k + tc[r_] * (k * k)).astype(np.float32); h[r_, c_] = 0; bandeau[r_, c_] = True
        val2 = val | bandeau
        # 2. normales des nœuds neufs (même calcul que preparer, orientées comme celles du bord)
        ca = int(max(0, f[rg].min() - 8)); cb = int(min(Ww, f[rg].max() + s + 1)); _, Nn = normales(P[:, ca:cb].astype(np.float32), val2[:, ca:cb])
        ref = np.zeros((R, 3), np.float32); ref[rg] = N[rg, f[rg]]; sg = np.where((Nn * ref[:, None, :]).sum(-1) < 0, -1.0, 1.0)[..., None]; bl = bandeau[:, ca:cb]; N[:, ca:cb][bl] = (Nn * sg)[bl]
        tps["geometrie"] += time.time() - tt; tt = time.time()
        # 3. lire le scan pour les pixels neufs, tranche par tranche
        for c in range(nt):
            r0, r1 = (c * TR) // p, min(R - 1, -(-(min(Hpx, (c + 1) * TR) - 1) // p)); ff = f[r0:r1 + 1][actif[r0:r1 + 1]]
            if not len(ff): continue
            x0 = max(int(ff.min()) * p + 1, int(xa[c])); x1 = min(int(min(Ww - 1, ff.max() + s)) * p + 1, int(xb[c]))
            if x1 <= x0: continue
            ys = np.arange(c * TR, min(Hpx, (c + 1) * TR)); xs = np.arange(x0, x1); okp = valide_px(val2, ys, xs, p) & ~valide_px(val, ys, xs, p)
            if not okp.any(): continue
            Pp = np.ascontiguousarray(interp_noeuds(P, ys, xs, p)[okp], np.float32); Np = interp_noeuds(N, ys, xs, p)[okp]; Np = np.ascontiguousarray(Np / (np.linalg.norm(Np, axis=-1, keepdims=True) + 1e-9), np.float32)
            out = np.empty((len(Pp), ND), np.uint8); rendre_points(scan, ech, Pp, Np, out); M = B.morceau(c); buf = np.array(M[:, x0 - xa[c]:x1 - xa[c]]); buf[okp] = out; M[:, x0 - xa[c]:x1 - xa[c]] = buf; lus += len(Pp)
        tps["scan"] += time.time() - tt; tt = time.time()
        # 4. feuilles repérées (provisoires) sur les nœuds neufs
        rr, cc2 = np.where(bandeau); po, fo = pics_noeuds(B, rr, cc2, p, seuil, contraste); pos[rr, cc2] = po; force[rr, cc2] = fo
        tps["pics"] += time.time() - tt; tt = time.time()
        # 5. suivre la feuille depuis le bord (les nœuds existants sont les ancres, ramenés au cœur de la feuille)
        la = int(max(0, f[rg].min() - C)); ub = int(min(Ww, f[rg].max() + s + 1)); G = repere_de(P[:, la:ub], N[:, la:ub], val2[:, la:ub]); vl = val[:, la:ub]
        Z = np.full(vl.shape, np.nan, np.float32); et = np.zeros(vl.shape, np.uint8); Z[vl] = (h[:, la:ub] + G)[vl] - bord; et[vl] = 1; et[vl & neuf[:, la:ub] & ~sur[:, la:ub]] = 2      # un nœud de bande posé sans pic ne compte pas comme sûr
        ag = (et == 2).astype(np.int32); libre = np.ascontiguousarray(bandeau[:, la:ub])
        conflits += int(suivre_graines(np.ascontiguousarray(pos[:, la:ub]), np.ascontiguousarray(force[:, la:ub]), libre, G, Z, et, ag, float(saut), int(pont), hlim))
        D, _ = recaler(Z, et == 1, (et == 2) & libre, np.ascontiguousarray(h[:, la:ub]), G, bord, 3.0, 100)
        hl = h[:, la:ub]; hl[libre] = np.clip(D[libre], -HMAX, HMAX); etb = np.zeros((R, Ww), np.uint8); etb[:, la:ub] = np.where(libre, et, 0)
        part = np.ones((R, Ww), np.float32); part[:, la:ub] = ndi.uniform_filter((et == 1).astype(np.float32), 7) / np.maximum(ndi.uniform_filter((et > 0).astype(np.float32), 7), 1e-3)      # part de nœuds sûrs à 3 nœuds à la ronde
        # 6. avancée des rangées
        for r in rg:
            c1 = min(Ww - 1, f[r] + s); e_ = etb[r, f[r] + 1:c1 + 1]; ks = np.where(e_ == 1)[0]; nb_ = c1 - f[r]
            if len(ks): aveugle[r] = nb_ - 1 - ks[-1]
            else: aveugle[r] += nb_
            flou = np.where(part[r, f[r] + 1:c1 + 1] < taux)[0]                                 # la feuille n'est plus suivie de façon continue : la rangée s'arrête là
            if len(flou): actif[r] = False; nb_ = int(flou[0]); discontinues += 1
            elif aveugle[r] > pont or nb_ < s:
                actif[r] = False
                if aveugle[r] > pont: nb_ = (ks[-1] + 1) if len(ks) else 0
            val[r, f[r] + 1:f[r] + 1 + nb_] = True; neuf[r, f[r] + 1:f[r] + 1 + nb_] = True; sur[r, f[r] + 1:f[r] + 1 + nb_] = e_[:nb_] == 1; f[r] += nb_
        tps["suivi"] += time.time() - tt; tt = time.time()
    # une rangée finit sur son dernier nœud sûr (pas de bout « à l'aveugle »)
    for r in range(R):
        if f[r] > fd[r]:
            ks = np.where(sur[r, fd[r] + 1:f[r] + 1])[0]; fin = fd[r] + 1 + (ks[-1] + 1 if len(ks) else 0); val[r, fin:f[r] + 1] = False; neuf[r, fin:f[r] + 1] = False; f[r] = fin - 1
    avance = (f - fd)[ctx >= 3]; um2 = (seg.um * p / 1000) ** 2; nn = int(neuf.sum()); mm = lambda k: round(float(k) * p * seg.um / 1000, 2)
    chiffres = dict(cote=cote, demande_mm=mm(n), parties=parties, complets=int((avance >= n).sum()), arretees=int((avance < 0.8 * n).sum()), sans_rien=int((avance <= 0).sum()), noeuds=nn, surs=int(sur.sum()),
                    mm2=round(nn * um2, 2), avance_mediane_mm=mm(np.median(avance)), avance_max_mm=mm(avance.max()), bord_mm=mm(parties), conflits=conflits, bord=round(bord, 2), pixels_lus=int(lus),
                    blocs=dict(disque=scan.lus_disque, reseau=scan.lus_reseau, absents=scan.absents), temps={k: round(v, 1) for k, v in tps.items()}, ms=round((time.time() - t0) * 1000))
    if not nn:
        B.fermer(True); return dict(rien=True, chiffres=chiffres)
    # pixels lus pour des nœuds finalement abandonnés : remis à zéro ; feuilles repérées définitives de la bande
    for c in range(nt):
        if xb[c] <= xa[c]: continue
        ys = np.arange(c * TR, min(Hpx, (c + 1) * TR)); ok = valide_px(val, ys, np.arange(xa[c], xb[c]), p); M = B.morceau(c); buf = np.array(M)
        if (buf.max(-1) > 0)[~ok].any(): buf[~ok] = 0; M[:] = buf
    rr, cc2 = np.where(neuf); po, fo = pics_noeuds(B, rr, cc2, p, seuil, contraste); pos[rr, cc2] = po; force[rr, cc2] = fo; pos[~val] = np.nan; force[~val] = 0; B.m.flush()
    # retour dans le repère de la grille, agrandie de ce qu'il faut (multiple de 16 pixels pour les niveaux réduits de la page)
    cols = np.where(neuf.any(0))[0]; wa, wz = int(cols[0]), int(cols[-1]) + 1; q = 16 // int(np.gcd(16, p)); npad = max(0, c0 + wz - Wt); npad = -(-npad // q) * q; Wn = Wt + npad; ct0 = c0 + wa; nb = wz - wa
    pad = dict(u1=(0, 0, 0, npad), u0=(0, 0, npad, 0), v1=(0, npad, 0, 0), v0=(npad, 0, 0, 0))[cote]
    rect = dict(u1=(0, R, ct0, ct0 + nb), u0=(0, R, Wn - ct0 - nb, Wn - ct0), v1=(ct0, ct0 + nb, 0, R), v0=(Wn - ct0 - nb, Wn - ct0, 0, R))[cote]
    T = lambda a: np.ascontiguousarray(retour(a[:, wa:wz], cote))
    return dict(cote=cote, pad=[int(x) for x in pad], rect=[int(x) for x in rect], masque=T(neuf), P0=T(P), N=T(N), h=T(np.where(neuf, h, 0).astype(np.float32)), pos=T(pos), force=T(force), sur=T(sur),
                pixels=B, pixels_dec=int(c0 * p), largeur_t=int(Wn), chiffres=chiffres)


def morceaux_de(E, B, pas):
    """Les pixels d'une bande (objet Bande, repère retourné) → morceaux rectangulaires (y, x, tableau) dans la grille agrandie par CETTE extension."""
    cote = E["cote"]; dec = int(E["pixels_dec"]); Wpx = (int(E["largeur_t"]) - 1) * pas + 1; r = []
    for c in range(len(B.xa)):
        if B.xb[c] <= B.xa[c]: continue
        a = B.morceau(c); y0 = c * TR; y1 = y0 + a.shape[0]; x0 = dec + int(B.xa[c]); x1 = dec + int(B.xb[c])
        if cote == "u1": r.append((y0, x0, a))
        elif cote == "u0": r.append((y0, Wpx - x1, a[:, ::-1]))
        elif cote == "v1": r.append((x0, y0, a.swapaxes(0, 1)))
        else: r.append((Wpx - x1, y0, a[:, ::-1].swapaxes(0, 1)))
    return r


class Mosaique:
    """Un grand tableau (rangées × colonnes [× profondeur]) fait de morceaux rectangulaires posés à des endroits donnés ; zéro ailleurs. Se lit
    comme un tableau : m[y0:y1, x0:x1], m[y, x0:x1], m[y0:y1, x], m[y0:y1], m[y]. Là où deux morceaux se recouvrent, la plus grande valeur
    l'emporte (un pixel pas lu vaut zéro)."""

    def __init__(self, forme, morceaux, dtype=np.uint8):
        self.shape = tuple(int(x) for x in forme); self.morceaux = list(morceaux); self.dtype = np.dtype(dtype); self.ndim = len(self.shape)

    def __len__(self): return self.shape[0]

    def __array__(self, dtype=None, copy=None):
        a = self[0:self.shape[0], 0:self.shape[1]]
        return a.astype(dtype) if dtype is not None else a

    def __getitem__(self, cle):
        if not isinstance(cle, tuple): cle = (cle,)
        cy = cle[0]; cx = cle[1] if len(cle) > 1 else slice(None); reste = cle[2:]

        def borne(c, n):
            if isinstance(c, slice): a, b, pas_ = c.indices(n); assert pas_ > 0; return a, max(a, b), pas_, False
            c = int(c); c = c + n if c < 0 else c
            if not 0 <= c < n: raise IndexError(c)
            return c, c + 1, 1, True
        y0, y1, sy, iy = borne(cy, self.shape[0]); x0, x1, sx, ix = borne(cx, self.shape[1]); o = np.zeros((y1 - y0, x1 - x0) + self.shape[2:], self.dtype)
        for (py, px, a) in self.morceaux:
            a0, a1, b0, b1 = max(y0, py), min(y1, py + a.shape[0]), max(x0, px), min(x1, px + a.shape[1])
            if a1 > a0 and b1 > b0: np.maximum(o[a0 - y0:a1 - y0, b0 - x0:b1 - x0], a[a0 - py:a1 - py, b0 - px:b1 - px], out=o[a0 - y0:a1 - y0, b0 - x0:b1 - x0])
        o = o[::sy, ::sx]; o = o[(0 if iy else slice(None)), (0 if ix else slice(None))] if (iy or ix) else o
        return o[(Ellipsis,) + tuple(reste)] if reste and not (iy and ix) else (o[tuple(reste)] if reste else o)


class Extension:
    """Méthodes ajoutées à Segment : la grille qui grandit (ou rapetisse quand on annule), le geste « etendre », sa persistance."""
    ext = ()                   # numéros des extensions appliquées, dans l'ordre
    org = (0, 0)               # où est le nœud (0, 0) de la grille d'origine dans la grille actuelle
    _base = None

    def _ext_fichier(self, i): return self.d / "extensions" / f"e{int(i):06d}.npz"
    def _ext_dossier(self): return Path(self.cfg.get("cache_ext") or self.cache)       # où vont les pixels du scan des bandes (le cache du segment, sauf mention contraire)
    def _ext_pixels(self, i): return self._ext_dossier() / f"ext_{self.nom}_{int(i):06d}_bloc.npy"

    def _ext_charger(self, i):
        z = np.load(self._ext_fichier(i)); E = {k: z[k] for k in z.files}
        for k in ("cote",): E[k] = str(E[k])
        for k in ("pixels_dec", "largeur_t", "Hpx"): E[k] = int(E[k])
        E["pixels"] = Bande(self._ext_pixels(i), E["Hpx"], E["xa"], E["xb"])
        return E

    def _disposer(self, ids):
        """Refait la grille en mémoire : la base (fichiers d'origine, jamais modifiés) + les extensions `ids`, dans l'ordre. Ne touche ni à h ni
        aux zones (l'appelant les agrandit ou les rogne)."""
        B = self._base; self.ext = [int(i) for i in ids]; p = self.pas
        if not self.ext:
            self.P0, self.N, self.valide, self.pos, self.force, self.bloc, self.pyr, self.encre = B["P0"], B["N"], B["valide"], B["pos"], B["force"], B["bloc"], B["pyr"], B["encre"]; self.org = (0, 0); self._bandes = None
        else:
            P0, N, val, pos, force = B["P0"].copy(), B["N"].copy(), B["valide"].copy(), B["pos"].copy(), B["force"].copy(); mor = [(0, 0, B["bloc"])]; ov = ou = 0; bandes = np.zeros(val.shape, bool)
            for i in self.ext:
                E = self._ext_charger(i); ph, pb, pg, pd = (int(x) for x in E["pad"])
                if ph or pb or pg or pd:
                    P0 = np.pad(P0, ((ph, pb), (pg, pd), (0, 0)), mode="edge"); N = np.pad(N, ((ph, pb), (pg, pd), (0, 0)), mode="edge"); val = np.pad(val, ((ph, pb), (pg, pd)))
                    pos = np.pad(pos, ((ph, pb), (pg, pd), (0, 0)), constant_values=np.nan); force = np.pad(force, ((ph, pb), (pg, pd), (0, 0))); bandes = np.pad(bandes, ((ph, pb), (pg, pd))); mor = [(y + ph * p, x + pg * p, a) for y, x, a in mor]; ov += ph; ou += pg
                v0, v1, u0, u1 = (int(x) for x in E["rect"]); m = E["masque"].astype(bool)
                P0[v0:v1, u0:u1][m] = E["P0"][m]; N[v0:v1, u0:u1][m] = E["N"][m]; val[v0:v1, u0:u1][m] = True; pos[v0:v1, u0:u1][m] = E["pos"][m]; force[v0:v1, u0:u1][m] = E["force"][m]; bandes[v0:v1, u0:u1][m] = True
                mor += morceaux_de(E, E["pixels"], p)
            self.P0, self.N, self.valide, self.pos, self.force = P0, N, val, pos, force; self.org = (ov, ou); self._bandes = bandes; gh, gw = val.shape; H, W = (gh - 1) * p + 1, (gw - 1) * p + 1
            self.bloc = Mosaique((H, W, ND), mor); self.pyr = {}; self.encre = {}; h_, w_ = H, W
            for L in range(1, NIVEAUX + 1):                              # niveaux réduits de la page : ceux de la base recopiés à leur place, la bande est rendue ensuite
                h_, w_ = (h_ + 1) // 2, (w_ + 1) // 2; a = np.zeros((h_, w_, 2 * COUCHES + 1), np.uint8); b = B["pyr"][L]; oy, ox = (ov * p) >> L, (ou * p) >> L
                a[oy:oy + b.shape[0], ox:ox + b.shape[1]] = b[:h_ - oy, :w_ - ox]; self.pyr[L] = a
            for cle, niveaux in B["encre"].items():
                fo = [(H, W)]
                for L in range(1, NIVEAUX + 1): fo.append(((fo[-1][0] + 1) // 2, (fo[-1][1] + 1) // 2))
                self.encre[cle] = [Mosaique(fo[L], [((ov * p) >> L, (ou * p) >> L, niveaux[L])]) for L in range(NIVEAUX + 1)]
        self.gh, self.gw = self.valide.shape; self.H, self.W = (self.gh - 1) * p + 1, (self.gw - 1) * p + 1; self.th, self.tw = -(-self.gh // CARREAU), -(-self.gw // CARREAU)
        self._c0 = None; self.fib = None; self._apercu = None

    def _apres_grille(self):
        """Après un changement de grille (h et zones déjà à la bonne taille) : page rendue là où il faut, scores refaits."""
        if self.ext and not self.rejeu:
            self._ext_rendre()
            if self.h.any(): r = np.where(self.h.any(1))[0]; c = np.where(self.h.any(0))[0]; self._maj_page(*self._px((r[0], r[-1] + 1, c[0], c[-1] + 1)))
        self.sc0 = self._scores_tout(np.zeros_like(self.h)); self.sc = self._scores_tout(self.h) if self.h.any() else {k: v.copy() for k, v in self.sc0.items()}; self._maj_zones_carreaux(); self.gen += 1

    def _ext_partie_origine(self):
        """h et zones sur la seule grille d'origine (ce que lisent les scripts existants)."""
        if not self.ext: return self.h, self.zones
        (ov, ou), (g0, w0) = self.org, self._base["valide"].shape
        return np.ascontiguousarray(self.h[ov:ov + g0, ou:ou + w0]), np.ascontiguousarray(self.zones[ov:ov + g0, ou:ou + w0])

    def _ext_rendre(self):
        """Rend la page (niveaux réduits) sur les bandes ajoutées."""
        b = self._bandes
        if b is not None and b.any(): r = np.where(b.any(1))[0]; c = np.where(b.any(0))[0]; self._maj_page(*self._px((r[0], r[-1] + 1, c[0], c[-1] + 1)))

    def _ext_basculer(self, i, poser):
        """Applique (poser) ou retire l'extension i : grille, h et zones agrandis ou rognés. L'extension retirée doit être la dernière appliquée."""
        E = self._ext_charger(i); ph, pb, pg, pd = (int(x) for x in E["pad"]); v0, v1, u0, u1 = (int(x) for x in E["rect"]); m = E["masque"].astype(bool); h, z = self.h, self.zones
        if poser:
            self._disposer(list(self.ext) + [i]); h = np.pad(h, ((ph, pb), (pg, pd))); z = np.pad(z, ((ph, pb), (pg, pd))); h[v0:v1, u0:u1][m] = E["h"][m]
        else:
            assert self.ext and self.ext[-1] == int(i), "extensions annulées dans le désordre"
            h = h.copy(); z = z.copy(); h[v0:v1, u0:u1][m] = 0; z[v0:v1, u0:u1][m] = False; h = h[ph:h.shape[0] - pb, pg:h.shape[1] - pd]; z = z[ph:z.shape[0] - pb, pg:z.shape[1] - pd]; self._disposer(list(self.ext)[:-1])
        self.h = np.ascontiguousarray(h, np.float32); self.zones = np.ascontiguousarray(z); self._apres_grille()
        return [ph * self.pas * (1 if poser else -1), pg * self.pas * (1 if poser else -1)]

    def _ext_calculer(self, p):
        """Calcul d'une bande (aperçu : rien n'est écrit dans le segment). Paramètres : cote, largeur (mm), saut, pont (nœuds), taux."""
        cote = str(p.get("cote", "u1"))
        if cote not in COTES: raise ValueError(f"unknown side: {cote}")
        n = int(np.clip(round(float(p.get("largeur", 2.0)) * 1000 / self.um / self.pas), 2, 400))
        for f in self._ext_dossier().glob(f"ext_tmp_{os.getpid()}_*.npy"):      # restes d'aperçus abandonnés (de ce serveur seulement)
            try: f.unlink()
            except OSError: pass
        return calculer(self, cote, n, saut=float(np.clip(p.get("saut", 1.5), 0.25, 4)), pont=int(np.clip(p.get("pont", 8), 0, 64)), taux=float(np.clip(p.get("taux", 0.7), 0.3, 1.0)), dire=self._dire,
                        fichier=self._ext_dossier() / f"ext_tmp_{os.getpid()}_{int(time.time() * 1000)}.npy")

    def apercu_extension(self, p):
        with self.verrou:
            self._apercu = None; self._dire("Extending: reading the edge…", 0.0); r = self._ext_calculer(p); self._dire("done", 1.0)
            if r.get("rien"): return dict(rien=True, auto=dict(outil="etendre", **r["chiffres"]), message="the sheet is not sure right after the edge on this side: nothing was added")
            self._apercu = dict(cle=self._cle_apercu("etendre", p), rec=r)
            return dict(outil="etendre", params=p, auto=dict(outil="etendre", **r["chiffres"]), gen=self.gen)

    def etendre(self, p, ident=None):
        """Le geste : la bande calculée (par l'aperçu, ou ici) devient une extension du segment. UN geste du journal, annulable. En rejeu, la
        bande n'est pas recalculée (il faudrait relire le scan) : on reprend celle qui a été enregistrée sous ce numéro."""
        with self.verrou:
            t0 = time.time(); i = int(ident) if ident is not None else self.dernier_id + 1
            if self._ext_fichier(i).exists() and (self.rejeu or ident is not None): chiffres = json.loads(str(np.load(self._ext_fichier(i))["chiffres"]))
            else:
                if self.rejeu: raise ValueError(f"extension {i} : fichier absent, impossible à rejouer")
                ap = self._apercu; self._apercu = None; r = ap["rec"] if ap and ap.get("rec") is not None and ap["cle"] == self._cle_apercu("etendre", p) else self._ext_calculer(p)
                if r.get("rien"): return dict(rien=True, message="the sheet is not sure right after the edge on this side: nothing was added", auto=dict(outil="etendre", **r["chiffres"]))
                B = r.pop("pixels"); chiffres = r.pop("chiffres"); (self.d / "extensions").mkdir(exist_ok=True); B.m.flush(); src = B.fichier; B.fermer(); gc.collect(); os.replace(src, self._ext_pixels(i))
                ecrire_atomique(self._ext_fichier(i), lambda t: np.savez_compressed(open(t, "wb"), xa=B.xa, xb=B.xb, Hpx=B.Hpx, chiffres=json.dumps(chiffres), **r))
            self.dernier_id = i; dec = self._ext_basculer(i, True); E = self._ext_charger(i); bbox = [int(x) for x in E["rect"]]
            if not self.rejeu: np.savez_compressed(self.d / "gestes" / f"g{i:06d}.npz", bbox=np.array(bbox), avant=np.zeros(1, np.float32), apres=np.zeros(1, np.float32), champ="grille")
            self._patchs[i] = dict(bbox=bbox, avant=np.zeros(1, np.float32), apres=np.zeros(1, np.float32), champ="grille")
            e = dict(type="geste", id=i, t=time.strftime("%Y-%m-%d %H:%M:%S"), outil="etendre", params=p, champ="grille", bbox=bbox, version=self.version, auto=dict(outil="etendre", **chiffres))
            self.gestes[i] = e; self.pile.append(i); self.refaire.clear(); self._journal(e); self._enregistrer("h"); self._enregistrer("zones")
            return dict(grille=True, decale=dec, etat=self.etat(), id=i, outil="etendre", auto=e["auto"], pile=len(self.pile), refaire=len(self.refaire), enregistre=self.enregistre, ms=round((time.time() - t0) * 1000))

    def _ext_annuler(self, i, sens):
        """Ctrl+Z / Ctrl+Y d'une extension (appelé par annuler, le numéro est déjà sorti de sa pile)."""
        dec = self._ext_basculer(i, sens > 0); (self.refaire if sens < 0 else self.pile).append(i)
        self._journal(dict(type="annuler" if sens < 0 else "retablir", id=i, t=time.strftime("%Y-%m-%d %H:%M:%S"))); self._enregistrer("h"); self._enregistrer("zones")
        return dict(grille=True, decale=dec, etat=self.etat(), id=i, outil="etendre", defait=sens < 0, auto=self.gestes.get(i, {}).get("auto"), pile=len(self.pile), refaire=len(self.refaire), enregistre=self.enregistre)

    def _exporter_etendu(self, dst):
        """Export tifxyz d'un segment agrandi : la grille actuelle entière (nœuds sans surface = −1)."""
        import tifffile
        Pc = self.P0 + self.h[..., None] * self.N
        for k, c in enumerate("zyx"): tifffile.imwrite(str(dst / f"{c}.tif"), np.where(self.valide, Pc[..., k], -1).astype(np.float32))
