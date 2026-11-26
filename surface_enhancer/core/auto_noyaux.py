"""RETOUCHEUR DE SURFACE — noyaux compilés (numba) des gestes automatiques (25/11). Chargé seulement quand un bouton « Automatic » sert.

suivre    : suivi d'UNE feuille de proche en proche depuis une ancre, dans le repère « à plat » (hauteur Z = décalage h + G, où G est la
            hauteur de la surface d'origine au-dessus d'une base lisse : une feuille y est lisse même là où la surface d'origine saute).
            File de priorité : le nœud le plus sûr d'abord (bien entouré de nœuds déjà posés, pic net, tout près de la hauteur prédite).
            La hauteur prédite est le plan ajusté sur les nœuds déjà posés à 3 nœuds à la ronde (pente bornée) ; un nœud ne prend un pic que
            s'il est à moins de `saut` voxels de cette prédiction. Sinon il est « pas sûr » : on n'invente pas de feuille, il garde sa forme
            actuelle, recalée en douceur sur ses voisins sûrs.
etiqueter : régions de la surface séparées par des marches (sauts entre voisins au-dessus d'un seuil).
Rien d'aléatoire, un seul fil : le même état et les mêmes paramètres redonnent exactement le même résultat (rejeu du journal)."""
import numba as nb
import numpy as np

DV = (0, 0, 1, -1)
DU = (1, -1, 0, 0)
POIDS = (1.0, 0.8825, 0.7788, 0.6873, 0.6065, 0.5353, 0.4724, 0.4169, 0.3679, 0.3247, 0.2865)       # exp(−d² / 8) : voisinage de l'ajustement (σ = 2 nœuds)
LISSE = (1.0, 0.8007, 0.6412, 0.5134, 0.4111, 0.3292, 0.2636, 0.2111, 0.1690, 0.1353, 0.1084)       # exp(−d² / 4,5) : lissage final (σ = 1,5 nœud)


@nb.njit(cache=True, nogil=True)
def _evaluer(v, u, pos, force, G, Z, etat, age, saut, pont, hlim):
    """Que ferait-on du nœud (v, u) maintenant ? → (coût, hauteur Z, sorte 1 = sur un pic / 2 = pas sûr, âge, conflit 0/1).
    Conflit : les nœuds déjà posés autour ne tiennent pas sur un même plan (deux fronts qui ne sont pas sur la même feuille)."""
    gh, gw, K = pos.shape
    Sw = 0.0; Sx = 0.0; Sy = 0.0; Sxx = 0.0; Sxy = 0.0; Syy = 0.0; Sz = 0.0; Sxz = 0.0; Syz = 0.0; Szz = 0.0; wsur = 0.0; zref = 0.0; vide = True
    for a in range(max(0, v - 3), min(gh, v + 4)):
        for b in range(max(0, u - 3), min(gw, u + 4)):
            e = etat[a, b]
            if e == 0: continue
            dx = a - v; dy = b - u; d2 = dx * dx + dy * dy
            if d2 > 10: continue
            w = POIDS[d2]
            if e == 1: wsur += w
            else: w *= 0.2
            if vide: zref = Z[a, b]; vide = False
            z = Z[a, b] - zref
            Sw += w; Sx += w * dx; Sy += w * dy; Sxx += w * dx * dx; Sxy += w * dx * dy; Syy += w * dy * dy; Sz += w * z; Sxz += w * dx * z; Syz += w * dy * z; Szz += w * z * z
    amin = 1 << 30; ka = -1
    for k in range(4):
        v1 = v + DV[k]; u1 = u + DU[k]
        if v1 < 0 or u1 < 0 or v1 >= gh or u1 >= gw or etat[v1, u1] == 0: continue
        if age[v1, u1] < amin: amin = age[v1, u1]; ka = k
    if ka < 0 or vide: return np.inf, 0.0, 0, 0, 0
    Axx = Sxx + 1.5; Ayy = Syy + 1.5                                    # un peu de retenue sur la pente : avec peu de voisins, on prolonge presque à plat
    det = Sw * (Axx * Ayy - Sxy * Sxy) - Sx * (Sx * Ayy - Sxy * Sy) + Sy * (Sx * Sxy - Axx * Sy)
    if det > 1e-9:
        pb = (Sw * (Sxz * Ayy - Syz * Sxy) - Sz * (Sx * Ayy - Sxy * Sy) + Sy * (Sx * Syz - Sxz * Sy)) / det
        pc = (Sw * (Axx * Syz - Sxy * Sxz) - Sx * (Sx * Syz - Sxz * Sy) + Sz * (Sx * Sxy - Axx * Sy)) / det
        pb = max(-1.5, min(1.5, pb)); pc = max(-1.5, min(1.5, pc))
    else:
        pb = 0.0; pc = 0.0
    pa = (Sz - pb * Sx - pc * Sy) / Sw
    sse = Szz - 2 * pa * Sz - 2 * pb * Sxz - 2 * pc * Syz + pa * pa * Sw + pb * pb * Sxx + pc * pc * Syy + 2 * pa * pb * Sx + 2 * pa * pc * Sy + 2 * pb * pc * Sxy
    rms = np.sqrt(max(sse, 0.0) / Sw); pred = zref + pa; g = G[v, u]
    conflit = 1 if (wsur >= 1.5 and rms > 1.2 * saut + 0.3) else 0
    if amin <= pont and conflit == 0:
        bk = -1; bd = 1e9
        for k in range(K):
            x = pos[v, u, k]
            if x != x or abs(x) > hlim: continue
            d = abs(x + g - pred)
            if d < bd: bd = d; bk = k
        if bk >= 0 and bd <= saut:
            return bd / saut + 0.3 * (1.0 - min(force[v, u, bk] / 0.15, 1.0)) + 0.6 * (1.0 - min(wsur / 6.0, 1.0)), float(pos[v, u, bk]) + g, 1, 0, 0
    return 10.0 + amin + 1, max(-hlim, min(hlim, pred - g)) + g, 2, amin + 1, conflit


@nb.njit(cache=True, nogil=True)
def _monter(hc, hi, i):
    while i > 0:
        p = (i - 1) >> 1
        if hc[i] < hc[p] or (hc[i] == hc[p] and hi[i] < hi[p]):
            a = hc[i]; hc[i] = hc[p]; hc[p] = a; b = hi[i]; hi[i] = hi[p]; hi[p] = b; i = p
        else: break


@nb.njit(cache=True, nogil=True)
def _descendre(hc, hi, n):
    i = 0
    while True:
        g = 2 * i + 1; d = g + 1; m = i
        if g < n and (hc[g] < hc[m] or (hc[g] == hc[m] and hi[g] < hi[m])): m = g
        if d < n and (hc[d] < hc[m] or (hc[d] == hc[m] and hi[d] < hi[m])): m = d
        if m == i: break
        a = hc[i]; hc[i] = hc[m]; hc[m] = a; b = hi[i]; hi[i] = hi[m]; hi[m] = b; i = m


@nb.njit(cache=True, nogil=True)
def _entrer(v0, u0, pos, force, libre, G, Z, etat, age, meil, hc, hi, nh, saut, pont, hlim):
    """Les voisins libres du nœud posé (v0, u0) entrent dans la file (ou y sont réévalués s'ils y étaient mal placés). → file (peut avoir grandi)."""
    gh, gw, K = pos.shape
    for k in range(4):
        v = v0 + DV[k]; u = u0 + DU[k]
        if v < 0 or u < 0 or v >= gh or u >= gw or not libre[v, u] or etat[v, u] != 0 or meil[v, u] <= 1.0: continue
        c, val, so, ag, cf = _evaluer(v, u, pos, force, G, Z, etat, age, saut, pont, hlim)
        if c < meil[v, u] - 1e-6:
            if nh == hc.shape[0]:
                hc2 = np.empty(2 * nh, np.float32); hi2 = np.empty(2 * nh, np.int64); hc2[:nh] = hc; hi2[:nh] = hi; hc = hc2; hi = hi2
            meil[v, u] = c; hc[nh] = c; hi[nh] = v * gw + u; nh += 1; _monter(hc, hi, nh - 1)
    return hc, hi, nh


@nb.njit(cache=True, nogil=True)
def _propager(pos, force, libre, G, Z, etat, age, saut, pont, hlim):
    """Propagation depuis les nœuds déjà posés (état 1) vers les nœuds `libre`, le plus sûr d'abord. Remplit Z, état (1 sur un pic, 2 pas
    sûr) et âge. → nombre de conflits (nœuds où les voisins déjà posés ne tiennent pas sur un même plan)."""
    gh, gw, K = pos.shape; meil = np.full((gh, gw), np.inf, np.float32)
    hc = np.empty(gh * gw + 64, np.float32); hi = np.empty(gh * gw + 64, np.int64); nh = 0; conflits = 0
    for v in range(gh):
        for u in range(gw):
            if etat[v, u] == 1: hc, hi, nh = _entrer(v, u, pos, force, libre, G, Z, etat, age, meil, hc, hi, nh, saut, pont, hlim)
    while nh > 0:
        c = hc[0]; idx = hi[0]; nh -= 1; hc[0] = hc[nh]; hi[0] = hi[nh]; _descendre(hc, hi, nh)
        v = idx // gw; u = idx % gw
        if etat[v, u] != 0 or c > meil[v, u] + 1e-6: continue
        c2, val, so, ag, cf = _evaluer(v, u, pos, force, G, Z, etat, age, saut, pont, hlim)
        if c2 > c + 0.25 and nh > 0 and c2 > hc[0]:                       # moins sûr qu'à son entrée dans la file, et un autre est plus sûr que lui : il attendra
            if nh == hc.shape[0]:
                hc2 = np.empty(2 * nh, np.float32); hi2 = np.empty(2 * nh, np.int64); hc2[:nh] = hc; hi2[:nh] = hi; hc = hc2; hi = hi2
            meil[v, u] = c2; hc[nh] = c2; hi[nh] = idx; nh += 1; _monter(hc, hi, nh - 1); continue
        Z[v, u] = val; etat[v, u] = so; age[v, u] = ag; conflits += cf
        hc, hi, nh = _entrer(v, u, pos, force, libre, G, Z, etat, age, meil, hc, hi, nh, saut, pont, hlim)
    return conflits


@nb.njit(cache=True, nogil=True)
def suivre(pos, force, valide, G, av, au, t0, saut, pont, hlim):
    """Propagation depuis l'ancre. → Z (hauteur suivie, repère à plat ; NaN = pas atteint), état (0 pas atteint, 1 sur un pic, 2 pas sûr),
    nombre de conflits (nœuds où deux fronts ne sont pas d'accord)."""
    gh, gw, K = pos.shape
    Z = np.full((gh, gw), np.nan, np.float32); etat = np.zeros((gh, gw), np.uint8); age = np.zeros((gh, gw), np.int32)
    Z[av, au] = t0 + G[av, au]; etat[av, au] = 1
    conflits = _propager(pos, force, valide, G, Z, etat, age, saut, pont, hlim)
    return Z, etat, conflits


@nb.njit(cache=True, nogil=True)
def suivre_graines(pos, force, libre, G, Z, etat, age, saut, pont, hlim):
    """Comme suivre, mais depuis des nœuds déjà posés (Z, état 1 = sûr ou 2 = pas sûr, et âge donnés : le bord d'un segment), vers les seuls
    nœuds `libre`. Z, état et âge sont complétés sur place. → nombre de conflits."""
    return _propager(pos, force, libre, G, Z, etat, age, saut, pont, hlim)


@nb.njit(cache=True, nogil=True)
def recaler(Z, sur, zone, h, G, bord, seuil, iters):
    """Écart à poser (nouvelle hauteur − hauteur actuelle) : sur les nœuds SÛRS, le pic suivi, lissé sur 1,5 nœud (sans mélanger ce qui est à
    plus de 2,5 vx), à `bord` voxels du cœur ; sur les nœuds pas sûrs de la `zone` (trous et bord de la région suivie), l'écart des sûrs
    prolongé puis lissé (ils gardent leur forme, sauf une marche existante, qui n'est pas recopiée) ; zéro ailleurs. → écart, passes."""
    gh, gw = h.shape; D = np.zeros((gh, gw), np.float32); fait = np.zeros((gh, gw), np.uint8); zh = (h + G).astype(np.float32)
    fv = np.empty(gh * gw, np.int32); fu = np.empty(gh * gw, np.int32); n = 0
    for v in range(gh):
        for u in range(gw):
            if not sur[v, u]: continue
            s = 0.0; w = 0.0; zc = Z[v, u]
            for a in range(max(0, v - 3), min(gh, v + 4)):
                for b in range(max(0, u - 3), min(gw, u + 4)):
                    if not sur[a, b]: continue
                    d2 = (a - v) * (a - v) + (b - u) * (b - u)
                    if d2 > 10 or abs(Z[a, b] - zc) > 2.5: continue
                    s += LISSE[d2] * Z[a, b]; w += LISSE[d2]
            D[v, u] = s / w + bord - zh[v, u]; fait[v, u] = 1; fv[n] = v; fu[n] = u; n += 1
    n0 = n; q = 0
    while q < n:                                                         # de proche en proche depuis les nœuds sûrs, dans la zone
        v = fv[q]; u = fu[q]; q += 1
        for k in range(4):
            v1 = v + DV[k]; u1 = u + DU[k]
            if v1 < 0 or u1 < 0 or v1 >= gh or u1 >= gw or fait[v1, u1] != 0 or not zone[v1, u1]: continue
            cc = zh[v1, u1] - zh[v, u]; x = D[v, u]
            if abs(cc) > seuil: x -= cc
            D[v1, u1] = x; fait[v1, u1] = 2; fv[n] = v1; fu[n] = u1; n += 1
    nit = 0
    for it in range(iters):
        if n == n0: break
        mx = 0.0; nit += 1
        for q0 in range(n0, n):
            q = q0 if it % 2 == 0 else n - 1 - (q0 - n0)
            v = fv[q]; u = fu[q]; s = 0.0; w = 0
            for k in range(4):
                v1 = v + DV[k]; u1 = u + DU[k]
                if v1 < 0 or u1 < 0 or v1 >= gh or u1 >= gw or fait[v1, u1] == 0: continue
                cc = zh[v, u] - zh[v1, u1]; x = D[v1, u1]
                if abs(cc) > seuil: x -= cc
                s += x; w += 1
            if w == 0: continue
            x = D[v, u] + 1.7 * (s / w - D[v, u]); mx = max(mx, abs(x - D[v, u])); D[v, u] = x
        if mx < 0.01: break
    return D, nit


@nb.njit(cache=True, nogil=True)
def etiqueter(valide, cu, cv, seuil):
    """Régions de nœuds reliés sans marche (|saut| ≤ seuil entre voisins). → étiquette par nœud (−1 = pas de surface), nombre de régions."""
    gh, gw = valide.shape; lab = np.full((gh, gw), -1, np.int32); pile = np.empty(gh * gw, np.int64); n = 0
    for v0 in range(gh):
        for u0 in range(gw):
            if not valide[v0, u0] or lab[v0, u0] >= 0: continue
            lab[v0, u0] = n; pile[0] = v0 * gw + u0; m = 1
            while m > 0:
                m -= 1; i = pile[m]; v = i // gw; u = i % gw
                if u + 1 < gw and valide[v, u + 1] and lab[v, u + 1] < 0 and abs(cu[v, u]) <= seuil: lab[v, u + 1] = n; pile[m] = i + 1; m += 1
                if u > 0 and valide[v, u - 1] and lab[v, u - 1] < 0 and abs(cu[v, u - 1]) <= seuil: lab[v, u - 1] = n; pile[m] = i - 1; m += 1
                if v + 1 < gh and valide[v + 1, u] and lab[v + 1, u] < 0 and abs(cv[v, u]) <= seuil: lab[v + 1, u] = n; pile[m] = i + gw; m += 1
                if v > 0 and valide[v - 1, u] and lab[v - 1, u] < 0 and abs(cv[v - 1, u]) <= seuil: lab[v - 1, u] = n; pile[m] = i - gw; m += 1
            n += 1
    return lab, n
