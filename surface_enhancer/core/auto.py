"""RETOUCHEUR DE SURFACE — gestes AUTOMATIQUES sur tout le segment. Chaque bouton = UN geste du journal (un seul Ctrl+Z), calculé d'abord en APERÇU (rien n'est écrit), avec un
bilan chiffré et la carte de ce qui bougerait.

  suivre          « Follow the sheet from here » : suivi d'UNE feuille de proche en proche depuis le point épinglé (auto_noyaux.suivre)
  aimant_partout  « Magnet everywhere »          : l'aimant existant sur toute la grille (ou les zones marquées), jamais de marche > 1 vx
  marches         « Remove steps »               : régions séparées par des marches ramenées sur la feuille de la région de référence
  fibres          « Best fibres »                : profondeur (± N vx) qui donne le quadrillage de fibres le plus net, champ lissé

La note de quadrillage des fibres (mesure directe, sans apprentissage) : min(part de l'énergie fine dans l'axe des fibres verticales, part dans l'axe des horizontales),
détails de pas 3 à 12 px, fenêtre de 32 px, pas de 16 px ; meilleure des 4 profondeurs 0 / −3 / −1 / +1 vx ; moyenne glissante sur 5 fenêtres ;
ramenée à 0–100 entre le 5e et le 95e centile de la surface d'ORIGINE (même échelle avant et après).
Ces méthodes s'ajoutent à la classe Segment (segment.py : class Segment(Auto))."""
from __future__ import annotations

import heapq
import json
import time

import cv2
import numpy as np

from .commun import DEMI, HMAX, ND, ecrire_atomique, interp_noeuds

FN, FHOP = 32, 16


def _masques_fibres():
    fy = np.fft.fftfreq(FN)[:, None]; fx = np.fft.rfftfreq(FN)[None, :]; fr = np.sqrt(fx ** 2 + fy ** 2); ang = np.degrees(np.arctan2(np.abs(fy), np.abs(fx)))
    bd = (fr >= 1 / 12) & (fr < 1 / 3)                                   # bandes « 3–6 px » et « 6–12 px » de l'audit, réunies
    w = np.full((1, FN // 2 + 1), 2.0); w[0, 0] = 1.0; w[0, -1] = 1.0   # demi-spectre (image réelle) : chaque case compte deux fois, sauf les deux colonnes de bord
    M = np.stack([(bd & (ang <= 15)) * w, (bd & (ang >= 75)) * w, bd * w], -1).reshape(-1, 3)
    return M.astype(np.float64), (np.hanning(FN)[:, None] * np.hanning(FN)[None, :]).astype(np.float32)


MQ, WIN = _masques_fibres()


def q_fibres(img, ok):
    """Quadrillage par fenêtre de 32 px au pas de 16 px, pour UNE image : min(énergie des fibres verticales, des horizontales) / énergie fine
    totale. NaN là où la fenêtre n'est pas pleine à 98 %. Mêmes nombres que e6_traits_fibres.spectre → min(V3 + V6, H3 + H6) / (T3 + T6 + 0,001)."""
    from scipy import fft as sfft
    h, w = img.shape; ny, nx = (h - FN) // FHOP + 1, (w - FN) // FHOP + 1; q = np.full((max(ny, 0), max(nx, 0)), np.nan, np.float32)
    if ny <= 0 or nx <= 0: return q
    img = img.astype(np.float32); vue = np.lib.stride_tricks.sliding_window_view
    for i in range(ny):
        blk = vue(img[i * FHOP:i * FHOP + FN], FN, axis=1)[:, ::FHOP].transpose(1, 0, 2); blk = (blk - blk.mean((1, 2), keepdims=True)) * WIN
        F = sfft.rfft2(blk.astype(np.float64)); e = (F.real ** 2 + F.imag ** 2).reshape(nx, -1) @ MQ
        val = vue(ok[i * FHOP:i * FHOP + FN], FN, axis=1)[:, ::FHOP].mean((0, 2))
        q[i] = np.where(val >= 0.98, np.minimum(e[:, 0], e[:, 1]) / (e[:, 2] + 1e-3), np.nan)
    return q


def lis(a, k):
    """Moyenne glissante sur k fenêtres en ignorant les absentes (e9_note_physique.lis)."""
    from scipy import ndimage as ndi
    v = np.isfinite(a); w = ndi.uniform_filter(v.astype(np.float32), k); r = ndi.uniform_filter(np.where(v, a, 0).astype(np.float32), k) / np.maximum(w, 1e-3); r[~v] = np.nan
    return r


def _stat(a):
    return round(float(a), 2) if np.isfinite(a) else None


class Auto:
    AUTOS = ("suivre", "aimant_partout", "marches", "fibres")
    avancement = None          # ce que le calcul en cours est en train de faire (la page le demande pendant qu'elle attend)
    fib = None                 # carte de la note de quadrillage des fibres (faite à la première demande)
    _apercu = None             # dernier aperçu calculé : « Apply » le réutilise tel quel si rien n'a changé entre-temps
    _c0 = None
    _auto = None               # bilan (et carte) du geste automatique qui vient d'être calculé

    def _dire(self, texte, part=None):
        self.avancement = dict(texte=texte, part=None if part is None else round(float(part), 3), t=round(time.time(), 1))

    # ───────────────────────── marches de toute la grille, bilan commun ─────────────────────────
    def _marches_tout(self, h=None):
        """Marche signée (saut le long de la normale) de chaque arête ↔ et ↕ de toute la grille, par bandes (peu de mémoire). NaN = pas d'arête."""
        h = self.h if h is None else h; cu = np.full((self.gh, self.gw), np.nan, np.float32); cv = np.full((self.gh, self.gw), np.nan, np.float32)
        for v0 in range(0, self.gh, 128):
            v1 = min(v0 + 128, self.gh); A = self._aretes(v0, v1, 0, self.gw, h); cu[v0:v1] = A["cu"]; cv[v0:v1] = A["cv"]
        return cu, cv

    def _scores_bandes(self, t0, t1, s0, s1, h=None):
        """_scores_rect par bandes de 24 carreaux quand le rectangle est grand (geste sur tout le segment) : même résultat, peu de mémoire."""
        if t1 - t0 <= 32: return self._scores_rect(t0, t1, s0, s1, h)
        rs = [self._scores_rect(a, min(a + 24, t1), s0, s1, h) for a in range(t0, t1, 24)]
        return {k: np.concatenate([r[k] for r in rs], 0) for k in rs[0]}

    def _repere(self):
        """G : hauteur de la surface d'ORIGINE au-dessus d'une base lisse (celle dont les normales lissées sont les normales). Dans le repère
        Z = h + G, une feuille est lisse même là où la surface d'origine saute d'une feuille à l'autre ou ondule. G est la solution, aux
        moindres carrés, de « G(voisin) − G(nœud) = marche de la surface d'origine entre les deux » (équation de Poisson, résolue par cosinus)."""
        if self._c0 is None:
            from scipy import fft as sfft
            gh, gw = self.gh, self.gw; cu, cv = self._marches_tout(np.zeros((gh, gw), np.float32)); cu = np.nan_to_num(cu).astype(np.float64); cv = np.nan_to_num(cv).astype(np.float64)
            d = np.zeros((gh, gw)); d[:, 1:] += cu[:, :-1]; d[:, :-1] -= cu[:, :-1]; d[1:] += cv[:-1]; d[:-1] -= cv[:-1]
            lam = (2 - 2 * np.cos(np.pi * np.arange(gh) / gh))[:, None] + (2 - 2 * np.cos(np.pi * np.arange(gw) / gw))[None, :]; lam[0, 0] = 1.0
            g = sfft.dctn(d, type=2, norm="ortho") / lam; g[0, 0] = 0.0; self._c0 = np.ascontiguousarray(sfft.idctn(g, type=2, norm="ortho").astype(np.float32))
        return self._c0

    def _poser(self, delta):
        """Pose un écart voulu sur toute la grille sans créer de marche : _adoucir (le fondu s'élargit tout seul), puis contrôle sur la surface
        réelle. _adoucir compte les écarts comme s'ils s'ajoutaient tels quels aux marches ; là où les normales de deux voisins divergent un
        peu, il peut rester quelques centièmes de voxel de trop sur une poignée d'arêtes : on les reprend (chaque nœud de l'arête fait la
        moitié du chemin) jusqu'à ce qu'aucune marche ne dépasse max(1 vx, ce qu'elle était). → nouvelles hauteurs de toute la grille."""
        _, neuf = self._adoucir((0, self.gh, 0, self.gw), delta.astype(np.float32)); neuf = np.where(self.valide, np.clip(neuf, -HMAX, HMAX), self.h).astype(np.float32); cu0, cv0 = self._marches_tout(self.h)
        with np.errstate(invalid="ignore"):
            lu = np.maximum(1, np.abs(cu0)) + 0.002; lv = np.maximum(1, np.abs(cv0)) + 0.002
            for _ in range(25):
                cu1, cv1 = self._marches_tout(neuf); eu = np.nan_to_num(np.sign(cu1) * np.maximum(np.abs(cu1) - lu, 0)); ev = np.nan_to_num(np.sign(cv1) * np.maximum(np.abs(cv1) - lv, 0))
                if not (eu.any() or ev.any()): break
                a = np.zeros(neuf.shape, np.float32); a[:, :-1] += 0.5 * eu[:, :-1]; a[:, 1:] -= 0.5 * eu[:, :-1]; a[:-1] += 0.5 * ev[:-1]; a[1:] -= 0.5 * ev[:-1]
                neuf = np.where(self.valide, np.clip(neuf + 1.02 * a, -HMAX, HMAX), self.h).astype(np.float32)
        return neuf

    def _fin_auto(self, outil, neuf, t0, pas_sur=None, champ=None, greffe=False, fib_q=None, **plus):
        """Fin commune des gestes automatiques. `greffe` : on ne garde de la proposition que les parties qui ne dégradent pas le quadrillage
        des fibres (_greffer). Puis bilan chiffré (nœuds déplacés, marches avant → après, part laissée telle quelle, note de quadrillage des
        fibres avant → après) et carte de ce qui bouge. → (rectangle = toute la grille, nouvelles hauteurs), au format des autres gestes ;
        le bilan attend dans self._auto."""
        val = self.valide; neuf = np.where(val, np.clip(neuf, -HMAX, HMAX), self.h).astype(np.float32); refus = None; fibres = None
        if greffe: neuf, fib_q, refus, plus["greffe"] = self._greffer(neuf)
        elif fib_q is None and not self.rejeu and (np.abs(neuf - self.h) > 0.05).any():
            F = self._fib_pret(); rect = self._fib_rect(np.abs(neuf - self.h) > 0.05); fib_q = F["q"].copy()
            fib_q[rect[0]:rect[1], rect[2]:rect[3]] = self._q_audit(neuf, rect, "Fibre score after…", (0.6, 0.95))
        if fib_q is not None: fibres = self._fib_bilan(self._fib_note(self.fib["q"]), self._fib_note(fib_q))
        d = neuf - self.h; b = val & (np.abs(d) > 0.05); nv = int(val.sum()); nb = int(b.sum())
        champ = val if champ is None else (champ & val); nc = int(champ.sum()); ps = np.zeros(val.shape, bool) if pas_sur is None else (pas_sur & champ)
        cu0, cv0 = self._marches_tout(self.h); cu1, cv1 = self._marches_tout(neuf); fin = int(np.isfinite(cu0).sum() + np.isfinite(cv0).sum())
        with np.errstate(invalid="ignore"):
            compte = lambda cu, cv, s: int((np.abs(cu) > s).sum() + (np.abs(cv) > s).sum())
            creees = int((np.abs(cu1) > np.maximum(1, np.abs(cu0)) + 0.02).sum() + (np.abs(cv1) > np.maximum(1, np.abs(cv0)) + 0.02).sum())
            bilan = dict(outil=outil, noeuds=nv, champ=nc, deplaces=nb, mediane=_stat(np.median(np.abs(d[b]))) if nb else 0.0, max=_stat(np.abs(d[b]).max()) if nb else 0.0,
                         signe=[_stat(x) for x in np.percentile(d[b], (10, 50, 90))] if nb else [0.0, 0.0, 0.0], vers_haut=int((d[b] < 0).sum()), vers_bas=int((d[b] > 0).sum()),
                         feuille=int((np.abs(d[b]) >= 4).sum()), aretes=fin, marches3=[compte(cu0, cv0, 3.0), compte(cu1, cv1, 3.0)], marches1=[compte(cu0, cv0, 1.02), compte(cu1, cv1, 1.02)],
                         creees=creees, pas_sur=int(ps.sum()), refuses=int(refus.sum()) if refus is not None else 0, fibres=fibres, ms=round((time.time() - t0) * 1000), **plus)
        carte = np.zeros(val.shape, np.uint8); carte[b & (d < 0)] = 1; carte[b & (d > 0)] = 2; carte[b & (np.abs(d) >= 4)] |= 4; carte[ps] |= 8
        if refus is not None: carte[refus & ~b] |= 16
        self._auto = dict(bilan=bilan, carte=carte, fib_q=fib_q); self._dire("done", 1.0)
        return (0, self.gh, 0, self.gw), neuf

    def _greffer(self, neuf):
        """« Garder les parties gagnantes » : compare, fenêtre par fenêtre, la note de quadrillage des fibres de la proposition à celle de la
        surface actuelle (moyennées sur 5 fenêtres), et REFUSE (la surface y reste telle quelle) :
        (1) là où la note baisserait de plus de 2 points ;
        (2) toute plaque qui changerait de feuille (déplacement ≥ 4 vx, d'un seul tenant, sans traverser une marche existante) SAUF si la note
            y monte d'au moins 2 points en moyenne, ou si au moins la moitié de son tour est une marche existante (> 3 vx) que la proposition
            efface — une région posée sur la feuille d'à côté : là, la preuve est géométrique — et que la note n'y baisse pas de plus de 2.
        → (surface retenue, carte de quadrillage de cette surface, nœuds refusés, chiffres)."""
        from scipy import ndimage as ndi
        F = self._fib_pret(); gh, gw = self.gh, self.gw; ny, nx = F["q"].shape; d = neuf - self.h; bouge = np.abs(d) > 0.05; rect = self._fib_rect(bouge)
        if rect is None: return neuf, F["q"], np.zeros((gh, gw), bool), dict(proposes=0, refuses=0, plaques=0, plaques_refusees=0, plaques_par_couture=0)
        qc = F["q"].copy(); qc[rect[0]:rect[1], rect[2]:rect[3]] = self._q_audit(neuf, rect, "Fibre score of the proposal…", (0.55, 0.75))
        gain = lis(self._fib_note(qc) - self._fib_note(F["q"]), 5)
        vi = np.clip(np.round((np.arange(gh) * self.pas - FN / 2) / FHOP).astype(int), 0, ny - 1); ui = np.clip(np.round((np.arange(gw) * self.pas - FN / 2) / FHOP).astype(int), 0, nx - 1)
        gn = gain[np.ix_(vi, ui)]; mesure = np.isfinite(gn); refus = bouge & mesure & (gn < -2.0); gros = bouge & (np.abs(d) >= 4); n = 0; pr = 0; pc = 0
        if gros.any():
            from .auto_noyaux import etiqueter
            cu0, cv0 = self._marches_tout(self.h); cu1, cv1 = self._marches_tout(neuf)
            la, na = etiqueter(gros & (d > 0), cu0, cv0, 3.0); lb, nb = etiqueter(gros & (d < 0), cu0, cv0, 3.0); lab = np.where(la >= 0, la + 1, np.where(lb >= 0, lb + 1 + na, 0)); n = int(na + nb)
            idx = np.arange(1, n + 1); nm = ndi.sum(mesure, lab, idx); moy = ndi.sum(np.where(mesure, gn, 0), lab, idx) / np.maximum(nm, 1); tour = np.zeros(n + 1); efface = np.zeros(n + 1)
            with np.errstate(invalid="ignore"):
                for c0, c1, A, B in ((cu0[:, :-1], cu1[:, :-1], lab[:, :-1], lab[:, 1:]), (cv0[:-1], cv1[:-1], lab[:-1], lab[1:])):
                    bord = (A != B) & np.isfinite(c0); e = bord & (np.abs(c0) > 3.0) & (np.abs(c1) <= 3.0)
                    for X in (A, B): tour += np.bincount(X[bord], minlength=n + 1); efface += np.bincount(X[e], minlength=n + 1)
            couture = efface[1:] / np.maximum(tour[1:], 1) >= 0.5; garde = ((nm >= 64) & (moy >= 2.0)) | (couture & ((nm < 64) | (moy >= -2.0)))
            mauvais = np.zeros(n + 1, bool); mauvais[1:] = ~garde; juste = np.zeros(n + 1, bool); juste[1:] = couture & garde; pr = int(mauvais.sum()); pc = int(juste.sum())
            refus = (refus & ~juste[lab]) | mauvais[lab]
        stats = dict(proposes=int(bouge.sum()), refuses=int(refus.sum()), plaques=n, plaques_refusees=pr, plaques_par_couture=pc)
        if not refus.any(): return neuf, qc, refus, stats
        self._dire("Keeping only the winning parts…", 0.78); n2 = self._poser(np.where(refus, 0, d)); r2 = self._fib_rect(np.abs(n2 - self.h) > 0.05); qn = F["q"].copy()
        if r2 is not None: qn[r2[0]:r2[1], r2[2]:r2[3]] = self._q_audit(n2, r2, "Fibre score after…", (0.8, 0.97))
        return n2, qn, refus, stats

    def _fib_rect(self, masque):
        """Rectangle de fenêtres de 32 px qui touchent les nœuds du masque (None s'il est vide)."""
        if not masque.any(): return None
        r = np.where(masque.any(1))[0]; c = np.where(masque.any(0))[0]; y0, y1, x0, x1 = self._px((r[0], r[-1] + 1, c[0], c[-1] + 1)); ny, nx = self._fib_dims()
        a = (max(0, (y0 - FN) // FHOP + 1), min(ny, (y1 - 1) // FHOP + 1), max(0, (x0 - FN) // FHOP + 1), min(nx, (x1 - 1) // FHOP + 1))
        return a if a[1] > a[0] and a[3] > a[2] else None

    def _cle_apercu(self, outil, p):
        return (outil, json.dumps(p, sort_keys=True), self.n_evt, self.gen)

    def apercu(self, outil, p):
        """Calcule un geste automatique SANS l'écrire : bilan + carte de ce qui bougerait. « Apply » (le geste du même nom, mêmes paramètres)
        reprend ce résultat tel quel si la surface n'a pas changé entre-temps."""
        from .segment import paquet
        if outil not in self.AUTOS: raise ValueError(f"no preview for this tool: {outil}")
        with self.verrou:
            self._apercu = None; self._auto = None; self._dire("computing…", 0.0); r = getattr(self, self.OPS[outil])(p); a = self._auto or {}; self._auto = None
            if r is None: return paquet(dict(rien=True, message="nothing to change here"), {})
            dif = np.abs(r[1] - self.h[r[0][0]:r[0][1], r[0][2]:r[0][3]]) > 1e-4
            if not dif.any(): return paquet(dict(rien=True, message="nothing would change: the surface is already there", auto=a.get("bilan")), {})
            self._apercu = dict(cle=self._cle_apercu(outil, p), r=r, auto=a)
            return paquet(dict(outil=outil, params=p, auto=a.get("bilan"), gen=self.gen, grille=[self.gh, self.gw]), {"carte": a.get("carte", np.zeros((1, 1), np.uint8))})

    # ───────────────────────── 1. suivre la feuille depuis l'ancre ─────────────────────────
    def _op_suivre(self, p):
        """Suivi d'UNE feuille de proche en proche depuis le point épinglé (auto_noyaux.suivre). Chaque nœud prend, parmi SES pics repérés,
        celui qui prolonge ses voisins déjà posés (à moins de `saut` vx du plan ajusté sur eux) ; sinon il est « pas sûr ».
        Prudence : on ne garde comme SÛRE que la région où la feuille est suivie de façon continue (au moins `taux` des nœuds à 3 nœuds à la
        ronde sont sur un pic) ET reliée à l'ancre sans trou de plus de `pont` nœuds. Là, la surface est posée sur la feuille de l'ancre (une
        partie posée sur la feuille d'à côté y est ramenée) ; les trous y suivent leurs voisins ; partout ailleurs, la surface reste TELLE
        QUELLE (raccord en fondu, jamais de marche de plus de 1 vx créée)."""
        from scipy import ndimage as ndi
        from .auto_noyaux import recaler, suivre
        t0 = time.time(); gh, gw = self.gh, self.gw
        if not p.get("ancre"): raise ValueError("pin a point first (click on the page, on a spot where the surface is on the right sheet): it is the anchor")
        saut = float(np.clip(p.get("saut", 1.5), 0.25, 4)); pont = int(np.clip(p.get("pont", 8), 0, 64)); bord = float(np.clip(p.get("bord", 0.0), -8, 8)); seuil = float(np.clip(p.get("seuil", 3.0), 1, 12))
        taux = float(np.clip(p.get("taux", 0.7), 0.3, 1.0)); a0, b0 = int(np.clip(round(float(p["ancre"][0])), 0, gh - 1)), int(np.clip(round(float(p["ancre"][1])), 0, gw - 1)); meilleur = None
        for dv in range(-3, 4):                                           # l'ancre : le nœud tout proche dont un pic est à moins de 4 vx de la surface
            for du in range(-3, 4):
                v, u = a0 + dv, b0 + du
                if not (0 <= v < gh and 0 <= u < gw and self.valide[v, u]): continue
                e = self.pos[v, u] - (self.h[v, u] - bord); e = e[np.isfinite(e) & (np.abs(self.pos[v, u]) <= HMAX - abs(bord))]
                if e.size and np.abs(e).min() <= 4:
                    c = float(np.abs(e).min() + np.hypot(dv, du)); x = float(e[np.abs(e).argmin()] + self.h[v, u] - bord)
                    if meilleur is None or c < meilleur[0]: meilleur = (c, v, u, x)
        if meilleur is None: raise ValueError("no sheet detected under the anchor (within 4 vx of the surface): pin a point where the surface sits on a sheet")
        _, av, au, ta = meilleur; self._dire("Following the sheet from the anchor…", 0.1); G = self._repere()
        Z, etat, conflits = suivre(self.pos, self.force, self.valide, G, av, au, float(ta), saut, pont, float(HMAX - abs(bord)))
        self._dire("Following the sheet: keeping only what is continuous up to the anchor…", 0.5)
        pic = etat == 1; k = 7; part = ndi.uniform_filter(pic.astype(np.float32), k) / np.maximum(ndi.uniform_filter((etat > 0).astype(np.float32), k), 1e-3)
        continu = pic & (part >= taux); continu[av, au] = True; lab, _ = ndi.label(ndi.binary_dilation(continu, iterations=max(pont // 2, 0)) if pont >= 2 else continu, structure=np.ones((3, 3), bool))
        sur = continu & (lab == lab[av, au]); zone = (ndi.binary_dilation(sur, iterations=max(pont, 1)) & (etat > 0)) | sur
        D, nit = recaler(Z, sur, zone, self.h, G, bord, seuil, 200); self._dire("Following the sheet: blending without steps…", 0.7)
        neuf = self._poser(D); self._dire("Following the sheet: counting the steps…", 0.85)
        self._suivi = dict(Z=Z, etat=etat, sur=sur, zone=zone, part=part) if p.get("garder") else None
        return self._fin_auto("suivre", neuf, t0, pas_sur=~sur, greffe=bool(p.get("greffe", True)), ancre=[av, au], suivis=int(sur.sum()), sur_pic=int(pic.sum()), ecartes=int((pic & ~sur).sum()), raccord=int((zone & ~sur).sum()),
                              conflits=int(conflits), non_atteints=int((self.valide & (etat == 0)).sum()), passes=int(nit), saut=saut, pont=pont, taux=taux, bord=bord)

    # ───────────────────────── carte des sauts de feuille (26/11) ─────────────────────────
    def sauts(self, p):
        """CARTE DES SAUTS DE FEUILLE, sans rien écrire. La feuille de l'ancre (le point épinglé) est suivie de proche en proche, comme pour
        « Follow the sheet » ; puis chaque nœud de la surface ACTUELLE est comparé à cette feuille : dessus, N feuilles plus haut ou plus bas
        (N = nombre de feuilles repérées entre les deux), entre deux feuilles, ou « pas sûr » là où la feuille de l'ancre n'est pas suivie
        de façon continue jusque-là. La frontière entre deux zones est un saut de feuille.
        Codes de la carte : 0 hors surface · 1 même feuille · 2, 3, 4 = 1, 2, 3 feuilles ou plus vers le HAUT de la coupe · 5, 6, 7 = vers le
        BAS · 8 entre deux feuilles (à 3 vx ou plus de la feuille de l'ancre, sans feuille repérée entre) · 9 pas sûr."""
        from scipy import ndimage as ndi
        from .auto_noyaux import suivre
        from .segment import paquet
        with self.verrou:
            t0 = time.time(); gh, gw = self.gh, self.gw
            if not p.get("ancre"): raise ValueError("pin a point first (right-click on the page, on a spot where the surface is on the right sheet): it is the reference")
            saut = float(np.clip(p.get("saut", 1.5), 0.25, 4)); pont = int(np.clip(p.get("pont", 8), 0, 64)); taux = float(np.clip(p.get("taux", 0.7), 0.3, 1.0))
            a0, b0 = int(np.clip(round(float(p["ancre"][0])), 0, gh - 1)), int(np.clip(round(float(p["ancre"][1])), 0, gw - 1)); meilleur = None
            for dv in range(-3, 4):                                       # l'ancre : le nœud tout proche dont un pic est à moins de 4 vx de la surface
                for du in range(-3, 4):
                    v, u = a0 + dv, b0 + du
                    if not (0 <= v < gh and 0 <= u < gw and self.valide[v, u]): continue
                    e = self.pos[v, u] - self.h[v, u]; e = e[np.isfinite(e) & (np.abs(self.pos[v, u]) <= HMAX)]
                    if e.size and np.abs(e).min() <= 4:
                        c = float(np.abs(e).min() + np.hypot(dv, du)); x = float(e[np.abs(e).argmin()] + self.h[v, u])
                        if meilleur is None or c < meilleur[0]: meilleur = (c, v, u, x)
            if meilleur is None: raise ValueError("no sheet detected under the pinned point (within 4 vx of the surface): pin a point where the surface sits on a sheet")
            _, av, au, ta = meilleur; G = self._repere()
            Z, etat, conflits = suivre(self.pos, self.force, self.valide, G, av, au, float(ta), saut, pont, float(HMAX))
            pic = etat == 1; k = 7; part = ndi.uniform_filter(pic.astype(np.float32), k) / np.maximum(ndi.uniform_filter((etat > 0).astype(np.float32), k), 1e-3)
            continu = pic & (part >= taux); continu[av, au] = True
            lab, _ = ndi.label(ndi.binary_dilation(continu, iterations=max(pont // 2, 0)) if pont >= 2 else continu, structure=np.ones((3, 3), bool))
            sur = continu & (lab == lab[av, au]); z = (Z - G).astype(np.float32); h = self.h; val = self.valide
            with np.errstate(invalid="ignore"):
                d = h - z; q = self.pos
                dessus = ((q >= (h - 2)[..., None]) & (q < (z - 2)[..., None])).sum(-1)          # feuilles repérées entre la surface et la feuille suivie, surface plus haut
                dessous = ((q > (z + 2)[..., None]) & (q <= (h + 2)[..., None])).sum(-1)         # … surface plus bas
                tri = np.sort(q, -1); ecarts = np.diff(tri, axis=-1); ecarts = ecarts[np.isfinite(ecarts) & (ecarts > 3)]
                esp = float(np.median(ecarts)) if ecarts.size else 12.0                              # écart habituel entre deux feuilles voisines, ici
                estime = np.round(np.abs(np.nan_to_num(d)) / max(esp, 4.0)).astype(np.int64)      # là où la feuille d'arrivée n'est pas repérée : nombre de feuilles estimé par la distance
                dessus = np.where(dessus >= 1, dessus, estime); dessous = np.where(dessous >= 1, dessous, estime)
            carte = np.zeros((gh, gw), np.uint8); carte[val] = 9; m = sur & val
            carte[m] = 1; loin = m & (np.abs(d) >= 3); carte[loin] = 8
            haut = loin & (d < 0) & (dessus >= 1); bas = loin & (d > 0) & (dessous >= 1)
            carte[haut] = (1 + np.clip(dessus, 1, 3))[haut]; carte[bas] = (4 + np.clip(dessous, 1, 3))[bas]
            carte = np.where(m, cv2.medianBlur(np.where(m, carte, 1).astype(np.uint8), 5), carte).astype(np.uint8)      # pas de poussière : un nœud isolé ne fait pas une zone
            nv = max(int(val.sum()), 1); parts = {str(c): round(100.0 * float((carte == c).sum()) / nv, 2) for c in range(1, 10)}
            zones = []; ailleurs = (carte >= 2) & (carte <= 7); labz, nz = ndi.label(ailleurs, structure=np.ones((3, 3), bool))
            if nz:
                tailles = ndi.sum(ailleurs, labz, np.arange(1, nz + 1)); um = float(self.um or 0)
                for i in np.argsort(-tailles)[:12]:
                    if tailles[i] < 25: break
                    mm_ = labz == i + 1; cv_, cu_ = ndi.center_of_mass(mm_); c = int(np.bincount(carte[mm_]).argmax())
                    vv, uu = np.nonzero(mm_); j = int(np.argmin((vv - cv_) ** 2 + (uu - cu_) ** 2))      # un nœud de la zone, le plus près de son centre
                    zones.append(dict(v=int(vv[j]), u=int(uu[j]), classe=c, feuilles=(-(c - 1) if c <= 4 else c - 4), noeuds=int(tailles[i]),
                                      mm2=round(float(tailles[i]) * (self.pas * um / 1000.0) ** 2, 2) if um else None))
            return paquet(dict(ancre=[int(av), int(au)], grille=[gh, gw], parts=parts, zones=zones, espacement=round(esp, 1), conflits=int(conflits), gen=self.gen, ms=round((time.time() - t0) * 1000)), {"carte": carte})

    # ───────────────────────── 2. l'aimant partout ─────────────────────────
    def _op_aimant_partout(self, p):
        """L'aimant existant (_cible_aimant) sur toute la grille, ou seulement dans les zones marquées ; au plus ± borne ; option de bord
        (à `bord` voxels du cœur de la feuille). Passe par _adoucir : jamais de marche de plus de 1 vx créée."""
        t0 = time.time(); gh, gw = self.gh, self.gw; borne = float(np.clip(p.get("borne", 6), 1, 16)); bord = float(np.clip(p.get("bord", 0.0), -8, 8))
        champ = (self.zones & self.valide) if p.get("zones") else self.valide
        if not champ.any(): raise ValueError("no marked area: paint one first (tool M), or untick “only in the marked areas”")
        t = np.zeros((gh, gw), np.float32); loin = np.zeros((gh, gw), bool); M = 24
        for v0 in range(0, gh, 256):
            v1 = min(v0 + 256, gh); a0, a1 = max(0, v0 - M), min(gh, v1 + M); t[v0:v1] = self._cible_aimant((a0, a1, 0, gw), borne, bord=bord)[v0 - a0:v1 - a0]
            e = self.pos[v0:v1] - self.h[v0:v1, :, None]; loin[v0:v1] = np.where(np.isfinite(e), np.abs(e), np.inf).min(-1) > borne
            self._dire("Magnet everywhere: finding the sheet…", 0.5 * v1 / gh)
        t[~champ] = 0; self._dire("Magnet everywhere: blending without steps…", 0.55)
        neuf = self._poser(t); self._dire("Magnet everywhere: counting the steps…", 0.85)
        return self._fin_auto("aimant_partout", neuf, t0, pas_sur=loin, champ=champ, greffe=bool(p.get("greffe", False)), borne=borne, bord=bord, zones=bool(p.get("zones")))

    # ───────────────────────── 3. enlever les marches ─────────────────────────
    def _op_marches(self, p):
        """Découpe la surface en régions séparées par des marches (saut entre voisins > seuil), garde comme référence la région de l'ancre (ou la
        plus grande) et ramène chaque autre région sur la feuille de la référence : décalage = l'écart mesuré le long de la couture (médiane),
        recalé sur les pics réels de la région. Une région dont la couture n'est pas nette, ou qui n'aurait pas de feuille repérée à l'arrivée,
        ou qui sortirait de ± 32 vx, est laissée telle quelle et comptée « not fixed »."""
        from .auto_noyaux import etiqueter
        t0 = time.time(); gh, gw = self.gh, self.gw; seuil = float(np.clip(p.get("seuil", 3.0), 1, 12)); h = self.h; self._dire("Remove steps: finding the regions…", 0.1)
        cu, cv = self._marches_tout(h); lab, n = etiqueter(self.valide, cu, cv, seuil)
        if n == 0: return None
        L = lab.ravel(); tailles = np.bincount(L[L >= 0], minlength=n)
        if p.get("ancre"):
            av, au = int(np.clip(round(float(p["ancre"][0])), 0, gh - 1)), int(np.clip(round(float(p["ancre"][1])), 0, gw - 1)); ref = int(lab[av, au]) if lab[av, au] >= 0 else int(tailles.argmax())
        else: ref = int(tailles.argmax())
        with np.errstate(invalid="ignore"): mu = np.abs(cu) > seuil; mv = np.abs(cv) > seuil
        ea = np.concatenate([np.flatnonzero(mu), np.flatnonzero(mv)]); eb = np.concatenate([np.flatnonzero(mu) + 1, np.flatnonzero(mv) + gw]); ec = np.concatenate([cu[mu], cv[mv]]).astype(np.float32)
        la, lb = L[ea], L[eb]; internes = int((la == lb).sum()); ext = la != lb; ea, eb, ec, la, lb = ea[ext], eb[ext], ec[ext], la[ext], lb[ext]
        # chaque arête de couture vue des deux côtés : (ma région, l'autre région, marche en allant de MON nœud vers l'autre)
        reg = np.concatenate([la, lb]); autre = np.concatenate([lb, la]); cs = np.concatenate([ec, -ec]); o = np.argsort(reg, kind="stable"); reg, autre, cs = reg[o], autre[o], cs[o]
        deb = np.searchsorted(reg, np.arange(n + 1)); on = np.argsort(L, kind="stable"); dn = np.searchsorted(L[on], np.arange(n + 1))
        decal = np.full(n, np.nan, np.float32); decal[ref] = 0.0; raisons = {}; file = []; hf = h.ravel(); pf = self.pos.reshape(-1, self.pos.shape[-1])

        def voisines(r):
            for a in np.unique(autre[deb[r]:deb[r + 1]]):
                if not np.isfinite(decal[a]):
                    k = int(np.isfinite(decal[autre[deb[a]:deb[a + 1]]]).sum()); heapq.heappush(file, (-k, int(a)))
        voisines(ref); essais = 0
        while file:
            _, r = heapq.heappop(file)
            if np.isfinite(decal[r]): continue
            essais += 1
            if essais % 500 == 0: self._dire("Remove steps: bringing the regions back…", 0.2 + 0.5 * min(1.0, essais / max(n, 1)))
            au_, cc = autre[deb[r]:deb[r + 1]], cs[deb[r]:deb[r + 1]]; ok = np.isfinite(decal[au_])
            if not ok.any(): continue
            x = decal[au_[ok]] + cc[ok]; s = float(np.median(x))                                      # décalage qui annule la marche le long de la couture
            if (np.abs(x - s) <= max(2.0, 0.5 * seuil)).mean() < 0.6: raisons[r] = "couture"; continue
            idx = on[dn[r]:dn[r + 1]]; hh = hf[idx]; pp = pf[idx]; e = pp - hh[:, None]; ae = np.where(np.isfinite(e), np.abs(e), np.inf); e0 = np.take_along_axis(e, ae.argmin(-1)[:, None], -1)[:, 0]
            pres = np.isfinite(e0) & (np.abs(e0) <= 4); ea_ = float(np.median(e0[pres])) if pres.sum() >= max(3, 0.3 * len(idx)) else 0.0   # où la région se tient par rapport au cœur de SA feuille
            e2 = pp - (hh + s + ea_)[:, None]; a2 = np.where(np.isfinite(e2), np.abs(e2), np.inf); r2 = np.take_along_axis(e2, a2.argmin(-1)[:, None], -1)[:, 0]
            a_pic = np.isfinite(e0); trouve = np.isfinite(r2) & (np.abs(r2) <= 3)
            if len(idx) >= 8 and a_pic.sum() >= 4 and trouve.sum() < 0.5 * a_pic.sum(): raisons[r] = "pas_de_feuille"; continue
            if trouve.sum() >= 3: s += float(np.median(r2[trouve]))                                    # recalé sur les pics réels de la feuille d'arrivée
            if np.abs(hh + s).max() > HMAX: raisons[r] = "marge"; continue
            decal[r] = s; raisons.pop(r, None); voisines(r)
        fixe = np.isfinite(decal); fixe[ref] = False; delta = np.where(lab >= 0, np.nan_to_num(decal, nan=0.0)[np.maximum(lab, 0)], 0).astype(np.float32)
        self._dire("Remove steps: blending without steps…", 0.75)
        neuf = self._poser(delta); reste = (lab >= 0) & ~np.isfinite(decal)[np.maximum(lab, 0)]; nr = {k: 0 for k in ("couture", "pas_de_feuille", "marge")}
        for v in raisons.values(): nr[v] += 1
        return self._fin_auto("marches", neuf, t0, pas_sur=reste, greffe=bool(p.get("greffe", False)), seuil=seuil, regions=int(n), reference=int(tailles[ref]), ramenees=int(fixe.sum()), noeuds_ramenes=int(tailles[fixe].sum()),
                              laissees=int(n - 1 - fixe.sum()), noeuds_laisses=int(reste.sum()), raisons=nr, marches_seuil_internes=internes, ancre=p.get("ancre"))

    # ───────────────────────── note de quadrillage des fibres ─────────────────────────
    def _fib_dims(self):
        return (self.H - FN) // FHOP + 1, (self.W - FN) // FHOP + 1

    def _q_prof(self, h, recettes, rect=None, texte=None, part=(0.0, 1.0)):
        """Quadrillage par fenêtre pour plusieurs images de la page prises sur la surface `h` : chaque recette = profondeurs (voxels autour de
        la surface) dont on fait la moyenne. Lu dans le bloc par petites bandes. → (recettes, fenêtres en hauteur, fenêtres en largeur)."""
        ny, nx = self._fib_dims(); i0, i1, j0, j1 = rect or (0, ny, 0, nx); x0, x1 = j0 * FHOP, (j1 - 1) * FHOP + FN; xs = np.arange(x0, x1)
        Q = np.full((len(recettes), i1 - i0, j1 - j0), np.nan, np.float32); offs = sorted({float(o) for r in recettes for o in r}); B = int(np.clip(700_000 // max((x1 - x0) * FHOP, 1), 1, 16))
        for a in range(i0, i1, B):
            b = min(a + B, i1); y0, y1 = a * FHOP, (b - 1) * FHOP + FN; S = np.asarray(self.bloc[y0:y1, x0:x1]); ok = S.max(-1) > 0; hp = interp_noeuds(h, np.arange(y0, y1), xs, self.pas); im = {}
            for o in offs:
                d = np.clip(hp + (o + DEMI), 0, ND - 1.001); i = np.floor(d).astype(np.intp); f = (d - i).astype(np.float32)
                A = np.take_along_axis(S, i[..., None], 2)[..., 0].astype(np.float32); im[o] = A + (np.take_along_axis(S, i[..., None] + 1, 2)[..., 0] - A) * f
            for r, rec in enumerate(recettes):
                g = im[float(rec[0])] if len(rec) == 1 else sum(im[float(o)] for o in rec) / len(rec)
                Q[r, a - i0:b - i0] = q_fibres(np.clip(g + 0.5, 0, 255).astype(np.uint8), ok)
            if texte: self._dire(texte, part[0] + (part[1] - part[0]) * (b - i0) / max(i1 - i0, 1))
        return Q

    def _q_audit(self, h, rect=None, texte=None, part=(0.0, 1.0)):
        """La mesure de l'audit : meilleure de 4 profondeurs (surface = moyenne de −0,5 et +0,5 ; −3 ; −1 ; +1 vx)."""
        return np.max(self._q_prof(h, [(-0.5, 0.5), (-3.0,), (-1.0,), (1.0,)], rect, texte, part), 0)

    def _fib_pret(self):
        """Carte du quadrillage : surface d'origine (calculée une fois, gardée dans base/fibres_origine.npz) et surface actuelle (refaite
        seulement là où la surface a changé depuis)."""
        from scipy import ndimage as ndi
        if self.fib is None:
            f = self.d / "base" / ("fibres_origine.npz" if not self.ext else "fibres_origine_e" + "_".join(str(i) for i in self.ext) + ".npz"); q0 = None; dims = self._fib_dims()
            if f.exists():
                try:
                    z = np.load(f); q0 = z["q"] if z["q"].shape == dims and int(z["version"]) == 1 else None
                except Exception: q0 = None
            if q0 is None:
                q0 = self._q_audit(np.zeros((self.gh, self.gw), np.float32), None, "Fibre score of the original surface (once)…", (0.0, 0.5))
                if not self.rejeu: ecrire_atomique(f, lambda t: np.savez_compressed(open(t, "wb"), q=q0, version=1))
            q5 = lis(q0, 5); fin = np.isfinite(q5); inter = ndi.binary_erosion(fin, iterations=6)
            if inter.sum() < 30: inter = fin
            p5, p95 = (float(x) for x in np.percentile(q5[inter], (5, 95))) if inter.any() else (0.0, 1.0)
            self.fib = dict(q0=q0, q=q0.copy(), p5=p5, p95=max(p95, p5 + 1e-6), inter=inter, sale=np.zeros(q0.shape, bool))
            if self.h.any(): r = np.where(self.h.any(1))[0]; c = np.where(self.h.any(0))[0]; self._fib_salir((r[0], r[-1] + 1, c[0], c[-1] + 1))
        F = self.fib
        if F["sale"].any():
            r = np.where(F["sale"].any(1))[0]; c = np.where(F["sale"].any(0))[0]; rect = (int(r[0]), int(r[-1]) + 1, int(c[0]), int(c[-1]) + 1)
            F["q"][rect[0]:rect[1], rect[2]:rect[3]] = self._q_audit(self.h, rect, "Fibre score of the current surface…", (0.5, 1.0)); F["sale"][:] = False
        return F

    def _fib_salir(self, bbox):
        """La surface a changé dans ce rectangle de nœuds : les fenêtres qui le touchent seront recalculées à la prochaine demande."""
        if self.fib is None: return
        y0, y1, x0, x1 = self._px(bbox); ny, nx = self.fib["sale"].shape
        self.fib["sale"][max(0, (y0 - FN) // FHOP + 1):min(ny, (y1 - 1) // FHOP + 1), max(0, (x0 - FN) // FHOP + 1):min(nx, (x1 - 1) // FHOP + 1)] = True

    def _fib_note(self, q):
        F = self.fib
        return (100 * np.clip((lis(q, 5) - F["p5"]) / (F["p95"] - F["p5"]), 0, 1)).astype(np.float32)

    def _fib_marquees(self):
        """Part de zone marquée dans chaque fenêtre de 32 px (8 nœuds)."""
        from scipy import ndimage as ndi
        ny, nx = self._fib_dims(); m = ndi.uniform_filter((self.zones & self.valide).astype(np.float32), 2 * FHOP // self.pas)
        return m[np.ix_(np.minimum(np.arange(ny) * FHOP // self.pas + FN // 2 // self.pas, self.gh - 1), np.minimum(np.arange(nx) * FHOP // self.pas + FN // 2 // self.pas, self.gw - 1))]

    def _fib_bilan(self, na, nb):
        """Note de quadrillage avant → après : page, zones marquées, reste (moyennes), part des fenêtres qui montent / baissent de plus de 10."""
        F = self.fib; MV = self._fib_marquees(); fin = F["inter"] & np.isfinite(na) & np.isfinite(nb); r = {}
        for nom, m in (("page", fin), ("marquees", fin & (MV > 0.9)), ("reste", fin & (MV < 0.1))):
            k = int(m.sum()); a, b = na[m], nb[m]
            r[nom] = dict(fenetres=k, avant=_stat(a.mean()) if k else None, apres=_stat(b.mean()) if k else None, monte=_stat(100 * (b - a > 10).mean()) if k else None, baisse=_stat(100 * (a - b > 10).mean()) if k else None,
                          monte_un_peu=_stat(100 * (b - a > 2).mean()) if k else None, baisse_un_peu=_stat(100 * (a - b > 2).mean()) if k else None)
        return r

    def fibres_binaire(self):
        """Pour le calque « fibre score » : note 0–100 par fenêtre (surface actuelle et surface d'origine)."""
        from .segment import paquet
        with self.verrou:
            self._dire("Fibre score…", 0.0); F = self._fib_pret(); n0 = self._fib_note(F["q0"]); n1 = self._fib_note(F["q"]); ny, nx = n0.shape; self._dire("done", 1.0)
            return paquet(dict(ny=ny, nx=nx, fenetre=FN, pas=FHOP, gen=self.gen, bilan=self._fib_bilan(n0, n1)), {"maintenant": n1, "origine": n0})

    # ───────────────────────── 4. le meilleur quadrillage de fibres ─────────────────────────
    def _op_fibres(self, p):
        """Pour chaque fenêtre de la page, la profondeur (autour de la surface ACTUELLE, de −N à +N vx par pas de 1) qui donne le quadrillage de
        fibres le plus net ; une fenêtre isolée ne décide pas (mesure moyennée sur 5 fenêtres, puis médiane 5 × 5 du champ) ; champ lissé,
        puis posé sans marche (_adoucir). Une fenêtre ne bouge que si le gain dépasse `gain` points de note."""
        from scipy import ndimage as ndi
        t0 = time.time(); gh, gw = self.gh, self.gw; N = int(np.clip(p.get("portee", 6), 1, 12)); zones = bool(p.get("zones")); F = self._fib_pret(); ny, nx = F["q"].shape; rect = (0, ny, 0, nx)
        champ = (self.zones & self.valide) if zones else self.valide
        if not champ.any(): raise ValueError("no marked area: paint one first (tool M), or untick “only in the marked areas”")
        if zones:
            m = self._fib_marquees() > 0; r = np.where(m.any(1))[0]; c = np.where(m.any(0))[0]
            if not len(r): raise ValueError("the marked areas are too small for the fibre measure (0.3 mm windows)")
            rect = (max(0, int(r[0]) - 4), min(ny, int(r[-1]) + 5), max(0, int(c[0]) - 4), min(nx, int(c[-1]) + 5))
        i0, i1, j0, j1 = rect; ks = np.arange(-N, N + 1, dtype=np.float32)
        Qc = self._q_prof(self.h, [(float(k),) for k in ks], rect, f"Best fibres: trying {2 * N + 1} depths…", (0.05, 0.5))
        Qs = np.stack([lis(q, 5) for q in Qc]); fin = np.isfinite(Qs).all(0); Qf = np.where(fin[None], Qs, -1.0); ib = Qf.argmax(0); prendre = lambda i: np.take_along_axis(Qf, i[None], 0)[0]
        qb = prendre(ib); qa = prendre(np.clip(ib - 1, 0, 2 * N)); qc = prendre(np.clip(ib + 1, 0, 2 * N)); den = qa - 2 * qb + qc; dedans = (ib > 0) & (ib < 2 * N)
        frac = np.where(dedans & (den < -1e-9), np.clip(0.5 * (qa - qc) / np.where(den < -1e-9, den, -1.0), -0.5, 0.5), 0.0)
        mieux = fin & (qb - Qf[N] >= float(np.clip(p.get("gain", 3.0), 0, 50)) / 100 * (F["p95"] - F["p5"])); K = np.where(mieux, ks[ib] + frac, 0).astype(np.float32); au_bord = int((mieux & ~dedans).sum())
        if min(K.shape) >= 5: K = cv2.medianBlur(K, 5)
        m = fin.astype(np.float32); K = cv2.GaussianBlur(K * m, (0, 0), 1.0) / (cv2.GaussianBlur(m, (0, 0), 1.0) + 1e-6)
        vi = (np.arange(gh, dtype=np.float32) * self.pas - FN / 2) / FHOP - i0; ui = (np.arange(gw, dtype=np.float32) * self.pas - FN / 2) / FHOP - j0
        Kn = ndi.map_coordinates(K, np.meshgrid(vi, ui, indexing="ij"), order=1, mode="nearest").astype(np.float32); Kn[~champ] = 0
        self._dire("Best fibres: blending without steps…", 0.52); neuf = self._poser(Kn)
        return self._fin_auto("fibres", neuf, t0, champ=champ, greffe=bool(p.get("greffe", True)), portee=N, zones=zones, fenetres_qui_bougent=int(mieux.sum()), fenetres=int(fin.sum()), a_la_limite=au_bord)
