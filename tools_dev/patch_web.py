"""Re-create ``surface_enhancer/web/app.js`` from the upstream workshop file (see docs/MERGE.md).

    python tools_dev/patch_web.py <folder holding app.js and vue3d.js>

``vue3d.js`` is copied as is. ``app.js`` gets a short list of exact replacements: English route names under
``/api/s/<segment>/``, the ``error`` key of the new server, and hooks for the export dialog and the help overlay
(``editor_extra.js``). Each replacement must match exactly once, else the script stops and names it.
"""
import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "surface_enhancer" / "web"

EDITS = [
    ('"use strict";\n', '"use strict";\nconst SEG = new URLSearchParams(location.search).get("s") || "", API = "/api/s/" + encodeURIComponent(SEG);\n'),
    ('const j = await r.json(); if (!r.ok || j.erreur) throw new Error(j.erreur || r.statusText); return j;',
     'let j = {}; try { j = await r.json(); } catch (e) { } if (!r.ok || j.error) { const err = new Error(j.error || r.statusText || "the server did not answer"); err.status = r.status; throw err; } return j;'),
    ('if (!r.ok) { let j = {}; try { j = await r.json(); } catch (e) { } throw new Error(j.erreur || r.statusText); }',
     'if (!r.ok) { let j = {}; try { j = await r.json(); } catch (e) { } throw new Error(j.error || r.statusText); }'),
    ('localStorage.setItem("retoucheur_" + E.nom,', 'localStorage.setItem("surface_enhancer_" + E.nom,'),
    ('`/api/tuile?n=${t.L}&y=${t.ty}&x=${t.tx}&c=${t.c}&g=${session}${t.g}` : `/api/encre?nom=${t.type}&n=${t.L}&y=${t.ty}&x=${t.tx}`',
     '`${API}/tile?n=${t.L}&y=${t.ty}&x=${t.tx}&c=${t.c}&g=${session}${t.g}` : `${API}/ink?nom=${t.type}&n=${t.L}&y=${t.ty}&x=${t.tx}`'),
    ('await binaire("/api/scores")', 'await binaire(API + "/scores")'),
    ('await api("/api/situer")', 'await api(API + "/locate")'),
    ('await binaire2("/api/sauts", ', 'await binaire2(API + "/jumps", '),
    ('await fetch("/api/zones")', 'await fetch(API + "/marks")'),
    ('await binaire(`/api/coupes?v=${p.v}&u=${p.u}&w=${w}`)', 'await binaire(`${API}/sections?v=${p.v}&u=${p.u}&w=${w}`)'),
    ('appliquer(await api("/api/geste", { outil: nom, params }))', 'appliquer(await api(API + "/gesture", { outil: nom, params }))'),
    ('appliquer(await api(sens < 0 ? "/api/annuler" : "/api/retablir", {}))', 'appliquer(await api(API + (sens < 0 ? "/undo" : "/redo"), {}))'),
    ('await api(`/api/pires?n=80&marquees=${marq ? 1 : 0}`)', 'await api(`${API}/worst?n=80&marked=${marq ? 1 : 0}`)'),
    ('const a = await api("/api/avancement");', 'const a = await api(API + "/progress");'),
    ('await binaire2("/api/fibres")', 'await binaire2(API + "/fibres")'),
    ('await binaire2("/api/apercu", { outil: o, params: p })', 'await binaire2(API + "/preview", { outil: o, params: p })'),
    ('[await api("/api/apercu", { outil: o, params: p }), {}]', '[await api(API + "/preview", { outil: o, params: p }), {}]'),
    ('appliquer(await api("/api/etendre", { params: a.params }))', 'appliquer(await api(API + "/extend", { params: a.params }))'),
    ('await binaire(`/api/patch3d?v=${p.v}&u=${p.u}&r=${$("v3dTaille").value}&c=${V.couche}&e=${encodeURIComponent(V.encre || "")}${tout ? "&tout=1&n=" + (v3d.grand ? 400 : 250) : ""}`)',
     'await binaire(`${API}/patch3d?v=${p.v}&u=${p.u}&r=${$("v3dTaille").value}&c=${V.couche}&e=${encodeURIComponent(V.encre || "")}${tout ? "&whole=1&n=" + (v3d.grand ? 400 : 250) : ""}`)'),
    ('const r = await api("/api/figer", {});', 'const r = await api(API + "/freeze", {});'),
    ('$("exporter").onclick = async () => { try { message("Exporting…"); const r = await api("/api/exporter", {}); message(`Exported as tifxyz: ${r.dossier} (${fr(r.noeuds_deplaces, 0)} nodes moved, ${fr(r.decalage_max, 1)} vx at most).`); } catch (e) { message(e.message, true); } };',
     '$("exporter").onclick = () => window.ouvrirExport && window.ouvrirExport();'),
    ('E = await api("/api/etat");', 'if (!SEG) { const e = new Error("no segment chosen"); e.status = 404; throw e; }\n    E = await api(API + "/state");'),
    ('$("chemins").textContent = `Versions: ${E.dossier}\\\\versions · exports: ${E.dossier}\\\\exports`;',
     '$("chemins").textContent = `Its versions, journal and exports are in ${E.dossier}`;'),
    ('try { m = JSON.parse(localStorage.getItem("retoucheur_" + E.nom)); } catch (e) { }', 'try { m = JSON.parse(localStorage.getItem("surface_enhancer_" + E.nom)); } catch (e) { }'),
    ('await Promise.all([chargerScores(), chargerZones()]); majPanneau(); dessinerCoupes(); demander(); window.PRET = true;',
     'await Promise.all([chargerScores(), chargerZones()]); majPanneau(); dessinerCoupes(); demander(); window.PRET = true; if (window.editeurPret) window.editeurPret();'),
    ('} catch (e) { $("sauve").textContent = "Server unreachable: restart serveur.py"; $("sauve").className = "erreur"; message(String(e.message || e), true); }',
     '} catch (e) { $("sauve").textContent = e.status ? "segment not opened" : "server unreachable"; $("sauve").className = "erreur"; message(String(e.message || e), true); if (window.editeurEchec) window.editeurEchec(e); }'),
    ('  else if (k === "escape") { if (prise || trait)', '  else if (k === "escape") { if (window.fermerDialogues && window.fermerDialogues()) return; if (prise || trait)'),
    ('  if (ev.target.tagName === "SELECT" || (ev.target.tagName === "INPUT" && ev.target.type !== "range" && ev.target.type !== "checkbox")) return;',
     '  if (ev.target.tagName === "SELECT" || ev.target.tagName === "TEXTAREA" || (ev.target.tagName === "INPUT" && ev.target.type !== "range" && ev.target.type !== "checkbox")) return;\n  if (window.dialogueOuvert && window.dialogueOuvert() && ev.key !== "Escape") return;'),
    ('if ($("auto") && !E.auto) { $("autoVieux").hidden = false;', 'if ($("auto") && !E.auto) {'),
]


def main():
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
        shutil.copy2(src / "app.js", WEB / "app.js")
        shutil.copy2(src / "vue3d.js", WEB / "vue3d.js")
        for n in ("panneau.js", "panneau.css", "fini.css"):           # the left panel: built and explained by these two files, the same in both tools
            shutil.copy2(src / n, WEB / n)
    f = WEB / "app.js"
    s = f.read_text(encoding="utf-8")
    for old, new in EDITS:
        n = s.count(old)
        if n != 1:
            raise SystemExit(f"app.js: expected exactly one match, found {n}: {old[:100]!r}")
        s = s.replace(old, new)
    left = [l for l in s.splitlines() if ('"/api/' in l or "`/api/" in l) and 'const SEG' not in l]
    if left:
        raise SystemExit("app.js: a route is still addressed the old way:\n" + "\n".join(x[:160] for x in left))
    f.write_text(s, encoding="utf-8", newline="\n")
    print("patched app.js")


if __name__ == "__main__":
    main()
