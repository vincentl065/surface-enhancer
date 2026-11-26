/* Surface Enhancer — editor additions that live outside app.js: help overlay, export / download dialog,
   empty state when a segment cannot be opened, collapsible panel groups. Uses the globals of app.js ($, E, API, api, fr, message). */
"use strict";
(function () {
  const dialogs = ["aideDlg", "exportDlg"];
  let previousFocus = null;
  const openOne = id => dialogs.find(d => !$(d).hidden) === id;
  function openDialog(id) {
    dialogs.forEach(d => { $(d).hidden = d !== id; });
    previousFocus = document.activeElement;
    const first = $(id).querySelector("button, input, a"); if (first) first.focus();
  }
  function closeDialogs() {
    const any = dialogs.some(d => !$(d).hidden);
    dialogs.forEach(d => { $(d).hidden = true; });
    if (any && previousFocus && previousFocus.focus) previousFocus.focus();
    return any;
  }
  window.fermerDialogues = closeDialogs;
  window.dialogueOuvert = () => dialogs.some(d => !$(d).hidden);
  document.querySelectorAll("[data-fermer]").forEach(b => b.addEventListener("click", closeDialogs));
  dialogs.forEach(d => $(d).addEventListener("pointerdown", ev => { if (ev.target === $(d)) closeDialogs(); }));
  $("aideBtn").onclick = () => openDialog("aideDlg");
  window.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && window.dialogueOuvert()) { ev.preventDefault(); closeDialogs(); return; }
    const t = ev.target.tagName;
    if (t === "INPUT" && ev.target.type === "text" || t === "TEXTAREA" || t === "SELECT") return;
    if (ev.key === "?" || ev.key === "F1") { ev.preventDefault(); openOne("aideDlg") ? closeDialogs() : openDialog("aideDlg"); }
  });

  // collapsible groups of the panel: remembered per browser
  document.querySelectorAll("details.groupe").forEach(d => {
    const key = "surface_enhancer_group_" + d.dataset.g;
    try { const v = localStorage.getItem(key); if (v !== null) d.open = v === "1"; } catch (e) { }
    d.addEventListener("toggle", () => { try { localStorage.setItem(key, d.open ? "1" : "0"); } catch (e) { } });
  });

  // empty state
  window.editeurEchec = err => {
    const none = !SEG;
    $("videTitre").textContent = none ? "No segment chosen" : err.status === 404 ? `There is no prepared segment named “${SEG}”` : err.status === 409 ? `“${SEG}” is not ready` : err.status ? `“${SEG}” cannot be opened` : "The server does not answer";
    $("videTexte").textContent = none ? "Open a segment from the list." : err.status ? String(err.message || err) : "Start it again with:  python -m surface_enhancer serve  — your gestures are saved, nothing is lost.";
    $("vide").hidden = false; document.title = "Surface Enhancer";
  };
  $("videReessayer").onclick = () => location.reload();

  // once the segment is loaded
  window.editeurPret = () => {
    const notes = [];
    if (E.blocs_absents) notes.push(`${fr(E.blocs_absents, 0)} scan blocks were missing when this segment was prepared: black areas in the sections are missing data, not voids. Prepare it again (it only fetches what is missing).`);
    if (!E.encre.length) { $("opEncreLigne").hidden = true; $("encre").title = "No ink layer for this segment. Add one with: python -m surface_enhancer ink-layer " + E.nom + ' "Label=prediction.tif"'; }
    if (notes.length) { $("avis").hidden = false; $("avis").textContent = "⚠ " + notes.join(" "); }
    if (!E.auto) $("autoVieux").hidden = false;
    const o = E.origine || {};
    $("exportDossier").value = o.output_segments || o.segments_dir || "";
    if (E.densifie > 1) {
      $("exportGrille").hidden = false;
      $("grilleOriginale").textContent = `same node layout as your segment (one node every ${E.pas * E.densifie} voxels) — what VC3D had`;
      $("grilleTravail").textContent = `working grid (one node every ${E.pas} voxels, ${E.densifie} × finer): keeps every detail of the retouch`;
    }
  };

  // export / download
  const grid = () => { const r = document.querySelector('input[name="grille"]:checked'); return E && E.densifie > 1 && r ? r.value : "working"; };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function result(html, error) { const r = $("exportResultat"); r.hidden = false; r.innerHTML = html; r.classList.toggle("erreur", !!error); }
  window.ouvrirExport = () => {
    $("exportResume").textContent = `${E.nom} · version ${E.version} · ${fr(E.pile, 0)} gesture${E.pile === 1 ? "" : "s"} applied` + (E.pile ? "" : " — nothing was retouched yet: the export would be identical to the original.");
    $("exportResultat").hidden = true; openDialog("exportDlg");
  };
  function download(what) {
    const a = document.createElement("a"); a.href = `${API}/download?what=${what}&grid=${grid()}`; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
    result(`✓ Download started (${what === "bundle" ? "segment + offset field + journal" : what}). Look in the downloads folder of your browser.`);
  }
  $("dlBundle").onclick = () => download("bundle"); $("dlSegment").onclick = () => download("segment");
  $("dlOffset").onclick = () => download("offset"); $("dlJournal").onclick = () => download("journal");
  async function exportTo(target) {
    const body = { target, grid: grid(), id: $("exportId").value.trim() };
    if (target === "volpkg") { body.segments_dir = $("exportDossier").value.trim(); if (!body.segments_dir) { result("✗ Give the segments folder of your VC3D package first (its <code>paths/</code> folder).", true); $("exportDossier").focus(); return; } }
    result("Writing…");
    try {
      const r = await api(API + "/export", body), bad = r.vc3d_problems || [];
      result(`<b>${bad.length ? "⚠ Written, but VC3D would refuse it" : "✓ New segment written"}</b>: <code>${esc(r.folder)}</code><br>` +
        `${fr(r.nodes_moved, 0)} nodes moved, ${fr(r.offset_max_vx, 1)} voxels at most${r.nodes_added ? ` · ${fr(r.nodes_added, 0)} nodes added by the extension` : ""} · grid ${r.shape[1]} × ${r.shape[0]} nodes` +
        (bad.length ? `<br>Problems: ${bad.map(esc).join("; ")}` : `<br>VC3D check passed (type, uuid, format, scale, bbox, x / y / z).`) +
        (target === "volpkg" ? `<br>In VC3D: reload the segments of the package (or open it again) — the new segment is listed under its id <code>${esc(r.id)}</code>.` : "") +
        (r.retouch_folder ? `<br><span class="doux">Record of the retouch (offset field, journal): <code>${esc(r.retouch_folder)}</code></span>` : ""), bad.length > 0);
    } catch (e) { result("✗ " + esc(e.message), true); }
  }
  $("exportVc").onclick = () => exportTo("volpkg"); $("exportLocal").onclick = () => exportTo("local");
})();
