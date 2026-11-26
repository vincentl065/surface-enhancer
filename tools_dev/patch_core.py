"""Re-create ``surface_enhancer/core/`` from the upstream workshop files (see docs/MERGE.md).

    python tools_dev/patch_core.py <folder holding commun.py, segment.py, auto.py, auto_noyaux.py>

The four files are copied, then a short list of exact replacements is applied (package imports, no hard-coded path,
English error messages, export moved to ``surface_enhancer/export.py``). Each replacement must match exactly once:
if upstream changed one of these lines the script stops and names it, so nothing is merged blindly.
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
CORE = HERE / "surface_enhancer" / "core"


SCAN_SHIM = '''

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
'''


def patch(name, edits, cuts=()):
    f = CORE / name
    s = f.read_text(encoding="utf-8")
    for a, b in cuts:                       # remove everything from the line starting with a up to (not including) the line starting with b
        m = re.search(r"^" + re.escape(a) + r".*?(?=^" + re.escape(b) + r")", s, re.S | re.M)
        if not m:
            raise SystemExit(f"{name}: block not found: {a!r} … {b!r}")
        s = s[:m.start()] + s[m.end():]
    for old, new in edits:
        n = s.count(old)
        if n != 1:
            raise SystemExit(f"{name}: expected exactly one match, found {n}: {old[:90]!r}")
        s = s.replace(old, new)
    f.write_text(s, encoding="utf-8", newline="\n")
    print("patched", name)


def main():
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
        for n in ("commun.py", "segment.py", "auto.py", "auto_noyaux.py", "extension.py"):
            shutil.copy2(src / n, CORE / n)

    patch("commun.py", [
        ('RACINE = Path(__file__).resolve().parent\nDONNEES = RACINE / "donnees"\n', ""),
        ('''def trouver_tifxyz(d) -> Path:
    d = Path(d)
    if (d / "x.tif").exists():
        return d
    c = sorted(p.parent for p in d.glob("pages/*/x.tif")) or sorted(p.parent for p in d.glob("*/x.tif"))
    if not c:
        raise SystemExit(f"aucune surface tifxyz (x.tif, y.tif, z.tif) dans {d}")
    return c[0]
''', '''def trouver_tifxyz(d) -> Path:
    from ..tifxyz import find_tifxyz
    return find_tifxyz(d)
'''),
        ('''    import tifffile
    X, Y, Z = [tifffile.imread(str(t / f"{c}.tif")).astype(np.float32) for c in "xyz"]
    meta = json.loads((t / "meta.json").read_text(encoding="utf-8")) if (t / "meta.json").exists() else {}
    pas = int(round(1 / meta.get("scale", [0.05, 0.05])[0]))
    valide = (X > 0) & (Y > 0) & (Z > 0) & np.isfinite(X) & np.isfinite(Y) & np.isfinite(Z)
    return np.stack([Z, Y, X], -1), valide, pas, meta
''', '''    from ..tifxyz import read_grid          # same validity rule as VC3D: z > 0, finite, optional mask.tif
    return read_grid(t)
'''),
    ], cuts=[("def cache_par_defaut", "# ───────────────────────────── grille tifxyz"),
             ("# ───────────────────────────── scan : blocs 128³", "def _numba")])

    f = CORE / "commun.py"                       # the old block reader, kept as a thin adapter so that upstream modules that still import it work unchanged
    f.write_text(f.read_text(encoding="utf-8") + SCAN_SHIM, encoding="utf-8", newline=chr(10))

    patch("auto.py", [
        ("from commun import DEMI, HMAX, ND, ecrire_atomique, interp_noeuds", "from .commun import DEMI, HMAX, ND, ecrire_atomique, interp_noeuds"),
        ("            from auto_noyaux import etiqueter\n            cu0, cv0 = self._marches_tout(self.h); cu1, cv1 = self._marches_tout(neuf)",
         "            from .auto_noyaux import etiqueter\n            cu0, cv0 = self._marches_tout(self.h); cu1, cv1 = self._marches_tout(neuf)"),
        ('''        """Calcule un geste automatique SANS l'écrire : bilan + carte de ce qui bougerait. « Apply » (le geste du même nom, mêmes paramètres)
        reprend ce résultat tel quel si la surface n'a pas changé entre-temps."""
        from segment import paquet''', '''        """Calcule un geste automatique SANS l'écrire : bilan + carte de ce qui bougerait. « Apply » (le geste du même nom, mêmes paramètres)
        reprend ce résultat tel quel si la surface n'a pas changé entre-temps."""
        from .segment import paquet'''),
        ("        from auto_noyaux import recaler, suivre\n", "        from .auto_noyaux import recaler, suivre\n"),
        ("        from auto_noyaux import etiqueter\n        t0 = time.time(); gh, gw = self.gh, self.gw; seuil", "        from .auto_noyaux import etiqueter\n        t0 = time.time(); gh, gw = self.gh, self.gw; seuil"),
        ('''        """Pour le calque « fibre score » : note 0–100 par fenêtre (surface actuelle et surface d'origine)."""
        from segment import paquet''', '''        """Pour le calque « fibre score » : note 0–100 par fenêtre (surface actuelle et surface d'origine)."""
        from .segment import paquet'''),
        ("recopiée ici pour ne rien importer de là-bas : min(part de", "La note de quadrillage des fibres (mesure directe, sans apprentissage) : min(part de"),
    ], cuts=[("La note de quadrillage des fibres est celle de l'audit (", "recopiée ici pour ne rien importer")])      # a line naming private working folders

    patch("segment.py", [
        ("from auto import Auto\nfrom extension import Extension\nfrom commun import (CARREAU, COUCHES, DEMI, DONNEES, HMAX, ND, NIVEAUX, TUILE, ecrire_atomique, ecrire_json, fondu, interp_noeuds, reduire2, valide_px)",
         "from .auto import Auto\nfrom .extension import Extension\nfrom .commun import (CARREAU, COUCHES, DEMI, HMAX, ND, NIVEAUX, TUILE, ecrire_atomique, ecrire_json, fondu, interp_noeuds, reduire2, valide_px)\n\n\n"
         "class SegmentError(RuntimeError):\n    \"\"\"The segment cannot be opened (not prepared, preload unfinished…); the message is meant for the user.\"\"\""),
        ('''    def __init__(self, nom: str, rejeu=False):
        self.nom = nom; self.d = DONNEES / nom; self.rejeu = rejeu        # rejeu : repart de la surface d'origine, n'écrit rien (rejouer.py)
        if not (self.d / "config.json").exists(): raise SystemExit(f"segment « {nom} » pas préparé : python preparer.py <surface> <volume> {nom}")
        self.cfg = json.loads((self.d / "config.json").read_text(encoding="utf-8")); self.cache = Path(self.cfg["cache"])''',
         '''    def __init__(self, nom: str, rejeu=False, donnees=None, cache=None):
        self.nom = nom; self.d = Path(donnees) / nom; self.rejeu = rejeu        # rejeu : repart de la surface d'origine, n'écrit rien (replay)
        if not (self.d / "config.json").exists(): raise SegmentError(f"segment “{nom}” is not prepared yet: prepare it first (home page, or: python -m surface_enhancer prepare <surface> <volume> --name {nom})")
        self.cfg = json.loads((self.d / "config.json").read_text(encoding="utf-8"))
        self.cache = Path(cache) if cache is not None and (Path(cache) / "bloc.npy").exists() else Path(self.cfg["cache"])       # the cache folder of the settings first; else where it was when prepared'''),
        ('''        if not fait.exists() or not np.load(fait).all(): raise SystemExit(f"le préchargement de « {nom} » n'est pas terminé : relance preparer.py (il reprend où il en était)")''',
         '''        if not fait.exists() or not np.load(fait).all(): raise SegmentError(f"the preload of “{nom}” is not finished (or its cache folder {self.cache} is gone): run the preparation again, it resumes where it stopped")'''),
        ('''            print(f"rattrapage : {rattrape} geste(s) du journal rejoué(s) sur {self.version}", flush=True); self._enregistrer("h"); self._enregistrer("zones")''',
         '''            print(f"catch-up: {rattrape} journal gesture(s) replayed onto {self.version}", flush=True); self._enregistrer("h"); self._enregistrer("zones")'''),
        ('''        if self.meta.get("figee"): raise RuntimeError("version figée : on n'écrit pas dedans")''',
         '''        if self.meta.get("figee"): raise RuntimeError("this version is frozen: nothing is written into it")'''),
        ('''                    criteres=CRITERES, voisine_proche=VOISINE_PROCHE, auto=list(self.AUTOS) + ["etendre"], org=[int(x) for x in self.org], extensions=len(self.ext), rouleau=(re.search(r"PHerc\\w+", self.cfg.get("volume", "")) or [""])[0], surface=self.cfg["surface"], dossier=str(self.d))''',
         '''                    criteres=CRITERES, voisine_proche=VOISINE_PROCHE, auto=list(self.AUTOS) + ["etendre"], org=[int(x) for x in self.org], extensions=len(self.ext), rouleau=(re.search(r"PHerc\\w+", self.cfg.get("volume", "")) or [""])[0], surface=self.cfg["surface"], dossier=str(self.d),
                    volume=self.cfg.get("volume"), origine=self.cfg.get("origin") or {}, densifie=int(self.cfg.get("densified_factor") or 1), blocs_absents=int(self.cfg.get("blocs_absents") or 0))'''),
    ], cuts=[("    def exporter(self):", "    # ───────────────────────── rendus locaux")])
    patch("extension.py", [
        ("from commun import (CARREAU, COUCHES, DEMI, HMAX, KPICS, ND, NIVEAUX, Scan, chercheur_de_pics,", "from .commun import (CARREAU, COUCHES, DEMI, HMAX, KPICS, ND, NIVEAUX, Scan, chercheur_de_pics,"),
        ("    from preparer import rendre_points\n", "    from ..prepare import sample_points as rendre_points\n"),
        ("    from auto_noyaux import recaler, suivre_graines\n", "    from .auto_noyaux import recaler, suivre_graines\n"),
        ('scan = Scan(seg.cfg["volume"], seg.cfg["cache_scan"], reseau=reseau, max_blocs=48)', 'scan = Scan(seg.cfg["volume"], seg.cfg.get("cache_scan"), reseau=reseau, max_blocs=48)'),
    ])
    s = (CORE / "segment.py").read_text(encoding="utf-8")
    anchor = "    # ───────────────────────── rendus locaux"
    assert s.count(anchor) == 1
    s = s.replace(anchor, '''    def exporter(self, **options):
        """Export as a NEW tifxyz segment (see surface_enhancer/export.py). Never into the original folder, never over an export."""
        from ..export import export_segment
        with self.verrou:
            return export_segment(self, **options)

''' + anchor)
    (CORE / "segment.py").write_text(s, encoding="utf-8", newline="\n")
    print("core ready")


if __name__ == "__main__":
    main()
