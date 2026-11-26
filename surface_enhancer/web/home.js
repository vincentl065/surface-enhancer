/* Surface Enhancer — home page: prepared segments, preparation jobs, "add a segment" (upload or local folder),
   VC3D volume packages. Talks only to the local server (docs/HTTP_API.md). */
"use strict";
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (x, n = 0) => x == null || !isFinite(x) ? "–" : Number(x).toLocaleString("en-US", { minimumFractionDigits: n, maximumFractionDigits: n });
const size = b => b >= 1e9 ? num(b / 1e9, 2) + " GB" : b >= 1e6 ? num(b / 1e6, 0) + " MB" : num(b / 1e3, 0) + " kB";
let HOME = null, source = null, volumeOk = null, pkg = null, timer = 0, lastJobs = "";

// ───────────── as a start tab (tabs.html): same content, laid out like the editor — a left column, then the page in the middle ─────────────
let TABS = null; try { if (window.parent !== window && window.parent.SR_TABS) TABS = window.parent.SR_TABS; } catch (e) { }
const TAB_ID = new URLSearchParams(location.search).get("id") || "";
if (TABS) {
  document.body.classList.add("dansOnglet");
  const col = document.querySelector(".bandeau"), plus = document.createElement("div"); plus.className = "departPlus";
  plus.innerHTML = `<p class="chapo">A traced surface often leaves its sheet for a few millimetres. See where, put it back, and send it back to VC3D.</p>
    <ul class="atouts"><li><b>Flat page and scan sections</b>, side by side</li><li><b>Automatic tools</b>, always with a preview</li><li><b>Scores and a 3D view</b> to check</li><li><b>Nothing is ever lost</b>: every gesture is saved</li></ul>`;
  col.appendChild(plus);
  // “Open” puts the segment in THIS tab, in place of the start page
  document.addEventListener("click", ev => { const a = ev.target.closest && ev.target.closest('a[href^="tabs.html?s="]'); if (a) { ev.preventDefault(); TABS.open(decodeURIComponent(a.getAttribute("href").split("s=")[1]), TAB_ID); } });
}

async function api(route, body) {
  let r;
  try { r = await fetch(route, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
  catch (e) { offline(true); throw new Error("the server does not answer"); }
  offline(false);
  let j = {}; try { j = await r.json(); } catch (e) { }
  if (!r.ok || j.error) throw new Error(j.error || r.statusText || "error " + r.status);
  return j;
}
function offline(yes) { $("hors").hidden = !yes; if (yes) $("hors").textContent = "⚠ The server does not answer. Start it again with:  python -m surface_enhancer serve  — your work is saved."; }
function state(id, html, kind) { const e = $(id); e.hidden = !html; e.innerHTML = html || ""; e.className = "etat" + (kind ? " " + kind : ""); }
const ok = t => `<b class="okTxt">✓</b> ${t}`, bad = t => `<b class="badTxt">✗</b> ${t}`, warn = t => `<b class="warnTxt">⚠</b> ${t}`;

// ───────────── library and jobs ─────────────
function segmentRow(s) {
  const mm = s.size_mm ? `${num(s.size_mm[1], 1)} × ${num(s.size_mm[0], 1)} mm` : `${num(s.page[1])} × ${num(s.page[0])} px`;
  const status = s.ready ? `<span class="tag ok">✓ ready</span>` : `<span class="tag bad" title="${esc(s.problem)}">✗ cache missing</span>`;
  const from = s.origin && s.origin.kind === "volpkg" ? "VC3D package" : s.origin && s.origin.kind === "upload" ? "upload" : s.origin && s.origin.sample ? "built-in sample" : "local folder";
  return `<article class="seg" data-name="${esc(s.name)}">
    <div class="segTete"><h3>${esc(s.name)}</h3>${status}${s.scroll ? `<span class="tag">${esc(s.scroll)}</span>` : ""}<span class="tag">${from}</span></div>
    <div class="segInfos doux">${mm} · grid ${num(s.grid[1])} × ${num(s.grid[0])} nodes, one every ${s.step} vx · <b>${num(s.gestures)}</b> gesture${s.gestures === 1 ? "" : "s"} · ${esc(s.version || "")} · cache ${size(s.cache_bytes)}
      ${s.missing_blocks ? ` · ${warn(num(s.missing_blocks) + " scan blocks missing")}` : ""}${s.exports.length ? ` · ${s.exports.length} export${s.exports.length > 1 ? "s" : ""}` : ""}<br>last change ${esc(s.modified || "–")}</div>
    <div class="ligne">
      ${s.ready ? `<a class="bouton principal" href="tabs.html?s=${encodeURIComponent(s.name)}">Open</a>
      <a class="bouton" href="/api/s/${encodeURIComponent(s.name)}/download?what=bundle" download title="tifxyz segment + offset field + journal of gestures">⬇ Download .zip</a>` : `<button data-reprepare="${esc(s.name)}" class="principal">Prepare again</button>`}
      <button data-remove="${esc(s.name)}" class="discret" title="Its versions and journal are moved to the trash folder of the data directory; its cache is deleted">Remove…</button>
    </div></article>`;
}
function jobRow(j) {
  const pct = Math.round((j.fraction || 0) * 100), run = j.state === "running";
  const head = run ? `Preparing <b>${esc(j.name)}</b> — ${esc(j.stage || "")} ${pct} %` : j.state === "done" ? ok(`<b>${esc(j.name)}</b> is ready`) : j.state === "cancelled" ? warn(`<b>${esc(j.name)}</b>: preparation cancelled`) : bad(`<b>${esc(j.name)}</b>: preparation ${esc(j.state)}`);
  return `<div class="job ${esc(j.state)}"><div class="ligne"><span>${head}</span>
      ${run ? `<button data-cancel="${esc(j.job)}" class="pousse discret">Cancel</button>` : j.state === "done" ? `<a class="bouton principal pousse" href="tabs.html?s=${encodeURIComponent(j.name)}">Open</a>` : ""}</div>
    ${run ? `<div class="barre" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i style="width:${pct}%"></i></div>` : ""}
    <div class="doux petit">${esc(j.message || "")}</div>
    ${(j.log || []).length && j.state !== "done" ? `<details class="petit"><summary>details</summary><pre>${esc((j.log || []).join("\n"))}${j.log_tail ? "\n" + esc(j.log_tail) : ""}</pre></details>` : ""}</div>`;
}
async function refresh() {
  clearTimeout(timer);
  try {
    HOME = await api("/api/home");
    $("version").textContent = "· " + HOME.version;
    const recent = HOME.jobs.filter(j => j.state === "running" || (Date.now() - Date.parse((j.finished || j.started || "").replace(" ", "T")) < 6 * 3600e3 && j.state !== "done") || (j.state === "done" && Date.now() - Date.parse((j.finished || "").replace(" ", "T")) < 120e3));
    const jobsHtml = recent.map(jobRow).join("");
    if (jobsHtml !== lastJobs) { $("jobs").innerHTML = jobsHtml; lastJobs = jobsHtml; }
    const busy = new Set(HOME.jobs.filter(j => j.state === "running").map(j => j.name));
    const list = HOME.segments.filter(s => !busy.has(s.name));
    $("segments").innerHTML = list.map(segmentRow).join("");
    $("nSeg").textContent = list.length ? `${list.length} prepared` : "";
    $("segVide").hidden = list.length > 0 || busy.size > 0; $("echantillon").hidden = !HOME.sample_available;
    $("dossiers").textContent = `Data: ${HOME.settings.data_dir} · cache: ${HOME.settings.cache_dir} (${size(HOME.settings.cache_free_bytes)} free)`;
    $("recents").innerHTML = HOME.recent_volpkgs.length && !pkg ? "recent: " + HOME.recent_volpkgs.slice(0, 3).map(p => `<button class="lien" data-recent="${esc(p)}" title="${esc(p)}">${esc(p.replace(/\\/g, "/").split("/").pop())}</button>`).join(" ") : "";
    timer = setTimeout(refresh, busy.size ? 1000 : 15000);
  } catch (e) { timer = setTimeout(refresh, 4000); }
}
document.addEventListener("click", async ev => {
  const b = ev.target.closest("button"); if (!b) return;
  try {
    if (b.dataset.cancel) { await api(`/api/jobs/${encodeURIComponent(b.dataset.cancel)}/cancel`, {}); refresh(); }
    else if (b.dataset.remove) askRemove(b.dataset.remove);
    else if (b.dataset.recent) { $("volpkg").value = b.dataset.recent; openVolpkg(); }
    else if (b.dataset.reprepare) { const s = HOME.segments.find(x => x.name === b.dataset.reprepare); await api("/api/prepare", { source: { kind: "path", path: s.source }, volume: s.volume, name: s.name, resume: true, densify_to: 4 }); refresh(); }
    else if (b.dataset.prepare) prepareFromPackage(b.dataset.prepare, b);
  } catch (e) { alertLine(e.message); }
});
function alertLine(t) { $("hors").hidden = false; $("hors").textContent = "✗ " + t; setTimeout(() => { $("hors").hidden = true; }, 9000); }

// ───────────── add a segment ─────────────
function showSurface(info, label) {
  const coarse = info.step > 8, w = info.warnings || [];
  state("surfaceEtat", ok(`<b>${esc(label)}</b> — grid ${num(info.grid[1])} × ${num(info.grid[0])} nodes, one every ${info.step} voxels → flat page ${num(info.page[1])} × ${num(info.page[0])} px`) + w.map(x => "<br>" + warn(esc(x))).join(""), "ok");
  $("densifierLigne").hidden = !coarse; $("densifier").checked = coarse;
  $("densifierTexte").innerHTML = `resample the grid to one node every 4 voxels before retouching <span class="doux">(recommended: yours has one node every ${info.step} voxels; the export can give back your layout)</span>`;
  if (!$("nom").value || $("nom").dataset.auto === "1") { $("nom").value = String(info.id).replace(/[^A-Za-z0-9_.\-]+/g, "_").slice(0, 96); $("nom").dataset.auto = "1"; }
  // the scan it was traced on, when the folder itself names it (never overrides a scan the user already chose)
  const g = info.scan_guess, sel = $("rouleau");
  if (g && sel && !sel.value) { const o = [...sel.options].find(x => x.value === g.url);
    if (o) { sel.value = g.url; pickScroll(); if (typeof loadScanNote === "function") loadScanNote(g); } }
  quote();
}
function quote() {
  const ready = !!source && !!$("volume").value.trim() && /^[A-Za-z0-9][A-Za-z0-9_.\-]*$/.test($("nom").value.trim());
  $("preparer").disabled = !ready;
  // a greyed button says, on the button itself, what is still missing; the step concerned is marked, the done ones are ticked
  const sansScan = !$("volume").value.trim(), sansSegment = !source, steps = document.querySelectorAll(".ajout .pas");
  const manque = [sansScan && "choose the scroll (step 1)", sansSegment && "choose your segment (step 2)", !sansScan && !sansSegment && !ready && "give it a valid name (advanced options)"].filter(Boolean);
  $("preparer").textContent = ready ? "Prepare this segment" : "Prepare this segment — first " + manque.join(", then ");
  $("preparer").title = ready ? "" : "Not possible yet: " + manque.join(", then ") + ". The scan is needed because it is read along your surface.";
  $("preparerPourquoi").innerHTML = ready ? "" : (sansScan ? '<button type="button" class="lien" data-aller="rouleau">↑ go to step 1: the scroll</button> ' : "") + (sansSegment ? '<button type="button" class="lien" data-aller="depot">↑ go to step 2: the segment</button>' : "");
  [sansScan, sansSegment].forEach((m, i) => { if (steps[i]) { steps[i].classList.toggle("manque", m); steps[i].classList.toggle("fait", !m); steps[i].querySelector(".num").textContent = m ? i + 1 : "✓"; } });
  if (!source) { state("devis", ""); return; }
  const i = source.info, need = i.cache_bytes, free = HOME ? HOME.settings.cache_free_bytes : 0, tight = free && need * 1.1 > free;
  state("devis", `${tight ? bad("Not enough room in the cache folder:") : "Preload:"} about <b>${size(need)}</b> in the cache folder (${size(free)} free). ` +
    `Time depends on your disk and connection: seconds for a few millimetres, up to an hour for a page of several centimetres read over the network.`, tight ? "bad" : "");
}
async function upload(file) {
  if (!file) return;
  if (!/\.zip$/i.test(file.name)) { state("surfaceEtat", bad("This is not a .zip file. Zip the segment folder (the one holding x.tif, y.tif, z.tif, meta.json) and drop the zip."), "bad"); return; }
  source = null; quote();
  state("surfaceEtat", `Uploading ${esc(file.name)} (${size(file.size)})… <span id="upPct">0 %</span><div class="barre"><i id="upBar"></i></div>`);
  const x = new XMLHttpRequest(); x.open("POST", "/api/upload?name=" + encodeURIComponent(file.name)); x.setRequestHeader("Content-Type", "application/zip");
  x.upload.onprogress = e => { if (e.lengthComputable && $("upBar")) { const p = Math.round(100 * e.loaded / e.total); $("upBar").style.width = p + "%"; $("upPct").textContent = p + " %"; } };
  x.onerror = () => state("surfaceEtat", bad("The upload failed: the server does not answer."), "bad");
  x.onload = () => {
    let j = {}; try { j = JSON.parse(x.responseText); } catch (e) { }
    if (x.status !== 200 || j.error) { state("surfaceEtat", bad(esc(j.error || "the upload failed (" + x.status + ")")), "bad"); return; }
    source = { kind: "upload", id: j.upload, info: j.summary }; showSurface(j.summary, file.srLabel || file.name);
  };
  x.send(file);
}
$("fichier").onchange = ev => upload(ev.target.files[0]);
// A segment FOLDER (chosen, or dropped): its four files are packed into a zip here in the page, then sent like any zip.
const WANTED = ["x.tif", "y.tif", "z.tif", "meta.json", "mask.tif"];
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = u => { let c = 0xFFFFFFFF; for (let i = 0; i < u.length; i++) c = CRC[(c ^ u[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
async function zipOf(folder, files) {                    // zip without compression (the .tif are small; nothing leaves this computer)
  const enc = new TextEncoder(), parts = [], central = []; let offset = 0;
  for (const f of files) {
    const data = new Uint8Array(await f.arrayBuffer()), name = enc.encode(folder + "/" + f.name), crc = crc32(data);
    const h = new DataView(new ArrayBuffer(30)); h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true); h.setUint16(12, 0x21, true);
    h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true); h.setUint16(26, name.length, true);
    const c = new DataView(new ArrayBuffer(46)); c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x0800, true); c.setUint16(14, 0x21, true);
    c.setUint32(16, crc, true); c.setUint32(20, data.length, true); c.setUint32(24, data.length, true); c.setUint16(28, name.length, true); c.setUint32(42, offset, true);
    parts.push(h.buffer, name, data); central.push(c.buffer, name); offset += 30 + name.length + data.length;
  }
  const size = central.reduce((n, b) => n + b.byteLength, 0), e = new DataView(new ArrayBuffer(22)); e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true); e.setUint32(12, size, true); e.setUint32(16, offset, true);
  return new Blob([...parts, ...central, e.buffer], { type: "application/zip" });
}
async function uploadFolder(entries, fallbackName) {     // entries: [{ file, path }] with path relative to what was chosen
  const tifs = entries.filter(e => e.file.name === "x.tif").sort((a, b) => a.path.split("/").length - b.path.split("/").length);
  if (!tifs.length) { state("surfaceEtat", bad("No x.tif in this folder: choose the folder that holds x.tif, y.tif, z.tif and meta.json (in a VC3D package: one folder of paths/)."), "bad"); return; }
  const dir = tifs[0].path.split("/").slice(0, -1).join("/"), inside = entries.filter(e => e.path.split("/").slice(0, -1).join("/") === dir && WANTED.includes(e.file.name));
  const missing = WANTED.slice(0, 4).filter(n => !inside.some(e => e.file.name === n));
  if (missing.length) { state("surfaceEtat", bad("This folder is not a complete tifxyz segment: " + esc(missing.join(", ")) + " missing."), "bad"); return; }
  const name = (dir.split("/").pop() || fallbackName || "segment").replace(/[^A-Za-z0-9_.\-]+/g, "_");
  state("surfaceEtat", `Reading the folder ${esc(name)}…`); guessScroll(dir || fallbackName || "");
  try { const z = new File([await zipOf(name, inside.map(e => e.file))], name + ".zip", { type: "application/zip" }); z.srLabel = name + " (folder)"; upload(z); } catch (e) { state("surfaceEtat", bad("This folder could not be read: " + esc(e.message)), "bad"); }
}
$("dossierIn").onchange = ev => { const fs = [...ev.target.files]; if (fs.length) uploadFolder(fs.map(f => ({ file: f, path: f.webkitRelativePath || f.name })), "segment"); ev.target.value = ""; };
$("choisirDossier").onclick = ev => { ev.stopPropagation(); $("dossierIn").click(); }; $("choisirZip").onclick = ev => { ev.stopPropagation(); $("fichier").click(); };
async function readDropped(entry, prefix, out, depth) {  // a dropped folder, read two levels deep at most
  if (entry.isFile) { const f = await new Promise((ok, ko) => entry.file(ok, ko)); out.push({ file: f, path: prefix + f.name }); }
  else if (entry.isDirectory && depth < 3) { const rd = entry.createReader(); for (;;) { const batch = await new Promise((ok, ko) => rd.readEntries(ok, ko)); if (!batch.length) break; for (const e of batch) await readDropped(e, prefix + entry.name + "/", out, depth + 1); } }
}
const drop = $("depot");
["dragenter", "dragover"].forEach(t => drop.addEventListener(t, ev => { ev.preventDefault(); drop.classList.add("survol"); }));
["dragleave", "drop"].forEach(t => drop.addEventListener(t, ev => { ev.preventDefault(); drop.classList.remove("survol"); }));
drop.addEventListener("drop", async ev => {
  const it = ev.dataTransfer.items && ev.dataTransfer.items[0], entry = it && it.webkitGetAsEntry ? it.webkitGetAsEntry() : null, first = ev.dataTransfer.files[0];
  if (entry && entry.isDirectory) { const out = []; try { await readDropped(entry, "", out, 0); } catch (e) { } uploadFolder(out, entry.name); }
  else upload(first);
});
drop.addEventListener("keydown", ev => { if (ev.target === drop && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); $("dossierIn").click(); } });
function tab(which) {
  const w = which === true ? "zip" : which === false ? "chemin" : which;
  for (const [id, pane, key] of [["ongletZip", "paneZip", "zip"], ["ongletChemin", "paneChemin", "chemin"]]) {
    $(id).classList.toggle("actif", key === w); $(id).setAttribute("aria-selected", key === w); $(pane).hidden = key !== w; }
}
$("ongletZip").onclick = () => tab("zip"); $("ongletChemin").onclick = () => tab("chemin");
async function inspect() {
  const p = $("chemin").value.trim(); if (!p) { state("surfaceEtat", bad("Type the path of the folder that holds x.tif, y.tif, z.tif and meta.json."), "bad"); return; }
  state("surfaceEtat", "Checking…"); source = null; quote();
  try { const info = await api("/api/inspect", { path: p }); source = { kind: "path", path: info.path, info }; showSurface(info, info.folder); }
  catch (e) { state("surfaceEtat", bad(esc(e.message)), "bad"); }
}
$("inspecter").onclick = inspect; $("chemin").addEventListener("keydown", ev => { if (ev.key === "Enter") inspect(); });
async function checkVolume() {
  const v = $("volume").value.trim(); volumeOk = null;
  if (!v) { state("volumeEtat", bad("Give the address of the scan volume."), "bad"); return; }
  state("volumeEtat", "Opening the volume…");
  try {
    const d = await api("/api/volume/check", { volume: v }); volumeOk = d;
    state("volumeEtat", (scanNote ? ok(scanNote) + "<br>" : "") + ok(`${d.remote ? "Remote" : "Local"} volume, ${num(d.shape[2])} × ${num(d.shape[1])} × ${num(d.shape[0])} voxels (x × y × z), ${esc(d.dtype)}` + (d.voxel_um ? `, ${d.voxel_um} µm per voxel` : `. ${warn("Voxel size not found in its name: type it below if you want millimetre scales.")}`)), "ok");
  } catch (e) { state("volumeEtat", bad(esc(e.message)), "bad"); }
  quote();
}
let scanNote = "";                                // “detected from …”, shown with the result of the check of the volume
function loadScanNote(g) { scanNote = `Scan detected from your segment (${esc(g.how)}): <b>${esc(g.scroll)}</b>${g.um ? ", " + g.um + " µm" : ""}. Change it above if it is not the right one.`; }
$("rouleau").addEventListener("change", () => { scanNote = ""; });
$("verifier").onclick = checkVolume; $("volume").addEventListener("input", quote); $("volume").addEventListener("keydown", ev => { if (ev.key === "Enter") checkVolume(); });
$("nom").addEventListener("input", () => { $("nom").dataset.auto = "0"; quote(); });
$("preparer").onclick = async () => {
  const um = parseFloat($("um").value.replace(",", "."));
  const body = { source: source.kind === "upload" ? { kind: "upload", id: source.id } : { kind: "path", path: source.path }, volume: $("volume").value.trim(), name: $("nom").value.trim(),
    mirror: $("miroirOpt").checked, densify_to: $("densifier").checked && source.info.step > 8 ? 4 : null, voxel_um: isFinite(um) && um > 0 ? um : null };
  $("preparer").disabled = true;
  try { await api("/api/prepare", body); state("devis", ok("Preparation started: follow it at the top of the page."), "ok"); source = null; state("surfaceEtat", ""); $("nom").value = ""; window.scrollTo({ top: 0, behavior: "smooth" }); refresh(); }
  catch (e) { state("devis", bad(esc(e.message)), "bad"); $("preparer").disabled = false; }
};
$("preparerPourquoi").addEventListener("click", ev => { const b = ev.target.closest("[data-aller]"); if (!b) return; const e = $(b.dataset.aller), p = e.closest(".pas"); p.scrollIntoView({ behavior: "smooth", block: "center" }); p.classList.remove("flash"); void p.offsetWidth; p.classList.add("flash"); e.focus({ preventScroll: true }); });
$("essai").onclick = async () => { try { await api("/api/sample", {}); refresh(); } catch (e) { alertLine(e.message); } };

// ───────────── VC3D volume package ─────────────
function packageRows() {
  const f = $("filtre").value.trim().toLowerCase(), all = pkg.segments, list = all.filter(s => !f || (s.id || s.folder).toLowerCase().includes(f));
  $("nVc").textContent = `${list.length} of ${all.length} segment${all.length === 1 ? "" : "s"}` + (list.length > 200 ? " (first 200 shown)" : "");
  $("volpkgSegments").innerHTML = list.slice(0, 200).map(s => `<div class="rang"><div><b>${esc(s.id || s.folder)}</b>${s.retouched ? ` <span class="tag">retouched</span>` : ""}
      <div class="doux petit">${s.step ? "one node every " + s.step + " vx" : ""}${s.area_cm2 ? " · " + num(s.area_cm2, 1) + " cm²" : ""}${s.modified ? " · " + esc(s.modified) : ""}${s.loadable ? "" : " · " + bad(esc(s.problem || "not loadable"))}</div></div>
      <button data-prepare="${esc(s.id || s.folder)}" ${s.loadable ? "" : "disabled"} title="${s.loadable ? "Preload this segment with the volume chosen above" : esc(s.problem || "")}">Prepare</button></div>`).join("") ||
    `<div class="videBloc">${all.length ? "No segment matches this filter." : "This package holds no segment (no folder with a meta.json in its segments folders)."}</div>`;
}
async function openVolpkg() {
  const p = $("volpkg").value.trim(); if (!p) { state("volpkgEtat", bad("Type the path of the volume package (the folder that holds volumes/ and paths/)."), "bad"); return; }
  state("volpkgEtat", "Opening…"); $("volpkgVue").hidden = true;
  try {
    pkg = await api("/api/volpkg/open", { path: p });
    state("volpkgEtat", pkg.warnings.length ? pkg.warnings.map(w => warn(esc(w))).join("<br>") : "", "");
    $("volpkgNom").textContent = `${pkg.name} — ${pkg.kind === "project" ? "VC3D project file" : pkg.kind === "folder" ? "volume package" : "folder of segments"}`;
    $("volpkgVolume").innerHTML = pkg.volumes.filter(v => !v.problem).map(v => `<option value="${esc(v.location)}">${esc(v.name)}${v.voxel_um ? " · " + v.voxel_um + " µm" : ""}${v.remote ? " · remote" : ""}</option>`).join("") +
      `<option value="">${pkg.volumes.length ? "another volume: the address typed in “Add a segment”, step 2" : "no volume in this package: use the address typed in “Add a segment”, step 2"}</option>`;
    $("volpkgVue").hidden = false; packageRows();
  } catch (e) { pkg = null; state("volpkgEtat", bad(esc(e.message)), "bad"); }
}
$("ouvrirVolpkg").onclick = openVolpkg; $("volpkg").addEventListener("keydown", ev => { if (ev.key === "Enter") openVolpkg(); }); $("filtre").addEventListener("input", () => pkg && packageRows());
async function prepareFromPackage(id, button) {
  const s = pkg.segments.find(x => (x.id || x.folder) === id), volume = $("volpkgVolume").value || $("volume").value.trim();
  if (!volume) { state("volpkgEtat", bad("Choose a volume, or type its address in “Add a segment”, step 2."), "bad"); return; }
  button.disabled = true;
  try { await api("/api/prepare", { source: { kind: "volpkg", volpkg: pkg.path, segment: id }, volume, name: String(id).replace(/[^A-Za-z0-9_.\-]+/g, "_").slice(0, 96), densify_to: s.step > 8 ? 4 : null }); state("volpkgEtat", ok(`Preparation of ${esc(id)} started: follow it at the top of the page.`), "ok"); window.scrollTo({ top: 0, behavior: "smooth" }); refresh(); }
  catch (e) { state("volpkgEtat", bad(esc(e.message)), "bad"); button.disabled = false; }
}

// ───────────── dialogs ─────────────
const dialogs = ["aideDlg", "supprDlg"]; let removing = null;
const closeDialogs = () => dialogs.forEach(d => { $(d).hidden = true; });
document.querySelectorAll("[data-fermer]").forEach(b => b.addEventListener("click", closeDialogs));
dialogs.forEach(d => $(d).addEventListener("pointerdown", ev => { if (ev.target === $(d)) closeDialogs(); }));
window.addEventListener("keydown", ev => { if (ev.key === "Escape") closeDialogs(); });
$("aideBtn").onclick = () => { $("aideDlg").hidden = false; };
function askRemove(name) {
  removing = name; $("supprNom").value = ""; $("supprOk").disabled = true; state("supprEtat", "");
  $("supprTexte").innerHTML = `Remove <b>${esc(name)}</b> from Surface Enhancer? Its versions, journal and exports are <b>moved</b> to the <code>trash</code> folder of the data directory (you can put them back by hand); its preloaded cache is deleted. The original segment is not touched.`;
  $("supprDlg").hidden = false; $("supprNom").focus();
}
$("supprNom").addEventListener("input", () => { $("supprOk").disabled = $("supprNom").value !== removing; });
$("supprOk").onclick = async () => { try { await api(`/api/s/${encodeURIComponent(removing)}/remove`, { confirm: removing }); closeDialogs(); refresh(); } catch (e) { state("supprEtat", bad(esc(e.message)), "bad"); } };

refresh().then(() => { window.READY = true; });

// ───────────── scroll picker (25 Nov): the public scans are listed, so nobody has to type an address ─────────────
let PUBLIC = [];
function normScroll(t) { return String(t || "").toLowerCase().replace(/[\s._]/g, "").replace(/pherc0*(\d)/, "pherc$1"); }
function pickScroll() {
  const v = $("rouleau").value; $("volumeLibre").hidden = v !== "autre";
  if (v === "autre") { $("volume").value = ""; state("volumeEtat", ""); quote(); $("volume").focus(); return; }
  $("volume").value = v; quote(); if (v) checkVolume();
}
function guessScroll(text) {
  if (!PUBLIC.length || $("rouleau").value) return;
  const m = /PHerc[\s._]?(Paris\d|MAN\w*|\d{3,4}[A-Za-z]?)/i.exec(text || ""); if (!m) return;
  const key = normScroll("PHerc" + m[1]), o = [...$("rouleau").options].find(x => x.dataset.first && normScroll(x.dataset.scroll) === key);
  if (o) { $("rouleau").value = o.value; pickScroll(); }
}
(async () => {
  try {
    PUBLIC = (await (await fetch("public_volumes.json", { cache: "no-store" })).json()).volumes; const seen = {};
    $("rouleau").innerHTML = '<option value="">choose a scroll…</option>' + PUBLIC.map(v => { const first = !seen[v.scroll]; seen[v.scroll] = 1;
      return `<option value="${esc(v.url)}" data-scroll="${esc(v.scroll)}" ${first ? 'data-first="1"' : ""}>${esc(v.scroll)} — ${v.um ? v.um + " µm" : ""} (scan ${esc(v.volume.slice(0, 8))})</option>`; }).join("") + '<option value="autre">another scan: I will paste its address…</option>';
  } catch (e) { $("rouleau").innerHTML = '<option value="autre">paste the address of the scan…</option>'; $("rouleau").value = "autre"; $("volumeLibre").hidden = false; }
  $("rouleau").onchange = pickScroll;
  const fichier = $("fichier"); fichier.addEventListener("change", () => { if (fichier.files[0]) guessScroll(fichier.files[0].name); });
  $("chemin").addEventListener("change", () => guessScroll($("chemin").value));
})();
