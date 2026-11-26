/* Surface Enhancer — tabs: several segments open at once, and a “New tab” to start from.
   A tab is either one editor (editor.html?tab=1&s=<segment>) or a start tab (index.html?tab=1: your segments, add a segment). Each tab lives
   in its own frame, created the first time it is shown and then kept: coming back to a tab is instant and finds everything as it was left.
   There is always at least one tab: with no segment open, the start tab is what the window shows. “+” opens another start tab.
   The list of open tabs is remembered in this browser. Closing a tab loses nothing: every gesture is already on disk. */
"use strict";
(() => {
  const CLE = "surface_enhancer_tabs", $ = id => document.getElementById(id);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const depart = id => id.charAt(0) === "+";              // a start tab (segment names never begin with “+”)
  let etat = { open: [], active: null }, connus = null, n = 0; const cadres = {};
  try { const j = JSON.parse(localStorage.getItem(CLE) || "{}"); if (Array.isArray(j.open)) etat = { open: j.open.map(String), active: j.active || null }; } catch (e) { }
  const sauver = () => { try { localStorage.setItem(CLE, JSON.stringify(etat)); } catch (e) { } };
  const infos = nom => (connus || []).find(s => s.name === nom);

  async function lister() {                               // the prepared segments, from the server
    try { const h = await (await fetch("/api/home", { cache: "no-store" })).json(); connus = h.segments.filter(s => s.ready); } catch (e) { connus = null; }
  }
  function dessiner() {
    $("liste").innerHTML = etat.open.map(id => { const s = infos(id), a = id === etat.active, d = depart(id);
      return `<div class="onglet${a ? " actif" : ""}${d ? " depart" : ""}" role="tab" aria-selected="${a}" data-nom="${esc(id)}"><button class="nom" title="${d ? "Open or add a segment" : esc(id)}">${d ? "New tab" : esc(id)}${s && s.scroll ? `<small>${esc(s.scroll)}</small>` : ""}</button><button class="x" aria-label="Close ${d ? "this tab" : esc(id)}" title="Close this tab (nothing is lost: every gesture is saved)">×</button></div>`; }).join("");
  }
  function activer(id) {
    if (!etat.open.includes(id)) etat.open.push(id); etat.active = id; sauver();
    if (!cadres[id]) { const f = document.createElement("iframe");
      f.src = depart(id) ? "index.html?tab=1&id=" + encodeURIComponent(id) : "editor.html?tab=1&s=" + encodeURIComponent(id); f.title = depart(id) ? "New tab" : "Editor: " + id; $("cadres").appendChild(f); cadres[id] = f; }
    for (const [k, f] of Object.entries(cadres)) f.classList.toggle("actif", k === id);
    document.title = depart(id) ? "Surface Enhancer" : "Surface Enhancer — " + id; history.replaceState(null, "", depart(id) ? "tabs.html" : "tabs.html?s=" + encodeURIComponent(id)); dessiner();
    setTimeout(() => { try { cadres[id].contentWindow.focus(); } catch (e) { } }, 60);
  }
  function nouveau() { const id = "+" + Date.now().toString(36) + (n++); activer(id); return id; }
  function retirer(id) { const i = etat.open.indexOf(id); if (i >= 0) etat.open.splice(i, 1); if (cadres[id]) { cadres[id].remove(); delete cadres[id]; } return i; }
  function fermer(id) {
    const i = retirer(id); if (i < 0) return;
    if (etat.active === id) etat.active = etat.open[Math.min(i, etat.open.length - 1)] || null;
    sauver(); if (etat.active) activer(etat.active); else nouveau();          // never an empty window
  }
  function ouvrir(nom, depuis) {
    /* Open a segment. Called by a start tab with its own id: the segment takes the place of that start tab. With no name: a new start tab. */
    if (!nom) return nouveau();
    if (depuis && depart(depuis) && etat.open.includes(depuis) && !etat.open.includes(nom)) { const i = retirer(depuis); etat.open.splice(i, 0, nom); }
    else if (depuis && depart(depuis) && etat.open.includes(nom)) retirer(depuis);
    activer(nom);
  }
  $("plus").addEventListener("click", () => nouveau());
  $("liste").addEventListener("click", ev => { const o = ev.target.closest(".onglet"); if (!o) return; if (ev.target.closest(".x")) fermer(o.dataset.nom); else activer(o.dataset.nom); });
  $("liste").addEventListener("auxclick", ev => { const o = ev.target.closest(".onglet"); if (o && ev.button === 1) { ev.preventDefault(); fermer(o.dataset.nom); } });      // middle click closes, as in a browser
  window.SR_TABS = { open: ouvrir, newTab: nouveau, close: fermer, activate: activer, state: () => etat };      // used by the pages inside the tabs

  (async () => {
    await lister();
    etat.open = etat.open.filter(id => !depart(id) && (!connus || infos(id)));          // start tabs are not kept from one visit to the next
    if (!etat.open.includes(etat.active)) etat.active = etat.open[0] || null;
    const voulu = new URLSearchParams(location.search).get("s");
    if (voulu) activer(voulu); else if (etat.active) activer(etat.active); else nouveau();
    window.READY = true;
  })();
})();
