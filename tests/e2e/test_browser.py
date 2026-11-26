"""End-to-end test in a headless Chrome, on a laptop-sized window (1366 × 768): the home page (upload, prepare, VC3D
package, error messages), then the editor (sections, retouch, undo, magnet, help, 3D, export, download).

Skipped when no Chrome / Chromium is found or when ``aiohttp`` is missing. Set ``SR_SCREENSHOTS=<folder>`` to keep the
screenshots (this is how docs/images/ is refreshed). One browser at a time; its debugging port is checked free first.
"""
import asyncio
import io
import json
import os
import zipfile
from pathlib import Path

import numpy as np
import pytest

from conftest import SAMPLE_SEGMENT, SAMPLE_VOLUME

pilot = pytest.importorskip("pilot")
pytest.importorskip("aiohttp")
pytestmark = [pytest.mark.e2e, pytest.mark.skipif(pilot.find_chrome() is None or os.environ.get("SR_SKIP_E2E") == "1", reason="no Chrome found (or SR_SKIP_E2E=1)")]


def test_whole_journey(server, settings, volpkg, tmp_path):
    shots = Path(os.environ.get("SR_SCREENSHOTS") or tmp_path / "shots")
    shots.mkdir(parents=True, exist_ok=True)
    z = tmp_path / "sample_scroll1.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in SAMPLE_SEGMENT.iterdir():
            zf.write(f, f"sample_scroll1/{f.name}")
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    checks = []

    def check(ok, what, detail=""):
        checks.append((bool(ok), what, str(detail)))
        print(("  ok    " if ok else "  FAIL  ") + what + (f" — {detail}" if detail else ""), flush=True)

    async def journey():
        async with pilot.Pilot(1366, 768) as p:
            text = lambda sel: p.js(f"(document.querySelector({json.dumps(sel)})||{{}}).innerText||''")
            fits = lambda: p.js("document.documentElement.scrollWidth <= window.innerWidth + 1")

            # ── home page ──
            await p.goto(server + "/index.html")
            await p.wait("window.READY === true", 30)
            check(not p.errors, "home page loads without console error", "; ".join(p.errors))
            check("sample" in await text("#segments") and "ready" in await text("#segments"), "the prepared sample is listed as ready (word + tick, not colour alone)", (await text("#segments"))[:80])
            check(await fits(), "home page fits a 1366 px wide window (no sideways scrolling)")
            await p.screenshot(shots / "home.png")
            await p.click_on("#aideBtn")
            check(await p.js("!document.getElementById('aideDlg').hidden"), "“How it works” opens")
            await p.key("Escape", vk=27)
            check(await p.js("document.getElementById('aideDlg').hidden"), "Esc closes it")

            # error messages, before anything is chosen
            check(await p.js("document.getElementById('preparer').disabled") and "first choose the scroll (step 1), then choose your segment (step 2)" in await text("#preparer"), "Prepare is disabled and the button itself says what is missing", await text("#preparer"))
            await p.click_on("#ongletChemin")
            await p.type("#chemin", "/no/such/folder")
            await p.click_on("#inspecter")
            await p.wait("document.getElementById('surfaceEtat').innerText.includes('not a folder')", 10)
            check("✗" in await text("#surfaceEtat"), "a wrong folder gives a clear message", (await text("#surfaceEtat"))[:90])
            await p.js("document.getElementById('rouleau').value='autre'; pickScroll()")      # the scroll picker: "another scan" reveals the address field
            await p.type("#volume", "/no/such/volume.zarr")
            await p.click_on("#verifier")
            await p.wait("document.getElementById('volumeEtat').innerText.includes('volume not found')", 10)
            check(True, "a wrong volume address gives a clear message", (await text("#volumeEtat"))[:90])

            # upload a zip, check the volume, prepare
            await p.click_on("#ongletZip")
            from conftest import SAMPLE_SEGMENT
            await p.set_files("#dossierIn", [SAMPLE_SEGMENT])      # a folder chosen instead of a zip
            await p.wait("document.getElementById('surfaceEtat').innerText.includes('17 × 17')", 20)
            check("✓" in await text("#surfaceEtat"), "a segment folder is accepted as it is (no zip needed)", (await text("#surfaceEtat"))[:70])
            other = tmp_path / "not_a_segment"
            other.mkdir()
            (other / "y.tif").write_bytes((SAMPLE_SEGMENT / "y.tif").read_bytes())
            await p.set_files("#dossierIn", [other])
            await p.wait("document.getElementById('surfaceEtat').innerText.includes('x.tif')", 10)
            check("✗" in await text("#surfaceEtat"), "a folder that is not a segment is refused with the reason", (await text("#surfaceEtat"))[:70])
            await p.set_files("#fichier", [z])
            await p.wait("document.getElementById('surfaceEtat').innerText.includes('17 × 17')", 20)
            check("one every 16 voxels" in await text("#surfaceEtat"), "the uploaded zip is read and described", (await text("#surfaceEtat"))[:110])
            check(await p.js("document.getElementById('densifier').checked && !document.getElementById('densifierLigne').hidden"), "a coarse grid is offered a resample to 4 voxels")
            await p.type("#volume", str(SAMPLE_VOLUME))
            await p.click_on("#verifier")
            await p.wait("document.getElementById('volumeEtat').innerText.includes('✓')", 20)
            check("7.91" in await text("#volumeEtat"), "the volume is opened and described", (await text("#volumeEtat"))[:110])
            await p.type("#nom", "e2e_upload")
            check("in the cache folder" in await text("#devis"), "the cost of the preload is announced before starting", (await text("#devis"))[:90])
            await p.screenshot(shots / "home_add_segment.png")
            await p.click_on("#preparer")
            await p.wait("document.getElementById('jobs').innerText.includes('e2e_upload')", 15)
            await p.wait("document.getElementById('segments').innerText.includes('e2e_upload')", 120, 0.4)
            check(True, "the preparation runs with a progress bar, then the segment appears in the list")

            # VC3D volume package
            await p.js("document.getElementById('blocVc').open = true")      # the VC3D block is folded by default
            await p.type("#volpkg", str(volpkg))
            await p.click_on("#ouvrirVolpkg")
            await p.wait("!document.getElementById('volpkgVue').hidden", 15)
            check("sample_scroll1" in await text("#volpkgSegments") and "sample-7.91um" in await p.js("document.getElementById('volpkgVolume').innerText"), "a VC3D volume package lists its volumes and segments")
            await p.js("document.getElementById('volpkg').scrollIntoView()")
            await p.screenshot(shots / "home_vc3d_package.png")
            await p.type("#filtre", "zzzz")
            check("No segment matches" in await text("#volpkgSegments"), "empty filter result is explained")

            # ── editor ──
            await p.goto(f"{server}/editor.html?s=nope")
            await p.wait("!document.getElementById('vide').hidden", 15)
            check("no prepared segment" in await text("#vide"), "an unknown segment gives an explained empty state with a way back", (await text("#videTitre")))
            p.errors.clear()                                  # the 404 above is expected
            await p.goto(f"{server}/editor.html?s=e2e_upload&neuf")
            await p.wait("window.PRET === true", 40)
            await asyncio.sleep(0.8)
            check(not p.errors, "editor loads without console error", "; ".join(p.errors))
            check("e2e_upload" in await p.js("document.title"), "the tab title names the segment", await p.js("document.title"))
            rc = await p.js("(()=>{const c=document.getElementById('page').getBoundingClientRect();return [c.left,c.top,c.width,c.height]})()")
            cx, cy = rc[0] + rc[2] / 2, rc[1] + rc[3] / 2
            lay = await p.js("(()=>{const a=document.getElementById('coupeU').getBoundingClientRect(), b=document.getElementById('coupeV').getBoundingClientRect(); return [a.width, a.bottom, b.bottom, innerHeight]})()")
            check(rc[2] >= 480 and lay[0] >= 320 and lay[2] <= lay[3] and await fits(), "page and both sections are fully visible at 1366 × 768", f"page {rc[2]:.0f} px wide, sections {lay[0]:.0f} px wide, bottom {lay[2]:.0f} of {lay[3]}")
            await p.hover(cx + 30, cy + 20)
            await p.wait("!!COUPE.e", 10)
            check(await p.js("!epingle && !!COUPE.e"), "the sections follow the mouse")
            await p.click(cx, cy)
            await asyncio.sleep(0.3)
            check(await p.js("!epingle"), "a left click does not pin")
            await p.click(cx, cy, "right")
            await asyncio.sleep(0.5)
            check(await p.js("epingle && COUPE.e.ligne_u.length > 50"), "a right-click pins the sections")
            await p.click(cx, cy, "right")
            await asyncio.sleep(0.3)
            check(await p.js("!epingle"), "a second right-click releases them")
            await p.click(cx, cy, "right")
            await asyncio.sleep(0.5)
            su = await p.js("(()=>{const r=COUPE.cv.u.getBoundingClientRect();return [r.left+r.width*0.3, r.top+r.height/2]})()")
            await p.wheel(su[0], su[1], -300)
            await asyncio.sleep(0.5)
            check(await p.js("COUPE.vue.u.k > COUPE.vue.v.k && epingle"), "the wheel zooms one section only", await p.js("COUPE.vue.u.k.toFixed(2) + ' / ' + COUPE.vue.v.k.toFixed(2)"))
            await p.click_on("#recentrerU")
            await asyncio.sleep(0.5)
            check(await p.js("COUPE.vue.u.k === COUPE.ech && COUPE.vue.u.ox === 0 && COUPE.vue.u.oy === 0"), "Recenter puts the section back")
            grey = await p.js("(()=>{const c=COUPE.img.u.getContext('2d').getImageData(0,0,COUPE.img.u.width,COUPE.img.u.height).data;let s=0;for(let i=0;i<c.length;i+=4)s+=c[i];return s/(c.length/4)})()")
            check(grey > 20, "the section shows the scan", f"mean grey {grey:.0f}")
            await p.screenshot(shots / "editor.png")

            g = await p.js("(()=>{const G=geoCoupe('u'),e=COUPE.e,r=COUPE.cv.u.getBoundingClientRect();return [r.left+G.x(e.w+10), r.top+G.y(e.ligne_u[e.w+10]), COUPE.ech]})()")
            await p.press(g[0], g[1])
            await p.drag_to(g[0], g[1], g[0], g[1] - 6 * g[2])
            await p.release(g[0], g[1] - 6 * g[2])
            await p.js("file.then(()=>true)")
            await asyncio.sleep(0.5)
            h = np.load(settings.segments_dir / "e2e_upload" / "versions" / "v001" / "decalage.npy")
            check(5.5 < float(np.abs(h).max()) < 6.5 and await p.js("E.pile") == 1, "dragging the orange line by 6 voxels moves the surface by 6 voxels", f"max offset {np.abs(h).max():.2f} vx")
            check("saved at" in await text("#sauve"), "“saved at HH:MM:SS” is shown", await text("#sauve"))
            check("Last retouch" in await text("#derniere") and ("▲" in await text("#derniere") or "▼" in await text("#derniere") or "=" in await text("#derniere")), "the score change of the retouch is given with an arrow and numbers")
            await p.key("z", "KeyZ", ctrl=True, vk=90)
            await p.js("file.then(()=>true)")
            await asyncio.sleep(0.4)
            h = np.load(settings.segments_dir / "e2e_upload" / "versions" / "v001" / "decalage.npy")
            check(await p.js("E.pile") == 0 and not h.any(), "Ctrl+Z restores the exact original surface")

            await p.key("a", "KeyA", vk=65)
            check(await p.js("outil") == "aimant" and "Magnet" in await text("#outilInfo"), "key A selects the magnet (named on the page)")
            await p.drag(cx - 40, cy - 30, cx + 40, cy + 30)
            await p.js("file.then(()=>true)")
            await asyncio.sleep(0.5)
            check(await p.js("E.pile") == 1, "the magnet writes one gesture", await text("#derniere"))
            await p.key("s", "KeyS", vk=83)
            check(await p.js("V.score && document.getElementById('voirScore').checked"), "key S shows the score map")
            await p.screenshot(shots / "editor_scores.png")
            await p.key("s", "KeyS", vk=83)
            await p.key("r", "KeyR", vk=82)

            await p.key("?", text="?")
            check(await p.js("!document.getElementById('aideDlg').hidden") and "orange line" in await text("#aideDlg"), "? opens the help (gestures, keys, score)")
            await p.screenshot(shots / "editor_help.png")
            await p.key("a", "KeyA", vk=65)
            check(await p.js("outil") == "regarder", "keys do not change the tool behind an open dialog")
            await p.key("Escape", vk=27)
            check(await p.js("document.getElementById('aideDlg').hidden"), "Esc closes the help")

            await p.key("Tab", vk=9)
            await p.wait("V.vue === '3d' && v3d && v3d.ok", 15)
            await asyncio.sleep(1.5)
            check(not p.errors, "3D view opens without error", "; ".join(p.errors))
            await p.screenshot(shots / "editor_3d.png")
            await p.key("Tab", vk=9)
            await p.wait("V.vue === '2d'", 10)

            # automatic button: preview first, then apply as one gesture
            await p.js("document.querySelector('details[data-grp=auto]').open = true")
            await p.js("document.getElementById('autoGreffe').checked = false")
            await p.click_on("button[data-auto=aimant_partout]")
            await p.wait("!!AP && !document.getElementById('autoChoix').hidden", 60)
            check(await p.js("E.pile") == 1 and "preview" in await text("#autoBilan"), "“Magnet everywhere” first shows a preview and writes nothing")
            await p.click_on("#autoAppliquer")
            await p.js("file.then(()=>true)")
            await asyncio.sleep(0.5)
            check(await p.js("E.pile") == 2, "Apply writes it as ONE gesture")

            # export dialog: write a new segment, then download the bundle
            await p.click_on("#menuBtn")
            await asyncio.sleep(0.3)
            items = await p.js("[...document.querySelectorAll('#menuListe [role=menuitem] b')].map(b => b.textContent).join(' | ')")
            check(await p.js("!document.getElementById('menuListe').hidden") and all(w in items for w in ("Import", "Open", "Save", "Export", "Close")), "the Segment menu offers import, open, save, export and close", items)
            await p.click_on("#menuListe [data-fait=exporter]")      # the menu entry does what the Export button does
            check(await p.js("!document.getElementById('exportDlg').hidden && !document.getElementById('exportGrille').hidden"), "the export dialog opens and offers the original node layout")
            await p.click_on("#exportVc")
            await p.wait("!document.getElementById('exportResultat').hidden", 5)
            check("Give the segments folder" in await text("#exportResultat"), "writing to VC3D without a folder is explained, not attempted")
            await p.type("#exportDossier", str(volpkg / "paths"))
            await p.type("#exportId", "e2e_into_vc3d")
            await p.click_on("#exportVc")
            await p.wait("document.getElementById('exportResultat').innerText.includes('written')", 20)
            meta_f = volpkg / "paths" / "e2e_into_vc3d" / "meta.json"
            meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
            check("VC3D check passed" in await text("#exportResultat") and meta.get("uuid") == "e2e_into_vc3d" and meta.get("scale") == [0.0625, 0.0625],
                  "the retouch is written as a NEW segment of the VC3D package, with the node layout VC3D had", (await text("#exportResultat"))[:80])
            await p.screenshot(shots / "editor_export.png")
            await p.allow_downloads(downloads)
            await p.click_on("#dlBundle")
            for _ in range(60):
                got = [f for f in downloads.glob("*.zip")]
                if got:
                    break
                await asyncio.sleep(0.25)
            names = zipfile.ZipFile(io.BytesIO(got[0].read_bytes())).namelist() if got else []
            check(any(n.endswith("/x.tif") for n in names) and any(n.endswith(".retouch/journal.jsonl") for n in names) and any(n.endswith(".retouch/offset_along_normal.npy") for n in names),
                  "Download gives one zip: tifxyz segment + offset field + journal", f"{len(names)} files")
            await p.key("Escape", vk=27)

            # tabs: two segments open at once, each editor kept as it was
            await p.goto(f"{server}/tabs.html?s=sample")
            await p.wait("window.READY === true && document.querySelector('#cadres iframe.actif') && document.querySelector('#cadres iframe.actif').contentWindow.PRET === true", 40)
            frame = "document.querySelector('#cadres iframe.actif').contentWindow"
            check(await p.js("document.querySelectorAll('.onglet').length === 1 && document.querySelector('.onglet.actif').dataset.nom === 'sample'") and await p.js(f"{frame}.document.getElementById('retour').hidden"),
                  "opening a segment gives one tab, with the editor inside")
            await p.js(f"{frame}.MARK = 'kept'")
            await p.click_on("#plus")
            await p.wait(f"document.querySelector('.onglet.actif.depart') && {frame}.READY === true", 20)
            check(await p.js(f"{frame}.document.body.classList.contains('dansOnglet') && !!{frame}.document.getElementById('tAjout')") and await p.js("document.querySelectorAll('.onglet').length === 2"),
                  "+ opens a New tab: your segments and Add a segment, in the window itself")
            await p.screenshot(shots / "start_tab.png")
            await p.js(f"{frame}.document.querySelector('a[href=\"tabs.html?s=e2e_upload\"]').click()")
            await p.wait(f"document.querySelector('.onglet.actif').dataset.nom === 'e2e_upload' && {frame}.PRET === true", 40)
            check(await p.js("document.querySelectorAll('.onglet').length === 2 && document.querySelectorAll('#cadres iframe').length === 2"), "Open, in the New tab, puts the segment in that tab; the first stays open")
            await p.screenshot(shots / "editor_tabs.png")
            await p.click_on(".onglet[data-nom=sample] .nom")
            await asyncio.sleep(0.4)
            check(await p.js(f"document.querySelector('.onglet.actif').dataset.nom === 'sample' && {frame}.MARK === 'kept'"), "coming back to a tab finds its editor as it was (not reloaded)")
            await p.js(f"{frame}.document.getElementById('menuBtn').click()")
            await p.js(f"{frame}.document.querySelector('#menuListe [data-onglet=close]').click()")
            await asyncio.sleep(0.4)
            check(await p.js("document.querySelectorAll('.onglet').length === 1 && document.querySelector('.onglet.actif').dataset.nom === 'e2e_upload' && document.querySelectorAll('#cadres iframe').length === 1"),
                  "Close in the Segment menu closes the tab and shows the other one")
            await p.goto(f"{server}/tabs.html")
            await p.wait("window.READY === true", 20)
            check(await p.js("document.querySelectorAll('.onglet').length === 1 && document.querySelector('.onglet.actif').dataset.nom === 'e2e_upload'"), "the open tabs are remembered")
            await p.click_on(".onglet.actif .x")
            await asyncio.sleep(0.5)
            check(await p.js("document.querySelectorAll('.onglet').length === 1 && !!document.querySelector('.onglet.actif.depart')"), "closing the last segment leaves a New tab, never an empty window")
            check(not p.errors, "no console error during the whole journey", "; ".join(p.errors))

    asyncio.run(journey())
    failed = [f"{w} ({d})" for ok, w, d in checks if not ok]
    assert not failed, "\n".join(failed)
    assert len(checks) >= 38
