"""RETOUCHEUR DE SURFACE — un segment préparé : état (décalage h par nœud, zones marquées), gestes, annulation, scores, rendus locaux.

Repères : nœud (v, u) = (ligne, colonne) de la grille tifxyz ; pixel de la page = nœud × pas ; d = voxels le long de la normale d'origine.
La surface retouchée est P0 + h · N. La surface d'origine (h = 0) n'est jamais réécrite : seule la copie versionnée (versions/vNNN/) change.
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import threading
import time
import warnings
from pathlib import Path

import cv2
import numpy as np

from .auto import Auto
from .extension import Extension
from .commun import (CARREAU, COUCHES, DEMI, HMAX, ND, NIVEAUX, TUILE, ecrire_atomique, ecrire_json, fondu, interp_noeuds, reduire2, valide_px)


class SegmentError(RuntimeError):
    """The segment cannot be opened (not prepared, preload unfinished…); the message is meant for the user."""

KS = np.arange(-COUCHES, COUCHES + 1)
CRITERES = ["distance to the sheet", "sheet sharpness", "steps", "grid stretch", "close neighbouring sheet"]
POIDS = np.array([0.35, 0.20, 0.25, 0.10, 0.10], np.float32)
CHAMPS = ["note", "dist", "net", "marche", "etir", "cis", "vois", "pire"]
VOISINE_PROCHE = 13.0      # voxels : en dessous, la feuille d'à côté est assez près pour gêner (encre de la voisine, glissement)


def noter(dist, net, marche, etir, cis, vois):
    """Note 0–100 d'un carreau à partir de ses cinq mesures (tableaux). → note, indice du critère qui coûte le plus."""
    s = np.stack([np.clip(1 - (dist - 1.5) / 6.5, 0, 1),                       # ≤ 1,5 vx de la feuille : parfait ; ≥ 8 vx : zéro
                  np.clip(net / 0.15, 0, 1),                                    # relief de la feuille ≥ 15 % du contraste du scan : net
                  np.clip(1 - (marche - 0.5) / 2.5, 0, 1),                      # marches ≤ 0,5 vx : parfait ; ≥ 3 vx : zéro
                  np.clip(1 - np.maximum((etir - 10) / 40, (cis - 8) / 30), 0, 1),   # étirement ≤ 10 % et cisaillement ≤ 8° : parfait
                  np.clip((vois - 6) / (VOISINE_PROCHE - 6), 0, 1)], -1)          # voisine ≥ 13 vx : parfait ; ≤ 6 vx : zéro
    return 100 * (s * POIDS).sum(-1), np.argmax((1 - s) * POIDS, -1).astype(np.float32)


def centile(B, q):
    """Centile q (0–100) le long du dernier axe en ignorant les NaN (tri : bien plus rapide que np.nanpercentile)."""
    T = np.sort(B, -1); n = np.isfinite(B).sum(-1); i = np.clip(np.round(q / 100 * (n - 1)).astype(np.intp), 0, B.shape[-1] - 1)
    return np.where(n > 0, np.take_along_axis(T, i[..., None], -1)[..., 0], np.nan)


def paquet(entete: dict, tableaux: dict) -> bytes:
    """Réponse binaire : longueur de l'en-tête (4 octets), en-tête JSON, puis les tableaux bout à bout (décrits dans l'en-tête)."""
    corps = []; pos = 0; desc = {}
    for nom, a in tableaux.items():
        a = np.ascontiguousarray(a); b = a.tobytes(); desc[nom] = dict(type=str(a.dtype), forme=list(a.shape), debut=pos, octets=len(b)); corps.append(b); pos += len(b)
    e = json.dumps(dict(entete, tableaux=desc), ensure_ascii=False).encode("utf-8")
    return struct.pack("<I", len(e)) + e + b"".join(corps)


def _liste(a, nd=2):
    """Tableau → liste JSON (None à la place des valeurs absentes)."""
    a = np.asarray(a, np.float64).ravel()
    return [None if not np.isfinite(x) else round(float(x), nd) for x in a]


class Segment(Auto, Extension):
    def __init__(self, nom: str, rejeu=False, donnees=None, cache=None):
        self.nom = nom; self.d = Path(donnees) / nom; self.rejeu = rejeu        # rejeu : repart de la surface d'origine, n'écrit rien (replay)
        if not (self.d / "config.json").exists(): raise SegmentError(f"segment “{nom}” is not prepared yet: prepare it first (home page, or: python -m surface_enhancer prepare <surface> <volume> --name {nom})")
        self.cfg = json.loads((self.d / "config.json").read_text(encoding="utf-8"))
        self.cache = Path(cache) if cache is not None and (Path(cache) / "bloc.npy").exists() else Path(self.cfg["cache"])       # the cache folder of the settings first; else where it was when prepared
        self.P0 = np.load(self.d / "base" / "P0.npy"); self.N = np.load(self.d / "base" / "N.npy"); self.valide = np.load(self.d / "base" / "valide.npy")
        self.gh, self.gw = self.valide.shape; self.pas = int(self.cfg["pas"]); self.H, self.W = self.cfg["page"]; self.um = float(self.cfg["um"])
        fait = self.cache / "bloc_fait.npy"
        if not fait.exists() or not np.load(fait).all(): raise SegmentError(f"the preload of “{nom}” is not finished (or its cache folder {self.cache} is gone): run the preparation again, it resumes where it stopped")
        self.bloc = np.load(self.cache / "bloc.npy", mmap_mode="r")
        self.pos = np.load(self.cache / "pics_pos.npy"); self.force = np.load(self.cache / "pics_force.npy")
        self.pyr = {L: np.load(self.cache / f"page_L{L}.npy", mmap_mode="c") for L in range(1, NIVEAUX + 1)}       # « c » : les retouches restent en mémoire, le cache n'est pas réécrit
        self.encre = {c["cle"]: [np.load(self.cache / "encre" / f"{c['cle']}_L{L}.npy", mmap_mode="r") for L in range(NIVEAUX + 1)] for c in self.cfg.get("encre", [])}
        lo, hi = self.cfg.get("lut", [0, 255]); self.lut8 = np.clip((np.arange(256) - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
        self.th, self.tw = -(-self.gh // CARREAU), -(-self.gw // CARREAU)
        self.verrou = threading.RLock(); self.gen = 1; self.enregistre = None; self._patchs = {}
        self._base = dict(P0=self.P0, N=self.N, valide=self.valide, pos=self.pos, force=self.force, bloc=self.bloc, pyr=self.pyr, encre=self.encre)      # 25/11 : la grille d'origine, jamais modifiée (les extensions s'y ajoutent en mémoire)
        self._ouvrir_version()
        if rejeu: self._depart_rejeu()
        else: self._replier_journal()
        self.sc0 = self._scores_tout(np.zeros_like(self.h))
        if self.h.any():
            self.sc = self._scores_tout(self.h); r = np.where(self.h.any(1))[0]; c = np.where(self.h.any(0))[0]; self._maj_page(*self._px((r[0], r[-1] + 1, c[0], c[-1] + 1)))
        else:
            self.sc = {k: v.copy() for k, v in self.sc0.items()}
        if self.ext and not rejeu: self._ext_rendre()
        self._maj_zones_carreaux()

    # ───────────────────────── versions, journal, enregistrement ─────────────────────────
    def _versions(self):
        return sorted(p for p in (self.d / "versions").iterdir() if p.is_dir() and p.name[0] == "v" and p.name[1:].isdigit())

    def _ouvrir_version(self):
        from PIL import Image
        vs = self._versions(); trav = vs[-1]; meta = json.loads((trav / "meta.json").read_text(encoding="utf-8"))
        if meta.get("figee") and not self.rejeu:                # la dernière version est figée : on en ouvre une nouvelle, copie conforme
            trav = self._nouvelle_version(trav); meta = json.loads((trav / "meta.json").read_text(encoding="utf-8"))
        self.version = trav.name; self.dv = trav; self.meta = meta; self._disposer([] if self.rejeu else meta.get("extensions", []))       # 25/11 : grille agrandie par les extensions déjà appliquées
        fh, fz = (trav / "decalage_etendu.npy", trav / "zones_etendu.png") if self.ext else (trav / "decalage.npy", trav / "zones.png")      # 25/11 : segment agrandi : la grille entière est dans les fichiers « _etendu »
        self.h = np.load(fh).astype(np.float32) if fh.exists() else np.zeros((self.gh, self.gw), np.float32)
        self.zones = (np.asarray(Image.open(fz).convert("L")) > 127) if fz.exists() else np.zeros((self.gh, self.gw), bool)
        self.zones = self.zones.copy()

    def _depart_rejeu(self):
        from PIL import Image
        self.h = np.zeros((self.gh, self.gw), np.float32); f = self.d / "base" / "zones_depart.png"
        self.zones = (np.asarray(Image.open(f).convert("L")) > 127).copy() if f.exists() else np.zeros((self.gh, self.gw), bool)
        self.gestes = {}; self.pile = []; self.refaire = []; self.dernier_id = 0; self.n_evt = 0

    def _nouvelle_version(self, depuis: Path) -> Path:
        n = int(depuis.name[1:]) + 1; neuf = depuis.parent / f"v{n:03d}"; neuf.mkdir()
        for f in ("decalage.npy", "zones.png", "decalage_etendu.npy", "zones_etendu.png"):
            if (depuis / f).exists(): shutil.copy2(depuis / f, neuf / f)
        if not (neuf / "decalage.npy").exists(): np.save(neuf / "decalage.npy", np.zeros((self.gh, self.gw), np.float32))
        ecrire_json(neuf / "meta.json", dict(version=neuf.name, figee=False, parent=depuis.name, evenements=getattr(self, "n_evt", 0), creee=time.strftime("%Y-%m-%d %H:%M:%S"),
                                           extensions=json.loads((depuis / "meta.json").read_text(encoding="utf-8")).get("extensions", [])))
        return neuf

    def _replier_journal(self):
        """Relit le journal des gestes : pile d'annulation illimitée, et rattrapage si le serveur s'est arrêté entre le journal et l'enregistrement."""
        self.gestes = {}; self.pile = []; self.refaire = []; self.dernier_id = 0; self.n_evt = 0
        f = self.d / "journal.jsonl"; lignes = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []
        fait = int(self.meta.get("evenements", 0)); rattrape = 0
        for n, e in enumerate(lignes):
            t = e.get("type")
            if t == "geste":
                self.gestes[e["id"]] = e; self.pile.append(e["id"]); self.refaire.clear(); self.dernier_id = max(self.dernier_id, e["id"])
            elif t == "annuler" and e["id"] in self.pile:
                self.pile.remove(e["id"]); self.refaire.append(e["id"])
            elif t == "retablir" and e["id"] in self.refaire:
                self.refaire.remove(e["id"]); self.pile.append(e["id"])
            if n >= fait and t in ("geste", "annuler", "retablir"):
                p = self._patch(e["id"]); v0, v1, u0, u1 = p["bbox"]; rattrape += 1
                if p["champ"] == "grille": self._ext_basculer(e["id"], t != "annuler"); continue              # 25/11 : une extension (la grille change de taille)
                (self.h if p["champ"] == "h" else self.zones)[v0:v1, u0:u1] = p["avant"] if t == "annuler" else p["apres"]
        self.n_evt = len(lignes)
        if rattrape:
            print(f"catch-up: {rattrape} journal gesture(s) replayed onto {self.version}", flush=True); self._enregistrer("h"); self._enregistrer("zones")

    def _patch(self, i):
        if i not in self._patchs:
            z = np.load(self.d / "gestes" / f"g{i:06d}.npz"); self._patchs[i] = dict(bbox=[int(x) for x in z["bbox"]], avant=z["avant"], apres=z["apres"], champ=str(z["champ"]))
            if len(self._patchs) > 400 and not self.rejeu: self._patchs.pop(next(iter(self._patchs)))
        return self._patchs[i]

    def _journal(self, e):
        if self.rejeu: return
        with open(self.d / "journal.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self.n_evt += 1

    def _enregistrer(self, champ):
        from PIL import Image
        if self.rejeu: return
        if self.meta.get("figee"): raise RuntimeError("this version is frozen: nothing is written into it")
        h0, z0 = self._ext_partie_origine()                                    # 25/11 : decalage.npy et zones.png gardent la taille de la grille d'origine (scripts de lecture existants)
        if champ == "h": ecrire_atomique(self.dv / "decalage.npy", lambda t: np.save(open(t, "wb"), h0))
        else: ecrire_atomique(self.dv / "zones.png", lambda t: Image.fromarray(z0.astype(np.uint8) * 255).save(t, format="PNG"))
        if self.ext and champ == "h": ecrire_atomique(self.dv / "decalage_etendu.npy", lambda t: np.save(open(t, "wb"), self.h))
        elif self.ext: ecrire_atomique(self.dv / "zones_etendu.png", lambda t: Image.fromarray(self.zones.astype(np.uint8) * 255).save(t, format="PNG"))
        else: (self.dv / ("decalage_etendu.npy" if champ == "h" else "zones_etendu.png")).unlink(missing_ok=True)
        self.meta.update(evenements=self.n_evt, gestes_appliques=len(self.pile), modifiee=time.strftime("%Y-%m-%d %H:%M:%S"), extensions=[int(i) for i in self.ext]); ecrire_json(self.dv / "meta.json", self.meta)
        self.enregistre = time.strftime("%H:%M:%S")
        if champ == "h" and self.pile and len(self.pile) % 25 == 0:      # copie de secours, comme les pages de tracé
            np.savez_compressed(self.d / "historique" / f"decalage_{time.strftime('%Y%m%d_%H%M%S')}_g{self.pile[-1]:06d}.npz", h=self.h)

    def figer(self):
        """Fige la version de travail (elle ne changera plus) et continue sur la suivante."""
        with self.verrou:
            self._enregistrer("h"); self._enregistrer("zones"); self.meta.update(figee=True, figee_le=time.strftime("%Y-%m-%d %H:%M:%S")); ecrire_json(self.dv / "meta.json", self.meta)
            ancien = self.version; neuf = self._nouvelle_version(self.dv); self._journal(dict(type="version", t=time.strftime("%Y-%m-%d %H:%M:%S"), de=ancien, vers=neuf.name))
            self.version = neuf.name; self.dv = neuf; self.meta = json.loads((neuf / "meta.json").read_text(encoding="utf-8")); self._enregistrer("h")
            return dict(figee=ancien, version=self.version, enregistre=self.enregistre)

    def exporter(self, **options):
        """Export as a NEW tifxyz segment (see surface_enhancer/export.py). Never into the original folder, never over an export."""
        from ..export import export_segment
        with self.verrou:
            return export_segment(self, **options)

    # ───────────────────────── rendus locaux (depuis le bloc, processeur seul) ─────────────────────────
    def _px(self, bbox):
        """Rectangle de nœuds → rectangle de pixels de la page touché (un nœud agit jusqu'à ses voisins)."""
        v0, v1, u0, u1 = bbox
        return max(0, (v0 - 1) * self.pas), min(self.H, v1 * self.pas + 1), max(0, (u0 - 1) * self.pas), min(self.W, u1 * self.pas + 1)

    def page_px(self, y0, y1, x0, x1, ks):
        """La page à plat de la surface RETOUCHÉE dans un rectangle de pixels, aux profondeurs ks. → (ny, nx, len(ks)) en flottants."""
        S = np.asarray(self.bloc[y0:y1, x0:x1]); ks = np.asarray(ks)
        i0, i1 = y0 // self.pas, min((y1 - 1) // self.pas + 2, self.gh); j0, j1 = x0 // self.pas, min((x1 - 1) // self.pas + 2, self.gw)
        if not self.h[i0:i1, j0:j1].any(): return S[:, :, DEMI + ks].astype(np.float32)
        hp = interp_noeuds(self.h, np.arange(y0, y1), np.arange(x0, x1), self.pas)
        d = DEMI + hp[..., None] + ks[None, None, :]; i = np.clip(np.floor(d).astype(np.intp), 0, ND - 2); f = np.clip(d - i, 0, 1).astype(np.float32)
        a = np.take_along_axis(S, i, 2).astype(np.float32); b = np.take_along_axis(S, i + 1, 2)
        return a + (b - a) * f

    def _maj_page(self, y0, y1, x0, x1):
        """Refait les niveaux réduits de la page dans le rectangle touché."""
        if self.rejeu: return
        q = 2 ** NIVEAUX; y0 = (y0 // q) * q; x0 = (x0 // q) * q; y1 = min(self.H, -(-y1 // q) * q); x1 = min(self.W, -(-x1 // q) * q)
        bande = max(q, min(512, 400_000 // max(x1 - x0, 1) // q * q))             # 25/11 : bandes plus basses quand le rectangle est large (geste sur tout le segment) : même résultat, bien moins de mémoire
        for ya in range(y0, y1, bande):
            a = self.page_px(ya, min(ya + bande, y1), x0, x1, KS)
            for L in range(1, NIVEAUX + 1):
                a = reduire2(a); oy, ox = ya >> L, x0 >> L; self.pyr[L][oy:oy + a.shape[0], ox:ox + a.shape[1]] = np.clip(a + 0.5, 0, 255).astype(np.uint8)

    def tuile(self, L, ty, tx, k):
        k = int(np.clip(k, -COUCHES, COUCHES))
        if L == 0:
            y0, x0 = ty * TUILE, tx * TUILE; y1, x1 = min(y0 + TUILE, self.H), min(x0 + TUILE, self.W)
            if y0 >= y1 or x0 >= x1 or y0 < 0 or x0 < 0: return None
            a = np.clip(self.page_px(y0, y1, x0, x1, [k])[..., 0] + 0.5, 0, 255).astype(np.uint8)
        else:
            if L not in self.pyr: return None
            a = np.asarray(self.pyr[L][ty * TUILE:(ty + 1) * TUILE, tx * TUILE:(tx + 1) * TUILE, k + COUCHES])
            if a.size == 0: return None
        return cv2.imencode(".jpg", self.lut8[a], [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()

    def tuile_encre(self, cle, L, ty, tx):
        if cle not in self.encre or not 0 <= L <= NIVEAUX: return None
        a = np.asarray(self.encre[cle][L][ty * TUILE:(ty + 1) * TUILE, tx * TUILE:(tx + 1) * TUILE])
        if a.size == 0: return None
        lo, hi = next(c["seuils"] for c in self.cfg["encre"] if c["cle"] == cle)
        al = np.clip((a.astype(np.float32) - lo) / max(hi - lo, 1), 0, 1) ** 1.5                      # réglage « A2 » : rampe 86e → 99,7e centile, transparence α^1,5
        im = np.empty(a.shape + (4,), np.uint8); im[..., 0] = 26; im[..., 1] = 217; im[..., 2] = 255; im[..., 3] = (al * 255).astype(np.uint8)   # BGRA : jaune (1 ; 0,85 ; 0,1)
        return cv2.imencode(".png", im, [cv2.IMWRITE_PNG_COMPRESSION, 1])[1].tobytes()

    def coupes(self, v, u, w):
        """Deux coupes du bloc par le pixel (v, u) : ↔ le long de la largeur de la page, ↕ le long de la hauteur ; ± w pixels, ± DEMI le long de la normale."""
        v = int(np.clip(v, 0, self.H - 1)); u = int(np.clip(u, 0, self.W - 1)); w = int(np.clip(w, 8, 600)); n = 2 * w + 1
        out = {}; e = dict(v=v, u=u, w=w, demi=DEMI, gen=self.gen)
        for axe in ("u", "v"):
            lim = self.W if axe == "u" else self.H; c = u if axe == "u" else v; s = np.arange(c - w, c + w + 1); ok = (s >= 0) & (s < lim); sc = np.clip(s, 0, lim - 1)
            img = np.zeros((ND, n), np.uint8); a, b = int(sc[ok][0]), int(sc[ok][-1]) + 1
            img[:, ok] = self.lut8[np.asarray(self.bloc[v, a:b] if axe == "u" else self.bloc[a:b, u])].T
            if axe == "u": ligne = interp_noeuds(self.h, [v], sc, self.pas)[0]; val = valide_px(self.valide, np.array([v]), sc, self.pas)[0] & ok
            else: ligne = interp_noeuds(self.h, sc, [u], self.pas)[:, 0]; val = valide_px(self.valide, sc, np.array([u]), self.pas)[:, 0] & ok
            ligne = np.where(val, ligne, np.nan)
            # feuilles repérées le long de la coupe (une colonne de petits points par nœud) : ce que l'aimant vise
            nn = np.arange(-(-(c - w) // self.pas), (c + w) // self.pas + 1); nn = nn[(nn >= 0) & (nn < (self.gw if axe == "u" else self.gh))]
            fixe = int(np.clip(round((v if axe == "u" else u) / self.pas), 0, (self.gh if axe == "u" else self.gw) - 1))
            pp = self.pos[fixe, nn] if axe == "u" else self.pos[nn, fixe]
            pics = [[int(nd_ * self.pas - (c - w)), round(float(x), 1)] for nd_, row in zip(nn, pp) for x in row if np.isfinite(x)]
            out["img_" + axe] = img; e["ligne_" + axe] = _liste(ligne); e["pics_" + axe] = pics
        return paquet(e, out)

    def situer(self, maxi=96):
        """Grille allégée des positions réelles (x, y, z) de la surface retouchée : de quoi la situer dans la vue d'ensemble du rouleau."""
        s = max(1, int(np.ceil(max(self.P0.shape[0], self.P0.shape[1]) / maxi))); val = np.asarray(self.valide[::s, ::s])
        P = (self.P0[::s, ::s] + self.h[::s, ::s, None] * self.N[::s, ::s])[..., ::-1]
        return dict(volume=str(self.cfg.get("volume", "")), pas=int(s * self.pas), n=[int(val.shape[0]), int(val.shape[1])],
                    xyz=[[int(round(float(c))) for c in p] if ok else None for p, ok in zip(P.reshape(-1, 3), val.reshape(-1))])

    def patch3d(self, v, u, r, k, cle=""):
        """Morceau de surface autour du pixel (v, u) pour la vue 3D : positions réelles (x, y, z), texture de la page, feuilles voisines, deux coupes."""
        p = self.pas; i = int(np.clip(round(v / p), 0, self.gh - 1)); j = int(np.clip(round(u / p), 0, self.gw - 1)); r = int(np.clip(r, 16, 160))
        i0, i1, j0, j1 = max(0, i - r), min(self.gh, i + r + 1), max(0, j - r), min(self.gw, j + r + 1)
        h = self.h[i0:i1, j0:j1]; P0 = self.P0[i0:i1, j0:j1]; N = self.N[i0:i1, j0:j1]; val = self.valide[i0:i1, j0:j1]
        surf = (P0 + h[..., None] * N)[..., ::-1]
        tex = self.lut8[np.clip(self.page_px(i0 * p, (i1 - 1) * p + 1, j0 * p, (j1 - 1) * p + 1, [int(np.clip(k, -COUCHES, COUCHES))])[..., 0] + 0.5, 0, 255).astype(np.uint8)]
        enc = np.zeros((1, 1), np.uint8)                          # 24/11 : encre du calque choisi (même rampe que la page 2D), posée en jaune sur le morceau
        if cle in self.encre:
            a_ = np.asarray(self.encre[cle][0][i0 * p:(i1 - 1) * p + 1, j0 * p:(j1 - 1) * p + 1]); lo_, hi_ = next(c["seuils"] for c in self.cfg["encre"] if c["cle"] == cle)
            if a_.shape == tex.shape: enc = (np.clip((a_.astype(np.float32) - lo_) / max(hi_ - lo_, 1), 0, 1) ** 1.5 * 255).astype(np.uint8)
        pos = self.pos[i0:i1, j0:j1]; dd = np.where(np.isfinite(pos), np.abs(pos - h[..., None]), np.inf); ix = dd.argmin(-1)[..., None]
        pp = np.take_along_axis(pos, ix, -1); rel = pos - pp; vois = []
        for signe in (-1, 1):                                    # la feuille juste au-dessus (d plus petit), puis juste en dessous
            c = np.where(np.isfinite(rel) & (rel * signe > 4), rel * signe, np.inf); m = c.min(-1); d = pp[..., 0] + signe * m
            q = (P0 + np.where(np.isfinite(d), d, 0)[..., None] * N)[..., ::-1].astype(np.float32); q[~(np.isfinite(d) & val & (np.abs(d) <= DEMI))] = np.nan; vois.append(q)
        t = {"surface": surf.astype(np.float32), "valide": val.astype(np.uint8), "texture": tex, "encre": enc, "dessus": vois[0], "dessous": vois[1]}
        for axe in ("u", "v"):                                   # rubans des deux coupes : bord haut (d = −DEMI) et bord bas (d = +DEMI), nœud par nœud
            if axe == "u": Pl, Nl = self.P0[i, j0:j1], self.N[i, j0:j1]; img = np.asarray(self.bloc[i * p, j0 * p:(j1 - 1) * p + 1]).T
            else: Pl, Nl = self.P0[i0:i1, j], self.N[i0:i1, j]; img = np.asarray(self.bloc[i0 * p:(i1 - 1) * p + 1, j * p]).T
            t["ruban_" + axe] = np.stack([Pl - DEMI * Nl, Pl + DEMI * Nl], 0)[..., ::-1].astype(np.float32); t["coupe_" + axe] = self.lut8[img]
        return paquet(dict(i0=i0, i1=i1, j0=j0, j1=j1, i=i, j=j, pas=p, miroir=self.cfg.get("miroir", False), gen=self.gen, um=self.um), t)

    def segment3d(self, v, u, k, cle="", nmax=400):
        """25/11 : TOUT le segment pour la vue 3D. Maillage allégé (un nœud sur `saut`, au plus nmax × nmax), texture prise dans un niveau
        réduit de la page retouchée, encre du calque choisi au même niveau, les deux coupes par le point sur toute la longueur. Mêmes tableaux
        que patch3d ; l'en-tête dit à la vue combien de pixels de texture et de page vaut un pas du maillage."""
        p = self.pas; nmax = int(np.clip(nmax, 60, 700)); s = max(1, -(-max(self.gh, self.gw) // nmax)); k = int(np.clip(k, -COUCHES, COUCHES))
        i = int(np.clip(round(v / p / s), 0, (self.gh - 1) // s)); j = int(np.clip(round(u / p / s), 0, (self.gw - 1) // s)); iv, ju = i * s, j * s
        val = self.valide[::s, ::s]; nv, nu = val.shape; surf = (self.P0[::s, ::s] + self.h[::s, ::s, None] * self.N[::s, ::s])[..., ::-1]
        L = next((l for l in range(1, NIVEAUX + 1) if max(self.pyr[l].shape[:2]) <= 4096 and self.pyr[l].shape[0] * self.pyr[l].shape[1] <= 3_000_000), NIVEAUX)
        tex = self.lut8[np.asarray(self.pyr[L][:, :, k + COUCHES])]; enc = np.zeros((1, 1), np.uint8)
        if cle in self.encre:
            a_ = np.asarray(self.encre[cle][L]); lo_, hi_ = next(c["seuils"] for c in self.cfg["encre"] if c["cle"] == cle)
            if a_.shape == tex.shape: enc = (np.clip((a_.astype(np.float32) - lo_) / max(hi_ - lo_, 1), 0, 1) ** 1.5 * 255).astype(np.uint8)
        t = {"surface": surf.astype(np.float32), "valide": val.astype(np.uint8), "texture": tex, "encre": enc, "dessus": np.zeros((1, 1, 3), np.float32), "dessous": np.zeros((1, 1, 3), np.float32)}; pr = []
        for axe in ("u", "v"):                                   # rubans des deux coupes, sur toute la longueur ; image allégée si elle dépasse 4 096 px
            if axe == "u": Pl, Nl = self.P0[iv], self.N[iv]; img = np.asarray(self.bloc[iv * p]).T
            else: Pl, Nl = self.P0[:, ju], self.N[:, ju]; img = np.asarray(self.bloc[:, ju * p]).T
            f = max(1, -(-img.shape[1] // 4096)); pr.append(p / f)
            t["ruban_" + axe] = np.stack([Pl - DEMI * Nl, Pl + DEMI * Nl], 0)[..., ::-1].astype(np.float32); t["coupe_" + axe] = self.lut8[img[:, ::f]]
        return paquet(dict(i0=0, i1=nv, j0=0, j1=nu, i=i, j=j, pas=p, tout=True, saut=s, niveau=L, pas_tex=s * p / 2 ** L, dec_tex=0.5 / 2 ** L, pas_page=s * p, pas_ruban=pr, ruban_fixe=[iv, ju],
                           miroir=self.cfg.get("miroir", False), gen=self.gen, um=self.um), t)

    # ───────────────────────── géométrie et scores ─────────────────────────
    def _aretes(self, v0, v1, u0, u1, h=None):
        """Sur un rectangle de nœuds : marche signée (saut le long de la normale) et longueur de chaque arête ↔ (vers u + 1) et ↕ (vers v + 1).
        Tableaux de la taille du rectangle ; NaN là où l'arête n'existe pas (bord, nœud invalide)."""
        h = self.h if h is None else h; ve, ue = min(v1 + 1, self.gh), min(u1 + 1, self.gw); nv, nu = v1 - v0, u1 - u0
        Pc = self.P0[v0:ve, u0:ue] + h[v0:ve, u0:ue, None] * self.N[v0:ve, u0:ue]; Nn = self.N[v0:ve, u0:ue]; val = self.valide[v0:ve, u0:ue]
        r = {}
        for nom, (a, b) in dict(u=((slice(0, nv), slice(0, ue - u0 - 1)), (slice(0, nv), slice(1, ue - u0))), v=((slice(0, ve - v0 - 1), slice(0, nu)), (slice(1, ve - v0), slice(0, nu)))).items():
            d = Pc[b] - Pc[a]; nm = Nn[a] + Nn[b]; nm = nm / (np.linalg.norm(nm, axis=-1, keepdims=True) + 1e-9); ok = val[a] & val[b]
            c = np.full((nv, nu), np.nan, np.float32); L = np.full((nv, nu), np.nan, np.float32); dd = np.full((nv, nu, 3), np.nan, np.float32)
            s = (slice(0, d.shape[0]), slice(0, d.shape[1]))
            c[s] = np.where(ok, (d * nm).sum(-1), np.nan); L[s] = np.where(ok, np.linalg.norm(d, axis=-1), np.nan); dd[s] = np.where(ok[..., None], d, np.nan)
            r["c" + nom] = c; r["L" + nom] = L; r["d" + nom] = dd
        return r

    def _scores_noeuds(self, v0, v1, u0, u1, h=None):
        h = self.h if h is None else h; A = self._aretes(v0, v1, u0, u1, h); val = self.valide[v0:v1, u0:u1]; hh = h[v0:v1, u0:u1]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            marche = np.fmax(np.abs(A["cu"]), np.abs(A["cv"])); etir = np.fmax(np.abs(A["Lu"] / self.pas - 1), np.abs(A["Lv"] / self.pas - 1)) * 100
            cis = np.degrees(np.arcsin(np.clip(np.abs((A["du"] * A["dv"]).sum(-1) / (A["Lu"] * A["Lv"] + 1e-9)), 0, 1)))
        pos = self.pos[v0:v1, u0:u1]; fin = np.isfinite(pos); dd = np.where(fin, np.abs(pos - hh[..., None]), np.inf); ix = dd.argmin(-1)[..., None]
        dist = np.take_along_axis(dd, ix, -1)[..., 0]; aucun = ~np.isfinite(dist); dist = np.where(aucun, 20.0, dist)        # aucune feuille repérée : compté comme 20 vx
        fo = self.force[v0:v1, u0:u1]; fp = np.take_along_axis(fo, ix, -1); net = np.where(aucun, 0, fp[..., 0])
        pp = np.take_along_axis(pos, ix, -1); autres = np.where(fin & (fo >= 0.5 * fp), np.abs(pos - pp), np.inf); np.put_along_axis(autres, ix, np.inf, -1)   # voisine = une feuille au moins moitié aussi nette
        vois = np.minimum(autres.min(-1), 40.0)                                                                             # pas de voisine dans le bloc : 40 vx
        r = dict(dist=dist, net=net, marche=marche, etir=etir, cis=cis, vois=vois)
        for k in r: r[k] = np.where(val, r[k], np.nan).astype(np.float32)
        return r

    def _scores_rect(self, t0, t1, s0, s1, h=None):
        """Scores des carreaux [t0, t1) × [s0, s1). → dictionnaire de tableaux (t1 − t0, s1 − s0) ; NaN = carreau sans surface."""
        C = CARREAU; v0, v1, u0, u1 = t0 * C, min(t1 * C, self.gh), s0 * C, min(s1 * C, self.gw); n = self._scores_noeuds(v0, v1, u0, u1, h); nt, ns = t1 - t0, s1 - s0

        def blocs(a):
            b = np.full((nt * C, ns * C), np.nan, np.float32); b[:a.shape[0], :a.shape[1]] = a
            return b.reshape(nt, C, ns, C).transpose(0, 2, 1, 3).reshape(nt, ns, C * C)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            B = {k: blocs(a) for k, a in n.items()}; plein = np.isfinite(B["dist"]).sum(-1) >= C * C // 4
            r = dict(dist=np.nanmedian(B["dist"], -1), net=np.nanmedian(B["net"], -1), marche=centile(B["marche"], 90), etir=np.nanmean(B["etir"], -1),
                     cis=np.nanmean(B["cis"], -1), vois=np.nanmedian(B["vois"], -1))
        for k in r: r[k] = np.where(plein, np.nan_to_num(r[k], nan=0.0), np.nan).astype(np.float32)
        note, pire = noter(r["dist"], r["net"], r["marche"], r["etir"], r["cis"], r["vois"]); r["note"] = np.where(plein, note, np.nan).astype(np.float32); r["pire"] = np.where(plein, pire, np.nan).astype(np.float32)
        return r

    def _scores_tout(self, h):
        sc = {k: np.full((self.th, self.tw), np.nan, np.float32) for k in CHAMPS}
        for t0 in range(0, self.th, 24):
            r = self._scores_rect(t0, min(t0 + 24, self.th), 0, self.tw, h)
            for k in CHAMPS: sc[k][t0:t0 + 24] = r[k]
        return sc

    def _maj_zones_carreaux(self):
        C = CARREAU; z = np.zeros((self.th * C, self.tw * C), np.float32); z[:self.gh, :self.gw] = self.zones & self.valide
        v = np.zeros_like(z); v[:self.gh, :self.gw] = self.valide
        zs = z.reshape(self.th, C, self.tw, C).sum((1, 3)); vs = v.reshape(self.th, C, self.tw, C).sum((1, 3)); self.zc = zs >= 0.5 * np.maximum(vs, 1)

    def bilan(self):
        """Notes globales : page entière, zones marquées, reste de la page — maintenant et à l'origine."""
        n, n0 = self.sc["note"], self.sc0["note"]; ok = np.isfinite(n); r = {}
        for nom, m in (("page", ok), ("marquees", ok & self.zc), ("reste", ok & ~self.zc)):
            k = int(m.sum()); r[nom] = dict(carreaux=k, note=round(float(n[m].mean()), 2) if k else None, note0=round(float(n0[m].mean()), 2) if k else None,
                                            mauvais=int((n[m] < 40).sum()), mauvais0=int((n0[m] < 40).sum()),
                                            detail={c: round(float(np.nanmean(self.sc[c][m])), 2) if k else None for c in CHAMPS[1:7]},
                                            detail0={c: round(float(np.nanmean(self.sc0[c][m])), 2) if k else None for c in CHAMPS[1:7]})
        r["proche"] = dict(maintenant=int((self.sc["vois"][ok] < VOISINE_PROCHE).sum()), origine=int((self.sc0["vois"][ok] < VOISINE_PROCHE).sum()))
        return r

    def scores_binaire(self):
        return paquet(dict(th=self.th, tw=self.tw, carreau=CARREAU, champs=CHAMPS, criteres=CRITERES, gen=self.gen, bilan=self.bilan()),
                      {"maintenant": np.stack([self.sc[k] for k in CHAMPS]), "origine": np.stack([self.sc0[k] for k in CHAMPS]), "marquees": self.zc.astype(np.uint8)})

    def pires(self, n=50, marquees=False):
        """Carreaux les plus mal notés (du pire au moins pire) ; `marquees` : seulement dans les zones marquées."""
        a = self.sc["note"].copy(); a[~np.isfinite(a)] = 1e9
        if marquees: a[~self.zc] = 1e9
        o = np.argsort(a, axis=None)[:n]
        return [dict(t=int(i // self.tw), s=int(i % self.tw), note=round(float(a.flat[i]), 1)) for i in o if a.flat[i] < 1e8]

    # ───────────────────────── gestes ─────────────────────────
    def _empreinte(self, points, rayon):
        """Rectangle de nœuds autour d'un trait (liste de [v, u]) et distance de chaque nœud au trait, en nœuds."""
        pts = np.asarray(points, np.float32).reshape(-1, 2); r = float(rayon)
        v0 = int(max(0, np.floor(pts[:, 0].min() - r - 1))); v1 = int(min(self.gh, np.ceil(pts[:, 0].max() + r + 2)))
        u0 = int(max(0, np.floor(pts[:, 1].min() - r - 1))); u1 = int(min(self.gw, np.ceil(pts[:, 1].max() + r + 2)))
        if v1 <= v0 or u1 <= u0: return None
        if len(pts) == 1:
            vv, uu = np.mgrid[v0:v1, u0:u1]; return (v0, v1, u0, u1), np.hypot(vv - pts[0, 0], uu - pts[0, 1]).astype(np.float32)
        m = np.full((v1 - v0, u1 - u0), 255, np.uint8); q = np.round((pts - [v0, u0]) * 16).astype(np.int32)[:, ::-1]
        cv2.polylines(m, [q.reshape(-1, 1, 2)], False, 0, 1, cv2.LINE_8, 4)
        return (v0, v1, u0, u1), cv2.distanceTransform(m, cv2.DIST_L2, 5)

    def _adoucir(self, bbox, delta, saut=1.0):
        """Pose un décalage voulu sans jamais créer de marche : entre deux nœuds voisins, le saut de la SURFACE (le long de la normale) reste
        ≤ 1 vx, ou ne dépasse pas ce qu'il était déjà. Le fondu s'élargit tout seul ; une marche existante peut être effacée d'un coup.
        La retouche reste locale (rien ne bouge au bord du rectangle élargi) et dans la marge de ± HMAX voxels : si l'une de ces deux limites
        gêne, c'est le déplacement demandé qui est réduit, jamais la règle des marches. → (rectangle élargi, nouvelles valeurs de h).
        `saut` : saut permis entre deux nœuds voisins (1 vx par défaut). La ligne tirée à la main dans une coupe en demande davantage (26/11) :
        avec 1 vx par nœud la pente est plafonnée (14° pour un nœud tous les 4 vx) et la surface ne passait pas par les points posés."""
        m = int(np.ceil(np.abs(delta).max())) + 3; v0, v1, u0, u1 = bbox
        V0, V1, U0, U1 = max(0, v0 - m), min(self.gh, v1 + m), max(0, u0 - m), min(self.gw, u1 + m)
        D = np.zeros((V1 - V0, U1 - U0), np.float32); D[v0 - V0:v1 - V0, u0 - U0:u1 - U0] = delta; val = self.valide[V0:V1, U0:U1]; D[~val] = 0
        anneau = np.zeros(D.shape, bool)                                 # bord du rectangle élargi, sauf là où c'est le bord de la grille
        if V0 > 0: anneau[0] = True
        if V1 < self.gh: anneau[-1] = True
        if U0 > 0: anneau[:, 0] = True
        if U1 < self.gw: anneau[:, -1] = True
        G = 1e6; H = self.h.copy(); loc = H[V0:V1, U0:U1]                 # loc : vue sur la copie, mise à jour lobe après lobe

        def bornes(c):                                                   # écart permis entre deux voisins : le saut final reste dans ± max(1, |saut actuel|)
            a = np.maximum(saut, np.abs(c)); return np.where(np.isfinite(c), -a - c, -G).astype(np.float32), np.where(np.isfinite(c), a - c, G).astype(np.float32)

        def balayer(g, lo_u, up_u, lo_v, up_v, haut):
            """haut : plus petite fonction ≥ g qui respecte les bornes ; sinon : plus grande fonction ≤ g qui les respecte."""
            op = np.maximum if haut else np.minimum
            for _ in range(400):
                g0 = g.copy()
                for j in range(g.shape[1] - 1): op(g[:, j + 1], g[:, j] + (lo_u[:, j] if haut else up_u[:, j]), out=g[:, j + 1])
                for j in range(g.shape[1] - 2, -1, -1): op(g[:, j], g[:, j + 1] - (up_u[:, j] if haut else lo_u[:, j]), out=g[:, j])
                for i in range(g.shape[0] - 1): op(g[i + 1], g[i] + (lo_v[i] if haut else up_v[i]), out=g[i + 1])
                for i in range(g.shape[0] - 2, -1, -1): op(g[i], g[i + 1] - (up_v[i] if haut else lo_v[i]), out=g[i])
                if np.array_equal(g, g0): break
            return g
        for signe in (1, -1):                                            # la partie qui monte, puis la partie qui descend (chacune sur la surface laissée par l'autre)
            f = np.maximum(signe * D, 0)
            if not f.any(): continue
            A = self._aretes(V0, V1, U0, U1, H); lo_u, up_u = bornes(signe * A["cu"][:, :-1]); lo_v, up_v = bornes(signe * A["cv"][:-1])
            g = balayer(f.copy(), lo_u, up_u, lo_v, up_v, True)
            plafond = np.where(anneau | ~val, 0, np.maximum(HMAX - signe * loc, 0)).astype(np.float32)
            if (g > plafond).any(): g = balayer(np.minimum(g, plafond), lo_u, up_u, lo_v, up_v, False)
            g[~val] = 0; loc += signe * g
        return (V0, V1, U0, U1), loc.copy()

    def _op_ligne(self, p):
        """Tirer la ligne de surface dans une coupe : la surface passe par les points de contrôle (courbe lissée), et la correction s'étend de
        part et d'autre de la coupe sur la portée choisie."""
        from scipy.interpolate import PchipInterpolator
        axe = p["axe"]; fixe = float(p["fixe"]); R = max(float(p["rayon"]), 1.0); B = self.h if axe == "u" else self.h.T; nr, ns = B.shape
        pts = sorted((float(s), float(d)) for s, d in p["points"]); pts = [q for i, q in enumerate(pts) if i == 0 or q[0] - pts[i - 1][0] > 0.05]
        if not pts: return None
        r0 = int(np.clip(np.floor(fixe), 0, nr - 2)); f = float(np.clip(fixe - r0, 0, 1)); ligne = B[r0] * (1 - f) + B[r0 + 1] * f
        sp = np.array([q[0] for q in pts]); dl = np.clip(np.array([q[1] for q in pts]), -HMAX, HMAX) - np.interp(sp, np.arange(ns), ligne)
        xs = np.concatenate([[sp[0] - R], sp, [sp[-1] + R]]); ys = np.concatenate([[0.0], dl, [0.0]])
        c0, c1 = int(max(0, np.ceil(xs[0]))), int(min(ns, np.floor(xs[-1]) + 1)); l0, l1 = int(max(0, np.ceil(fixe - R))), int(min(nr, np.floor(fixe + R) + 1))
        if c1 <= c0 or l1 <= l0: return None
        dline = PchipInterpolator(xs, ys)(np.arange(c0, c1))
        if p.get("lisser"):                                   # 26/11 : un point vient d'être retiré — entre ses deux voisins, la ligne se relâche sur la courbe lisse
            a, b = sorted(float(x) for x in p["lisser"][:2]); cols = np.arange(c0, c1)      # qui passe par les points restants (au lieu de garder la bosse du point retiré)
            absolu = np.clip(np.array([q[1] for q in pts]), -HMAX, HMAX); bouts = np.interp([xs[0], xs[-1]], np.arange(ns), ligne)
            cible = PchipInterpolator(xs, np.concatenate([[bouts[0]], absolu, [bouts[1]]]))(cols)
            dline = np.where((cols >= a) & (cols <= b), cible - ligne[c0:c1], 0.0)
        w = fondu(np.abs(np.arange(l0, l1) - fixe) / R); delta = (w[:, None] * dline[None, :]).astype(np.float32)
        saut = float(np.clip(p.get("saut", 1.0), 1.0, 16.0))            # absent des gestes d'avant le 26/11 : ils se rejouent à l'identique avec 1 vx
        return self._adoucir((l0, l1, c0, c1), delta, saut) if axe == "u" else self._adoucir((c0, c1, l0, l1), delta.T, saut)

    def _cible_aimant(self, bbox, borne, h=None, bord=0.0):
        """Écart (en voxels) qui amène chaque nœud du rectangle sur la feuille la plus proche, SANS casser la surface : on prend d'abord l'avis du
        voisinage (médiane des écarts vers le pic le plus proche, à moins de `borne`), puis chaque nœud vise le pic le plus proche de cet avis, et le
        tout est lissé sur 2 nœuds. Un nœud isolé qui viserait la feuille d'à côté ne décide pas ; là où aucune feuille n'est repérée, on suit les voisins."""
        v0, v1, u0, u1 = bbox; h = self.h if h is None else h; pos = self.pos[v0:v1, u0:u1]; hh = h[v0:v1, u0:u1]; val = self.valide[v0:v1, u0:u1]
        e = pos - hh[..., None]; a = np.where(np.isfinite(e), np.abs(e), np.inf); t = np.take_along_axis(e, a.argmin(-1)[..., None], -1)[..., 0]
        ok = np.isfinite(t) & (np.abs(t) <= borne) & val; avis = np.where(ok, t, 0).astype(np.float32)
        if min(avis.shape) >= 5: avis = cv2.medianBlur(cv2.medianBlur(avis, 5), 5)
        e2 = pos - (hh + avis)[..., None]; a2 = np.where(np.isfinite(e2), np.abs(e2), np.inf); r = np.take_along_axis(e2, a2.argmin(-1)[..., None], -1)[..., 0]
        t1 = np.where(np.isfinite(r) & (np.abs(r) <= 3) & (np.abs(avis + r) <= borne), avis + r, avis).astype(np.float32); m = val.astype(np.float32)
        if bord: t1 = np.where(ok | (np.isfinite(r) & (np.abs(r) <= 3)), t1 + bord, t1).astype(np.float32)      # 25/11 « edge magnet » : à `bord` voxels du cœur, seulement là où une feuille est repérée
        return np.where(val, cv2.GaussianBlur(t1 * m, (0, 0), 2.0) / (cv2.GaussianBlur(m, (0, 0), 2.0) + 1e-6), 0).astype(np.float32)

    def _op_aimant(self, p):
        """Aimant : colle la surface à la feuille la plus proche (pic du profil le long de la normale), sans aller plus loin que ± borne."""
        e = self._empreinte(p["points"], p["rayon"])
        if e is None: return None
        bbox, dist = e; R = max(float(p["rayon"]), 1.0); t = self._cible_aimant(bbox, float(p.get("borne", 6)), bord=float(np.clip(p.get("bord", 0.0), -8, 8)))
        w = fondu(np.clip((dist / R - 0.6) / 0.4, 0, 1))                           # plein effet jusqu'à 60 % du rayon, puis fondu
        return self._adoucir(bbox, (t * w).astype(np.float32))

    def _op_pousser(self, p):
        """Pinceau : ± 1 vx par passage, en fondu autour du trait."""
        e = self._empreinte(p["points"], p["rayon"])
        if e is None: return None
        bbox, dist = e
        return self._adoucir(bbox, (float(np.sign(p.get("signe", 1))) * float(p.get("pas", 1.0)) * fondu(dist / max(float(p["rayon"]), 1.0))).astype(np.float32))

    def _region(self, traits):
        """Région peinte (réunion de traits de pinceau) → rectangle de nœuds et masque."""
        es = [self._empreinte(t["points"], t["rayon"]) for t in traits]; es = [(e, t) for e, t in zip(es, traits) if e is not None]
        if not es: return None
        v0 = min(e[0][0] for e, _ in es); v1 = max(e[0][1] for e, _ in es); u0 = min(e[0][2] for e, _ in es); u1 = max(e[0][3] for e, _ in es); m = np.zeros((v1 - v0, u1 - u0), bool)
        for (b, dist), t in es:
            a = dist <= float(t["rayon"])
            if t.get("gomme"): m[b[0] - v0:b[1] - v0, b[2] - u0:b[3] - u0] &= ~a
            else: m[b[0] - v0:b[1] - v0, b[2] - u0:b[3] - u0] |= a
        return (v0, v1, u0, u1), m & self.valide[v0:v1, u0:u1]

    def _op_feuille(self, p):
        """Décaler d'une feuille la région peinte : toute la région saute de l'écart médian vers la feuille voisine (au-dessus si sens = −1,
        en dessous si sens = +1), puis se recolle à cette feuille ; le bord se raccorde sans marche."""
        r = self._region(p["traits"])
        if r is None or not r[1].any(): return None
        bbox, m = r; v0, v1, u0, u1 = bbox; sens = 1 if float(p.get("sens", 1)) > 0 else -1; pos = self.pos[v0:v1, u0:u1]; hh = self.h[v0:v1, u0:u1]
        a = np.where(np.isfinite(pos), np.abs(pos - hh[..., None]), np.inf); ix = a.argmin(-1)[..., None]; pp = np.take_along_axis(pos, ix, -1); rel = (pos - pp) * sens
        saut = np.where(np.isfinite(rel) & (rel > 4), rel, np.inf).min(-1); ok = m & np.isfinite(saut)
        if ok.sum() < max(4, 0.15 * m.sum()): raise ValueError("no neighbouring sheet detected on that side in this region (within ± 40 vx)")
        s = float(np.median(saut[ok])) * sens
        if np.abs(hh[m] + s).max() > HMAX: raise ValueError(f"this jump ({s:+.0f} vx) goes beyond the ± {HMAX} vx margin: export, then prepare the segment again to go further")
        bb, neuf = self._adoucir(bbox, np.where(m, s, 0).astype(np.float32))
        if p.get("recoller", True):                               # recollage fin à la feuille d'arrivée, dans la région seulement
            V0, V1, U0, U1 = bb; M = np.zeros(neuf.shape, bool); M[v0 - V0:v1 - V0, u0 - U0:u1 - U0] = m; H2 = self.h.copy(); H2[V0:V1, U0:U1] = neuf
            t = np.where(M, self._cible_aimant(bb, 4.0, H2), 0).astype(np.float32)
            anc = self.h[V0:V1, U0:U1].copy(); self.h[V0:V1, U0:U1] = neuf
            try: bb2, neuf2 = self._adoucir(bb, t)
            finally: self.h[V0:V1, U0:U1] = anc
            return bb2, neuf2                                   # neuf2 contient déjà le saut (calculé sur la surface décalée)
        return bb, neuf

    def _op_marquer(self, p):
        e = self._empreinte(p["points"], p["rayon"])
        if e is None: return None
        (v0, v1, u0, u1), dist = e; a = self.zones[v0:v1, u0:u1].copy(); a[dist <= float(p["rayon"])] = bool(p.get("valeur", 1))
        return (v0, v1, u0, u1), a & self.valide[v0:v1, u0:u1]

    OPS = dict(ligne="_op_ligne", aimant="_op_aimant", bord="_op_aimant", pousser="_op_pousser", feuille="_op_feuille", marquer="_op_marquer",
               suivre="_op_suivre", aimant_partout="_op_aimant_partout", marches="_op_marches", fibres="_op_fibres")      # 25/11 : gestes automatiques (auto.py)

    def _note_rect(self, bbox):
        t0, t1, s0, s1 = self._carreaux(bbox); a = self.sc["note"][t0:t1, s0:s1]
        return round(float(np.nanmean(a)), 2) if np.isfinite(a).any() else None

    def _carreaux(self, bbox):
        v0, v1, u0, u1 = bbox; C = CARREAU
        return max(0, (v0 - 1) // C), min(self.th, -(-(v1 + 1) // C)), max(0, (u0 - 1) // C), min(self.tw, -(-(u1 + 1) // C))

    def _apres(self, champ, bbox):
        """Après un changement dans un rectangle de nœuds : page et scores refaits sur place. → ce que la page web doit rafraîchir."""
        info = dict(champ=champ, bbox=[int(x) for x in bbox])
        if champ == "h":
            px = self._px(bbox); self._maj_page(*px); t0, t1, s0, s1 = self._carreaux(bbox); r = self._scores_bandes(t0, t1, s0, s1); self._fib_salir(bbox)
            for k in CHAMPS: self.sc[k][t0:t1, s0:s1] = r[k]
            self.gen += 1; info.update(px=[int(x) for x in px], carreaux=dict(t0=t0, t1=t1, s0=s0, s1=s1, **{k: _liste(r[k]) for k in CHAMPS}, origine=_liste(self.sc0["note"][t0:t1, s0:s1])))
        else:
            self._maj_zones_carreaux(); v0, v1, u0, u1 = bbox; t0, t1, s0, s1 = self._carreaux(bbox)
            info["zones"] = dict(bbox=info["bbox"], masque=self.zones[v0:v1, u0:u1].astype(np.uint8).ravel().tolist(), t0=t0, t1=t1, s0=s0, s1=s1, marquees=self.zc[t0:t1, s0:s1].astype(np.uint8).ravel().tolist())
        info.update(gen=self.gen, bilan=self.bilan(), pile=len(self.pile), refaire=len(self.refaire), enregistre=self.enregistre, version=self.version)
        return info

    def geste(self, outil, p, ident=None):
        if outil not in self.OPS: raise ValueError(f"unknown tool: {outil}")
        with self.verrou:
            t0 = time.time(); champ = "zones" if outil == "marquer" else "h"; ap = self._apercu; self._apercu = None; self._auto = None
            if ap and ap["cle"] == self._cle_apercu(outil, p): r = ap["r"]; self._auto = ap["auto"]            # 25/11 : « Apply » après un aperçu : le résultat déjà calculé (même surface, mêmes paramètres)
            else: r = getattr(self, self.OPS[outil])(p)
            auto = self._auto or {}; self._auto = None
            if r is None: return dict(rien=True, message="nothing to change here")
            (v0, v1, u0, u1), apres = r; arr = self.h if champ == "h" else self.zones; avant = arr[v0:v1, u0:u1].copy()
            if champ == "h": apres = np.where(self.valide[v0:v1, u0:u1], np.clip(apres, -HMAX, HMAX), avant).astype(np.float32)
            dif = (np.abs(apres - avant) > 1e-4) if champ == "h" else (apres != avant)
            if not dif.any(): return dict(rien=True, message="nothing to change here (the surface is already there, or no sheet detected within reach)")
            rr = np.where(dif.any(1))[0]; cc = np.where(dif.any(0))[0]; a0, a1, b0, b1 = rr[0], rr[-1] + 1, cc[0], cc[-1] + 1
            avant, apres = avant[a0:a1, b0:b1], apres[a0:a1, b0:b1]; bbox = [int(v0 + a0), int(v0 + a1), int(u0 + b0), int(u0 + b1)]
            self.dernier_id = ident if ident is not None else self.dernier_id + 1; i = self.dernier_id
            if not self.rejeu: np.savez_compressed(self.d / "gestes" / f"g{i:06d}.npz", bbox=np.array(bbox), avant=avant, apres=apres, champ=champ)
            self._patchs[i] = dict(bbox=bbox, avant=avant, apres=apres, champ=champ)
            note_avant = self._note_rect(bbox); arr[bbox[0]:bbox[1], bbox[2]:bbox[3]] = apres
            e = dict(type="geste", id=i, t=time.strftime("%Y-%m-%d %H:%M:%S"), outil=outil, params=p, champ=champ, bbox=bbox, version=self.version)
            self.gestes[i] = e; self.pile.append(i); self.refaire.clear(); info = self._apres(champ, bbox)
            e["note_zone"] = [note_avant, self._note_rect(bbox)]
            if auto.get("bilan"): e["auto"] = auto["bilan"]; info["auto"] = auto["bilan"]
            if auto.get("fib_q") is not None and self.fib is not None: self.fib["q"] = auto["fib_q"]; self.fib["sale"][:] = False
            if champ == "h": e["deplacement_max"] = round(float(np.abs(apres - avant).max()), 2)
            self._journal(e); self._enregistrer(champ)
            info.update(id=i, outil=outil, note_zone=e["note_zone"], deplacement_max=e.get("deplacement_max"), enregistre=self.enregistre, ms=round((time.time() - t0) * 1000))
            return info

    def annuler(self, sens=-1):
        """Ctrl+Z (sens = −1) ou Ctrl+Y (sens = +1), sans limite : chaque geste garde sur disque l'avant et l'après de sa zone."""
        with self.verrou:
            src = self.pile if sens < 0 else self.refaire
            if not src: return dict(rien=True, message="nothing left to undo" if sens < 0 else "nothing left to redo")
            i = src.pop(); p = self._patch(i); v0, v1, u0, u1 = p["bbox"]
            if p["champ"] == "grille": return self._ext_annuler(i, sens)                                  # 25/11 : annuler / rétablir une extension
            (self.h if p["champ"] == "h" else self.zones)[v0:v1, u0:u1] = p["avant"] if sens < 0 else p["apres"]
            (self.refaire if sens < 0 else self.pile).append(i)
            self._journal(dict(type="annuler" if sens < 0 else "retablir", id=i, t=time.strftime("%Y-%m-%d %H:%M:%S"))); info = self._apres(p["champ"], p["bbox"]); self._enregistrer(p["champ"])
            g = self.gestes.get(i, {}); s = self.gestes.get(self.pile[-1]) if self.pile else None
            info.update(id=i, outil=g.get("outil"), defait=sens < 0, params=g.get("params"), sommet=dict(outil=s["outil"], params=s["params"]) if s else None, enregistre=self.enregistre)
            return info

    def etat(self):
        vs = []
        for v in self._versions():
            try: m = json.loads((v / "meta.json").read_text(encoding="utf-8"))
            except Exception: m = {}
            vs.append(dict(nom=v.name, figee=bool(m.get("figee")), role=m.get("role"), creee=m.get("creee")))
        return dict(nom=self.nom, page=[self.H, self.W], grille=[self.gh, self.gw], pas=self.pas, um=self.um, demi=DEMI, couches=COUCHES, hmax=HMAX, carreau=CARREAU, niveaux=NIVEAUX, tuile=TUILE,
                    miroir=bool(self.cfg.get("miroir")), face=self.cfg.get("face"), encre=[dict(cle=c["cle"], nom=c["nom"]) for c in self.cfg.get("encre", [])], version=self.version, versions=vs,
                    pile=len(self.pile), refaire=len(self.refaire), enregistre=self.enregistre or self.meta.get("modifiee", "")[-8:] or None, gen=self.gen, bilan=self.bilan(),
                    criteres=CRITERES, voisine_proche=VOISINE_PROCHE, auto=list(self.AUTOS) + ["etendre"], org=[int(x) for x in self.org], extensions=len(self.ext), rouleau=(re.search(r"PHerc\w+", self.cfg.get("volume", "")) or [""])[0], surface=self.cfg["surface"], dossier=str(self.d),
                    volume=self.cfg.get("volume"), origine=self.cfg.get("origin") or {}, densifie=int(self.cfg.get("densified_factor") or 1), blocs_absents=int(self.cfg.get("blocs_absents") or 0))
