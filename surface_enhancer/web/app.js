/* RETOUCHEUR DE SURFACE — page. Tout à la souris + quelques touches (barre du bas). Chaque geste part au serveur et y est écrit tout de suite.
   Repères : pixel de la page (u = colonne, v = ligne) ; nœud = pixel / pas ; d = voxels le long de la normale (haut de la coupe = d négatif). */
"use strict";
const SEG = new URLSearchParams(location.search).get("s") || "", API = "/api/s/" + encodeURIComponent(SEG);
const $ = id => document.getElementById(id);
const fr = (x, n = 1) => x == null || !isFinite(x) ? "–" : x.toLocaleString("en-US", { minimumFractionDigits: n, maximumFractionDigits: n });
const OI = { orange: "#E69F00", ciel: "#56B4E9", vert: "#009E73", jaune: "#F0E442", bleu: "#0072B2", vermillon: "#D55E00", violet: "#CC79A7" };
let E = null;                                  // état du serveur
const V = { x: 0, y: 0, s: 0.2, miroir: false, couche: 0, encre: "", opEncre: 0.9, zones: true, score: false, pics: true, vue: "2d", fibres: false };
let outil = "regarder", point = null, epingle = false, survol = null, surbrillance = null, messageT = 0;
const cv = $("page"), cx = cv.getContext("2d"), session = Math.random().toString(36).slice(2, 8);
let compteur = 0, horloge = 0, demande = false, TU = 256, NIV = 4, PAS = 4, CAR = 8, DEMI = 40, HMAX = 32;
const dpr = () => window.devicePixelRatio || 1;

// ───────────── échanges avec le serveur ─────────────
async function api(route, corps) {
  const r = await fetch(route, corps === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
  let j = {}; try { j = await r.json(); } catch (e) { } if (!r.ok || j.error) { const err = new Error(j.error || r.statusText || "the server did not answer"); err.status = r.status; throw err; } return j;
}
async function binaire(route) {
  const b = await (await fetch(route)).arrayBuffer(), n = new DataView(b).getUint32(0, true), e = JSON.parse(new TextDecoder().decode(new Uint8Array(b, 4, n))), t = {};
  for (const [k, d] of Object.entries(e.tableaux)) { const s = b.slice(4 + n + d.debut, 4 + n + d.debut + d.octets); t[k] = d.type === "float32" ? new Float32Array(s) : new Uint8Array(s); t[k].forme = d.forme; }
  return [e, t];
}
async function binaire2(route, corps) {            // 25/11 : comme binaire(), en GET ou en POST, avec le message d'erreur du serveur
  const r = await fetch(route, corps === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
  if (!r.ok) { let j = {}; try { j = await r.json(); } catch (e) { } throw new Error(j.error || r.statusText); }
  const b = await r.arrayBuffer(), n = new DataView(b).getUint32(0, true), e = JSON.parse(new TextDecoder().decode(new Uint8Array(b, 4, n))), t = {};
  for (const [k, d] of Object.entries(e.tableaux)) { const q = b.slice(4 + n + d.debut, 4 + n + d.debut + d.octets); t[k] = d.type === "float32" ? new Float32Array(q) : new Uint8Array(q); t[k].forme = d.forme; }
  return [e, t];
}
function message(txt, erreur) { const m = $("message"); m.textContent = txt || ""; m.className = "petit " + (erreur ? "erreur" : "doux"); clearTimeout(messageT); if (txt && !erreur) messageT = setTimeout(() => { m.textContent = ""; }, 9000); }
function majSauve(etat) {
  const s = $("sauve");
  if (etat === "encours") { s.textContent = "saving…"; s.className = "encours"; }
  else if (etat === "erreur") { s.textContent = "NOT saved — server unreachable"; s.className = "erreur"; }
  else { s.textContent = E.enregistre ? `✓ saved at ${E.enregistre} · ${E.version}` : `✓ nothing to save · ${E.version}`; s.className = ""; }
}

// ───────────── repères page ⇄ écran ─────────────
const ecran = (u, v) => [((V.miroir ? E.page[1] - u : u) - V.x) * V.s, (v - V.y) * V.s];
const versPage = (px, py) => { const um = px / V.s + V.x; return [V.miroir ? E.page[1] - um : um, py / V.s + V.y]; };
function demander() { if (!demande) { demande = true; requestAnimationFrame(dessiner); } }
function centrer(u, v, s) { if (s) V.s = s; const um = V.miroir ? E.page[1] - u : u; V.x = um - cv.clientWidth / V.s / 2; V.y = v - cv.clientHeight / V.s / 2; demander(); memoriser(); }
function memoriser() { try { localStorage.setItem("surface_enhancer_" + E.nom, JSON.stringify({ x: V.x, y: V.y, s: V.s, couche: V.couche, encre: V.encre, zones: V.zones, score: V.score, pics: V.pics, miroir: V.miroir, portee: $("portee").value, borne: $("borne").value })); } catch (e) { } }

// ───────────── tuiles (page à plat et calques d'encre) ─────────────
const tuiles = new Map();
const adresse = t => t.type === "ct" ? `${API}/tile?n=${t.L}&y=${t.ty}&x=${t.tx}&c=${t.c}&g=${session}${t.g}` : `${API}/ink?nom=${t.type}&n=${t.L}&y=${t.ty}&x=${t.tx}`;
function tuile(type, L, ty, tx, creer = true) {
  const cle = type === "ct" ? `ct/${V.couche}/${L}/${ty}/${tx}` : `${type}/${L}/${ty}/${tx}`; let t = tuiles.get(cle);
  if (!t && creer) { t = { img: new Image(), pret: false, type, L, ty, tx, c: V.couche, g: ++compteur }; t.img.onload = () => { t.pret = true; demander(); }; t.img.src = adresse(t); tuiles.set(cle, t); }
  if (t) t.vu = ++horloge; return t;
}
function invalider(px) {                         // une retouche a changé ce rectangle de la page : recharger les tuiles touchées (l'ancienne image reste jusqu'à la nouvelle)
  const [y0, y1, x0, x1] = px;
  for (const t of tuiles.values()) {
    if (t.type !== "ct") continue; const k = TU << t.L;
    if (t.tx * k < x1 && (t.tx + 1) * k > x0 && t.ty * k < y1 && (t.ty + 1) * k > y0) { const g = ++compteur, im = new Image(); t.g = g; im.onload = () => { if (t.g === g) { t.img = im; t.pret = true; demander(); } }; im.src = adresse(t); }
  }
}
function menage() { if (tuiles.size < 900) return; const a = [...tuiles.entries()].sort((p, q) => p[1].vu - q[1].vu); for (let i = 0; i < a.length - 600; i++) tuiles.delete(a[i][0]); }

// ───────────── scores et zones : calques à la résolution des nœuds ─────────────
let SC = null, ZN = null; const cvScore = document.createElement("canvas"), cvZones = document.createElement("canvas");
const sc = (c, t, s) => SC.m[c * SC.th * SC.tw + t * SC.tw + s];
const classe = n => n >= 80 ? 0 : n >= 60 ? 1 : n >= 40 ? 2 : 3;
function peindreScore(t0, t1, s0, s1) {
  const C = CAR, w = (s1 - s0) * C, h = (t1 - t0) * C; if (w <= 0 || h <= 0) return; const im = new ImageData(w, h), d = im.data;
  for (let t = t0; t < t1; t++) for (let s = s0; s < s1; s++) {
    const n = sc(0, t, s); if (!(n === n)) continue; const k = classe(n); if (!k) continue;
    const col = k === 1 ? [240, 228, 66] : k === 2 ? [230, 159, 0] : [213, 94, 0];
    for (let y = 0; y < C; y++) for (let x = 0; x < C; x++) {
      const X = s * C + x, Y = t * C + y, o = ((t - t0) * C + y) * w * 4 + ((s - s0) * C + x) * 4;
      const trait = k === 1 ? (X % 4 === 1 && Y % 4 === 1) : k === 2 ? ((X + Y) % 4 === 0) : ((X + Y) % 4 === 0 || (X - Y + 4096) % 4 === 0);
      d[o] = col[0]; d[o + 1] = col[1]; d[o + 2] = col[2]; d[o + 3] = trait ? 245 : (k === 1 ? 0 : k === 2 ? 40 : 75);
    }
  }
  cvScore.getContext("2d").putImageData(im, s0 * C, t0 * C);
}
function peindreZones(v0, v1, u0, u1) {
  const gh = E.grille[0], gw = E.grille[1]; v0 = Math.max(0, v0 - 1); u0 = Math.max(0, u0 - 1); v1 = Math.min(gh, v1 + 1); u1 = Math.min(gw, u1 + 1);
  const w = u1 - u0, h = v1 - v0; if (w <= 0 || h <= 0) return; const im = new ImageData(w, h), d = im.data, z = (v, u) => v >= 0 && u >= 0 && v < gh && u < gw && ZN[v * gw + u];
  for (let v = v0; v < v1; v++) for (let u = u0; u < u1; u++) {
    if (!ZN[v * gw + u]) continue; const o = ((v - v0) * w + (u - u0)) * 4, bord = !z(v - 1, u) || !z(v + 1, u) || !z(v, u - 1) || !z(v, u + 1);
    d[o] = 86; d[o + 1] = 180; d[o + 2] = 233; d[o + 3] = bord ? 255 : ((u - v + 8192) % 7 === 0 ? 150 : 0);
  }
  cvZones.getContext("2d").putImageData(im, u0, v0);
}
async function chargerScores() {
  const [e, t] = await binaire(API + "/scores"); SC = { th: e.th, tw: e.tw, m: t.maintenant, o: t.origine, marq: t.marquees, champs: e.champs }; E.bilan = e.bilan; E.criteres = e.criteres;
  cvScore.width = SC.tw * CAR; cvScore.height = SC.th * CAR; peindreScore(0, SC.th, 0, SC.tw);
}
async function chargerZones() {
  ZN = new Uint8Array(await (await fetch(API + "/marks")).arrayBuffer()); cvZones.width = E.grille[1]; cvZones.height = E.grille[0]; peindreZones(0, E.grille[0], 0, E.grille[1]);
}

// ───────────── dessin de la page ─────────────
function dessiner() {
  demande = false; if (!E || V.vue !== "2d") return;
  const w = cv.clientWidth, h = cv.clientHeight, r = dpr(), [H, W] = E.page;
  if (cv.width !== Math.round(w * r) || cv.height !== Math.round(h * r)) { cv.width = Math.round(w * r); cv.height = Math.round(h * r); }
  cx.setTransform(r, 0, 0, r, 0, 0); cx.fillStyle = "#0b0a08"; cx.fillRect(0, 0, w, h);
  const a = V.miroir ? -V.s : V.s, e = V.miroir ? (W - V.x) * V.s : -V.x * V.s, enPage = () => cx.setTransform(a * r, 0, 0, V.s * r, e * r, -V.y * V.s * r), enEcran = () => cx.setTransform(r, 0, 0, r, 0, 0);
  const c0 = versPage(0, 0), c1 = versPage(w, h), ua = Math.max(0, Math.min(c0[0], c1[0])), ub = Math.min(W, Math.max(c0[0], c1[0])), va = Math.max(0, c0[1]), vb = Math.min(H, c1[1]);
  const L = Math.max(0, Math.min(NIV, Math.floor(Math.log2(1 / (V.s * r)) + 0.15))), rab = 0.6 / V.s; let attente = 0;
  enPage(); cx.save(); cx.beginPath(); cx.rect(0, 0, W, H); cx.clip(); cx.imageSmoothingEnabled = V.s * r < 3;
  const couche = (type, Lc, creer) => {
    const k = TU << Lc;
    for (let ty = Math.floor(va / k); ty * k < vb; ty++) for (let tx = Math.floor(ua / k); tx * k < ub; tx++) {
      const t = tuile(type, Lc, ty, tx, creer); if (!t) continue; if (!t.pret) { if (Lc === L) attente++; continue; }
      cx.drawImage(t.img, tx * k, ty * k, t.img.naturalWidth * (1 << Lc) + rab, t.img.naturalHeight * (1 << Lc) + rab);
    }
  };
  for (let Lc = NIV; Lc >= L; Lc--) couche("ct", Lc, Lc === NIV || Lc === L);
  if (V.encre) {                                 // encre en jaune sur le scan assombri
    cx.globalAlpha = 0.55 * V.opEncre; cx.fillStyle = "#000"; cx.fillRect(0, 0, W, H); cx.globalAlpha = V.opEncre;
    for (let Lc = NIV; Lc >= L; Lc--) couche(V.encre, Lc, Lc === L); cx.globalAlpha = 1;
  }
  cx.imageSmoothingEnabled = V.s * PAS * r < 1.5;
  if (V.zones && ZN) cx.drawImage(cvZones, -PAS / 2, -PAS / 2, E.grille[1] * PAS, E.grille[0] * PAS);
  if (V.score && SC) cx.drawImage(cvScore, -PAS / 2, -PAS / 2, SC.tw * CAR * PAS, SC.th * CAR * PAS);
  if (V.fibres && FB) cx.drawImage(cvFib, FB.x0, FB.x0, FB.nx * FB.pas, FB.ny * FB.pas);
  if (AP && AP.cv) cx.drawImage(AP.cv, -PAS / 2, -PAS / 2, E.grille[1] * PAS, E.grille[0] * PAS);        // aperçu d'un geste automatique : ce qui bougerait
  if (SJ && SJ.cv) {                              // carte des sauts de feuille, et le chiffre de chaque zone
    cx.drawImage(SJ.cv, -PAS / 2, -PAS / 2, E.grille[1] * PAS, E.grille[0] * PAS); const t = 13 / V.s; cx.font = `700 ${t}px Segoe UI`; cx.textAlign = "center"; cx.textBaseline = "middle";
    for (const z of SJ.e.zones) { const x = z.u * PAS, y = z.v * PAS, txt = (z.feuilles < 0 ? "▲" : "▼") + Math.abs(z.feuilles); cx.save(); if (V.miroir) { cx.translate(x, y); cx.scale(-1, 1); cx.translate(-x, -y); }
      cx.fillStyle = "rgba(0,0,0,.8)"; cx.fillRect(x - t * 1.3, y - t * 0.85, t * 2.6, t * 1.7); cx.fillStyle = z.feuilles < 0 ? OI.orange : OI.ciel; cx.fillText(txt, x, y); cx.restore(); }
  }
  cx.restore(); enEcran();
  const cote = CAR * PAS * V.s;                   // taille d'un carreau à l'écran
  if (V.score && SC && cote >= 26) {              // chiffres : la note du carreau, et la lettre du critère qui coûte le plus
    cx.font = `600 ${Math.min(15, cote / 2.6)}px Segoe UI, sans-serif`; cx.textAlign = "center"; cx.textBaseline = "middle"; cx.lineWidth = 3; cx.strokeStyle = "rgba(0,0,0,.85)";
    const k = CAR * PAS;
    for (let t = Math.max(0, Math.floor(va / k)); t < Math.min(SC.th, Math.ceil(vb / k)); t++) for (let s = Math.max(0, Math.floor(ua / k)); s < Math.min(SC.tw, Math.ceil(ub / k)); s++) {
      const n = sc(0, t, s); if (!(n === n)) continue; const [x, y] = ecran((s + 0.5) * k - PAS / 2, (t + 0.5) * k - PAS / 2), txt = Math.round(n) + (cote >= 44 && n < 80 ? " " + "DNMGV"[sc(7, t, s)] : "");
      cx.fillStyle = n >= 80 ? "rgba(255,255,255,.55)" : "#fff"; cx.strokeText(txt, x, y); cx.fillText(txt, x, y);
      cx.strokeStyle = "rgba(0,0,0,.35)"; cx.lineWidth = 1; cx.strokeRect(x - cote / 2, y - cote / 2, cote, cote); cx.lineWidth = 3; cx.strokeStyle = "rgba(0,0,0,.85)";
    }
  }
  if (V.fibres && FB && FB.pas * V.s >= 26) {     // chiffres du calque « fibre score » : la note de chaque fenêtre
    cx.font = `600 ${Math.min(14, FB.pas * V.s / 2.4)}px Segoe UI, sans-serif`; cx.textAlign = "center"; cx.textBaseline = "middle"; cx.lineWidth = 3; cx.strokeStyle = "rgba(0,0,0,.85)";
    for (let i = Math.max(0, Math.floor((va - FB.x0) / FB.pas)); i < Math.min(FB.ny, Math.ceil((vb - FB.x0) / FB.pas)); i++) for (let j = Math.max(0, Math.floor((ua - FB.x0) / FB.pas)); j < Math.min(FB.nx, Math.ceil((ub - FB.x0) / FB.pas)); j++) {
      const n = FB.m[i * FB.nx + j]; if (!(n === n)) continue; const [x, y] = ecran(FB.x0 + (j + 0.5) * FB.pas, FB.x0 + (i + 0.5) * FB.pas), txt = String(Math.round(n));
      cx.fillStyle = n >= 60 ? "rgba(190,225,255,.6)" : "#bfe3ff"; cx.strokeText(txt, x, y); cx.fillText(txt, x, y);
    }
  }
  if (surbrillance) {                             // le carreau où « pire carreau » vient de t'amener : double cadre noir et blanc
    const k = CAR * PAS, [x0, y0] = ecran(surbrillance.s * k - PAS / 2, surbrillance.t * k - PAS / 2), [x1, y1] = ecran((surbrillance.s + 1) * k - PAS / 2, (surbrillance.t + 1) * k - PAS / 2);
    cx.lineWidth = 5; cx.strokeStyle = "#000"; cx.strokeRect(Math.min(x0, x1), y0, Math.abs(x1 - x0), y1 - y0); cx.lineWidth = 2; cx.strokeStyle = "#fff"; cx.setLineDash([8, 5]); cx.strokeRect(Math.min(x0, x1), y0, Math.abs(x1 - x0), y1 - y0); cx.setLineDash([]);
  }
  const trace = (pts, R, couleur, alpha) => {     // un trait de pinceau, à sa vraie largeur
    if (!pts.length) return; cx.globalAlpha = alpha; cx.strokeStyle = couleur; cx.fillStyle = couleur; cx.lineWidth = Math.max(2, 2 * R * PAS * V.s); cx.lineCap = "round"; cx.lineJoin = "round"; cx.beginPath();
    pts.forEach((p, i) => { const [x, y] = ecran(p[1] * PAS, p[0] * PAS); i ? cx.lineTo(x, y) : cx.moveTo(x, y); }); if (pts.length === 1) { const [x, y] = ecran(pts[0][1] * PAS, pts[0][0] * PAS); cx.lineTo(x + 0.01, y); } cx.stroke(); cx.globalAlpha = 1; cx.lineCap = "butt";
  };
  for (const t of region) trace(t.points, t.rayon, OI.violet, 0.4);
  if (pinceau) trace(pinceau.points, pinceau.rayon, { aimant: OI.vert, bord: OI.orange, bord2: OI.ciel, pousser: OI.jaune, marquer: OI.ciel, gomme: "#fff", feuille: OI.violet }[outil] || "#fff", 0.45);
  if (point) {                                    // les deux coupes sur la page : ↔ trait plein orange, ↕ tirets bleus (forme + couleur)
    const wc = COUPE.w || 100, [x, y] = ecran(point.u + 0.5, point.v + 0.5), l = wc * V.s;
    for (const [dx, dy, col, tirets] of [[l, 0, OI.orange, []], [0, l, OI.ciel, [7, 5]]]) {
      cx.setLineDash(tirets); cx.lineWidth = 4; cx.strokeStyle = "rgba(0,0,0,.8)"; cx.beginPath(); cx.moveTo(x - dx, y - dy); cx.lineTo(x + dx, y + dy); cx.stroke();
      cx.lineWidth = 2; cx.strokeStyle = col; cx.beginPath(); cx.moveTo(x - dx, y - dy); cx.lineTo(x + dx, y + dy); cx.stroke();
    }
    cx.setLineDash([]); cx.fillStyle = epingle ? "#fff" : "rgba(255,255,255,.6)"; cx.strokeStyle = "#000"; cx.lineWidth = 2;
    if (epingle) { cx.fillRect(x - 5, y - 5, 10, 10); cx.strokeRect(x - 5, y - 5, 10, 10); } else { cx.beginPath(); cx.arc(x, y, 4, 0, 7); cx.fill(); cx.stroke(); }
    if (COUPE.survol) { const s = COUPE.survol, [sx, sy] = s.axe === "u" ? ecran(s.px + 0.5, point.v + 0.5) : ecran(point.u + 0.5, s.px + 0.5); cx.beginPath(); cx.arc(sx, sy, 6, 0, 7); cx.fillStyle = OI.jaune; cx.fill(); cx.stroke(); }
  }
  if (survol && outil !== "regarder") {           // le pinceau sous la souris
    const R = rayonNoeuds() * PAS * V.s; cx.lineWidth = 3; cx.strokeStyle = "rgba(0,0,0,.8)"; cx.beginPath(); cx.arc(survol.x, survol.y, R, 0, 7); cx.stroke(); cx.lineWidth = 1.5; cx.strokeStyle = "#fff"; cx.setLineDash([5, 4]); cx.beginPath(); cx.arc(survol.x, survol.y, R, 0, 7); cx.stroke(); cx.setLineDash([]);
  }
  // barre d'échelle (1 mm) et attente
  const mm = 1000 / E.um * V.s, pasmm = mm > 300 ? 0.2 : mm > 60 ? 1 : mm > 12 ? 5 : 10; $("echelle").textContent = `├${"─".repeat(Math.max(2, Math.round(mm * pasmm / 8)))}┤ ${fr(pasmm, pasmm < 1 ? 1 : 0)} mm`;
  $("charge").hidden = attente === 0; menage();
}

// ───────────── coupes ─────────────
const COUPE = { ech: 3, w: 0, e: null, img: {}, occupe: false, encore: false, survol: null, cv: { u: $("coupeU"), v: $("coupeV") }, vue: { u: { k: 0, ox: 0, oy: 0 }, v: { k: 0, ox: 0, oy: 0 } } };
const vueDe = axe => { const s = COUPE.vue[axe]; if (!s.k) s.k = COUPE.ech; return s; };   // chaque coupe a son zoom (k, pixels par voxel) et son déplacement (ox, oy)
let trait = null, prise = null;                   // trait en cours dans une coupe : { axe, fixe, points: [{ s, d }] } · prise : point tenu par la souris
const rayonNoeuds = () => parseFloat($("portee").value) * 1000 / E.um / PAS;
const fixeDe = axe => (axe === "u" ? point.v : point.u) / PAS;
async function chargerCoupes() {
  if (!point || !E) return; if (COUPE.occupe) { COUPE.encore = true; return; } COUPE.occupe = true;
  try {
    const w = Math.min(600, Math.ceil(Math.max(...["u", "v"].map(a => (COUPE.cv[a].clientWidth / 2 + Math.abs(vueDe(a).ox)) / vueDe(a).k))) + 2), p = point, [e, t] = await binaire(`${API}/sections?v=${p.v}&u=${p.u}&w=${w}`);
    COUPE.e = e; COUPE.w = e.w;
    for (const axe of ["u", "v"]) {
      const g = t["img_" + axe], [h, n] = g.forme, c = document.createElement("canvas"); c.width = n; c.height = h; const im = new ImageData(n, h);
      for (let i = 0; i < g.length; i++) { im.data[i * 4] = im.data[i * 4 + 1] = im.data[i * 4 + 2] = g[i]; im.data[i * 4 + 3] = 255; } c.getContext("2d").putImageData(im, 0, 0); COUPE.img[axe] = c;
    }
    dessinerCoupes(); demander();
  } catch (err) { majSauve("erreur"); }
  COUPE.occupe = false; if (COUPE.encore) { COUPE.encore = false; chargerCoupes(); }
}
const flip = axe => axe === "u" && V.miroir;
function geoCoupe(axe) {                           // conversions colonne / profondeur ⇄ pixels de la coupe
  const c = COUPE.cv[axe], Wc = c.clientWidth, Hc = (2 * DEMI + 1) * COUPE.ech, { k, ox, oy } = vueDe(axe), w = COUPE.w, f = flip(axe) ? -1 : 1;
  return { Wc, Hc, k, f, ox, oy, x: i => Wc / 2 + ox + (i - w) * k * f, y: d => Hc / 2 + oy + d * k, i: x => w + (x - Wc / 2 - ox) / k * f, d: y => (y - Hc / 2 - oy) / k };
}
function dessinerCoupes() {
  for (const axe of ["u", "v"]) {
    const c = COUPE.cv[axe], g = c.getContext("2d"), r = dpr(), k = vueDe(axe).k, Hc = (2 * DEMI + 1) * COUPE.ech; c.style.height = Hc + "px";
    const Wc = c.clientWidth; if (c.width !== Math.round(Wc * r) || c.height !== Math.round(Hc * r)) { c.width = Math.round(Wc * r); c.height = Math.round(Hc * r); }
    g.setTransform(r, 0, 0, r, 0, 0); g.fillStyle = "#000"; g.fillRect(0, 0, Wc, Hc);
    if (!COUPE.e || !COUPE.img[axe]) { g.fillStyle = "#aaa"; g.font = "13px Segoe UI"; g.fillText("Move the mouse over the page: the scan section shows here.", 12, 24); continue; }
    const G = geoCoupe(axe), e = COUPE.e, n = 2 * e.w + 1, ligne = e["ligne_" + axe];
    g.save(); if (flip(axe)) { g.translate(Wc, 0); g.scale(-1, 1); } g.imageSmoothingEnabled = k < 4; g.drawImage(COUPE.img[axe], Wc / 2 + G.f * G.ox - (e.w + 0.5) * k, G.y(-DEMI - 0.5), n * k, (2 * DEMI + 1) * k); g.restore();
    // limites de retouche, surface d'origine (tirets blancs), feuilles repérées (petits points), surface (trait orange épais)
    g.setLineDash([2, 6]); g.strokeStyle = "rgba(255,255,255,.35)"; g.lineWidth = 1; for (const d of [-HMAX, HMAX]) { g.beginPath(); g.moveTo(0, G.y(d)); g.lineTo(Wc, G.y(d)); g.stroke(); }
    g.setLineDash([6, 5]); g.strokeStyle = "rgba(255,255,255,.75)"; g.lineWidth = 1.2; g.beginPath(); let leve = true;
    for (let i = 0; i < n; i++) { if (ligne[i] == null) { leve = true; continue; } leve ? g.moveTo(G.x(i), G.y(0)) : g.lineTo(G.x(i), G.y(0)); leve = false; } g.stroke(); g.setLineDash([]);
    if (V.pics) { for (const [i, d] of e["pics_" + axe]) { const x = G.x(i), y = G.y(d); g.fillStyle = "rgba(86,180,233,.85)"; g.fillRect(x - 1, y - 1, 2, 2); } }
    const chemin = (dec, fn) => { g.beginPath(); let l = true; for (let i = 0; i < n; i++) { const v = fn(i); if (v == null) { l = true; continue; } l ? g.moveTo(G.x(i), G.y(v + dec)) : g.lineTo(G.x(i), G.y(v + dec)); l = false; } g.stroke(); };
    if (V.couche) { g.setLineDash([1, 4]); g.strokeStyle = OI.jaune; g.lineWidth = 1.5; chemin(V.couche, i => ligne[i]); g.setLineDash([]); }
    g.strokeStyle = "rgba(0,0,0,.9)"; g.lineWidth = 4.5; chemin(0, i => ligne[i]); g.strokeStyle = OI.orange; g.lineWidth = 2; chemin(0, i => ligne[i]);
    if (prise && trait && trait.axe === axe) {       // aperçu pendant qu'on tire : tirets blancs
      const R = rayonNoeuds() * PAS, sp = prise.p.s * PAS - (axe === "u" ? e.u : e.v) + e.w, base = ligne[Math.round(sp)] ?? 0, dl = prise.p.d - base;
      g.setLineDash([5, 4]); g.strokeStyle = "#fff"; g.lineWidth = 2; chemin(0, i => ligne[i] == null || Math.abs(i - sp) > R ? null : ligne[i] + dl * 0.5 * (1 + Math.cos(Math.PI * Math.abs(i - sp) / R))); g.setLineDash([]);
    }
    if (trait && trait.axe === axe) for (const p of trait.points) { const x = G.x(p.s * PAS - (axe === "u" ? e.u : e.v) + e.w), y = G.y(p.d); g.fillStyle = prise && prise.p === p ? OI.orange : "#fff"; g.strokeStyle = "#000"; g.lineWidth = 2; g.fillRect(x - 5, y - 5, 10, 10); g.strokeRect(x - 5, y - 5, 10, 10); }
    // repère du point (deux petits triangles), sens du haut et du bas
    g.fillStyle = axe === "u" ? OI.orange : OI.ciel; const xc = G.x(e.w); g.beginPath(); g.moveTo(xc - 6, 0); g.lineTo(xc + 6, 0); g.lineTo(xc, 9); g.fill(); g.beginPath(); g.moveTo(xc - 6, Hc); g.lineTo(xc + 6, Hc); g.lineTo(xc, Hc - 9); g.fill();
    g.font = "11px Segoe UI"; g.fillStyle = "rgba(255,255,255,.8)"; g.textAlign = "left"; g.fillText("▲ top of the section (up)", 6, 13); g.fillText("▼ bottom (down)", 6, Hc - 6);
    g.textAlign = "right"; g.fillText(`${fr(Wc / k * E.um / 1000, 1)} mm wide · zoom × ${fr(k / COUPE.ech, 1)}`, Wc - 6, 13); g.textAlign = "left";
    if (COUPE.survol && COUPE.survol.axe === axe) { g.strokeStyle = "rgba(240,228,66,.8)"; g.lineWidth = 1; g.beginPath(); g.moveTo(COUPE.survol.x, 0); g.lineTo(COUPE.survol.x, Hc); g.stroke();
      const ld = ligne[Math.round(G.i(COUPE.survol.x))];          // le point exact de la surface qu'un clic va saisir, par-dessus le trait vertical
      if (ld != null && !prise) { const y = G.y(ld); g.beginPath(); g.arc(COUPE.survol.x, y, 6, 0, 7); g.fillStyle = "#000"; g.fill(); g.beginPath(); g.arc(COUPE.survol.x, y, 4.5, 0, 7); g.fillStyle = "#fff"; g.fill(); g.strokeStyle = OI.orange; g.lineWidth = 2; g.stroke(); }
    }
  }
  dessinerSituer();
  $("epingle").innerHTML = epingle ? "<b>Section pinned</b> (right-click on the page, or Esc, to release)." : "The section follows the mouse on the page; right-click to pin it.";
}
function brancherCoupe(axe) {
  const c = COUPE.cv[axe]; let pan = null;
  const lire = ev => { const rc = c.getBoundingClientRect(), x = ev.clientX - rc.left, y = ev.clientY - rc.top, G = geoCoupe(axe), e = COUPE.e, i = G.i(x); return { x, y, i, d: G.d(y), px: (axe === "u" ? e.u : e.v) - e.w + i, G }; };
  c.addEventListener("contextmenu", ev => ev.preventDefault());
  c.addEventListener("pointerdown", ev => {
    if (!COUPE.e || !point) return; ev.preventDefault(); c.setPointerCapture(ev.pointerId); const m = lire(ev), e = COUPE.e, ligne = e["ligne_" + axe], fixe = fixeDe(axe);
    if (ev.button !== 0) {                         // clic droit sur un de ses points : le retirer ; sinon clic droit ou molette enfoncée : déplacer la coupe dans sa fenêtre
      const q = ev.button === 2 && trait && trait.axe === axe ? trait.points.find(p => Math.hypot(m.G.x(p.s * PAS - (axe === "u" ? e.u : e.v) + e.w) - m.x, m.G.y(p.d) - m.y) < 10) : null;
      if (q) {                                     // retirer un point : la ligne se relâche entre ses deux voisins (un geste, annulable) au lieu de garder la bosse
        const tri = [...trait.points].sort((a, b) => a.s - b.s), k = tri.indexOf(q), R = rayonNoeuds(), a = k > 0 ? tri[k - 1].s : q.s - R, b = k < tri.length - 1 ? tri[k + 1].s : q.s + R;
        trait.points.splice(trait.points.indexOf(q), 1);
        if (trait.points.length) geste("ligne", { axe, fixe: trait.fixe, points: trait.points.map(p => [+p.s.toFixed(3), +p.d.toFixed(2)]), rayon: +R.toFixed(2), saut: 12, lisser: [+a.toFixed(3), +b.toFixed(3)] });
        dessinerCoupes();
      } else { pan = { x: m.x, y: m.y }; c.style.cursor = "grabbing"; }
      return;
    }
    if (!trait || trait.axe !== axe || trait.fixe !== fixe) trait = { axe, fixe, points: [] };
    epingle = true;                                // on retouche ici : la coupe ne bouge plus
    const col = p => p.s * PAS - (axe === "u" ? e.u : e.v) + e.w; let p = trait.points.find(p => Math.hypot(m.G.x(col(p)) - m.x, m.G.y(p.d) - m.y) < 10);
    let neuf = false, d0;
    if (!p) {
      const ld = ligne[Math.round(m.i)]; if (ld == null) { message("No surface at this spot of the section."); return; }
      const pres = Math.abs(m.G.y(ld) - m.y) <= 12; p = { s: m.px / PAS, d: pres ? ld : Math.max(-HMAX, Math.min(HMAX, m.d)) }; trait.points.push(p); neuf = true; d0 = ld;
    } else d0 = p.d;
    prise = { p, neuf, d0, y0: m.y, dp: p.d }; dessinerCoupes(); demander();
  });
  c.addEventListener("pointermove", ev => {
    if (!COUPE.e) return; const m = lire(ev);
    if (pan) { const s = vueDe(axe); s.ox += m.x - pan.x; s.oy += m.y - pan.y; pan.x = m.x; pan.y = m.y; dessinerCoupes(); return; }
    if (prise && trait && trait.axe === axe) { prise.p.d = Math.max(-HMAX, Math.min(HMAX, prise.dp + (m.y - prise.y0) / vueDe(axe).k)); }
    COUPE.survol = { axe, x: m.x, px: m.px }; const ld = COUPE.e["ligne_" + axe][Math.round(m.i)];
    $(axe === "u" ? "infoU" : "infoV").textContent = `depth ${fr(m.d, 1)} vx` + (ld != null ? ` · surface ${fr(ld, 1)} vx from the original` : ""); dessinerCoupes(); demander();
  });
  const lacher = () => {
    if (pan) { pan = null; c.style.cursor = ""; chargerCoupes(); return; }
    if (!prise) return; const pr = prise; prise = null;
    if (Math.abs(pr.p.d - pr.d0) < 0.25) { if (pr.neuf) trait.points.splice(trait.points.indexOf(pr.p), 1); else pr.p.d = pr.d0; dessinerCoupes(); return; }   // pas bougé : rien à faire
    geste("ligne", { axe, fixe: trait.fixe, points: trait.points.map(p => [+p.s.toFixed(3), +p.d.toFixed(2)]), rayon: +rayonNoeuds().toFixed(2), saut: 12 });   // pente permise : jusqu'à 12 vx par nœud (un pli serré), pour passer par les points posés ; 3 ne suffisait pas (26/11)
  };
  c.addEventListener("pointerup", lacher); c.addEventListener("pointercancel", lacher);
  c.addEventListener("pointerleave", () => { COUPE.survol = null; dessinerCoupes(); demander(); });
  c.addEventListener("wheel", ev => {               // zoom de CETTE coupe, autour de la souris
    ev.preventDefault(); if (!COUPE.e) return; const m = lire(ev), s = vueDe(axe), k = Math.max(Math.min(1, COUPE.ech), Math.min(16, s.k * Math.exp(-ev.deltaY * 0.0015)));
    s.ox = m.x - m.G.Wc / 2 - (m.i - COUPE.w) * k * m.G.f; s.oy = m.y - m.G.Hc / 2 - m.d * k; s.k = k; dessinerCoupes(); chargerCoupes();
  }, { passive: false });
  const b = document.createElement("button"), tete = c.parentElement.querySelector("header"); b.type = "button"; b.id = "recentrer" + axe.toUpperCase(); b.textContent = "⌖ Recenter";
  b.title = "Put this section back: centred on the point, normal zoom"; b.style.cssText = "flex:none;padding:1px 8px;font-size:.78rem;font-weight:400";
  b.onclick = () => { Object.assign(vueDe(axe), { k: COUPE.ech, ox: 0, oy: 0 }); dessinerCoupes(); chargerCoupes(); }; tete.insertBefore(b, tete.querySelector(".doux"));
}
function finirTrait() { trait = null; prise = null; dessinerCoupes(); }

// ───────────── situer : où est-on dans le rouleau ─────────────
// Vue d'ensemble basse résolution du scan, livrée avec l'outil (scrolls/ : toutes les tranches côte à côte dans une image). Une coupe en travers
// du rouleau et une coupe en long, par le point ; le segment en orange. Si la vue d'ensemble de ce scan manque, rien n'est affiché.
const SIT = { g: null, m: null, vol: null, cv: null, cle: "", ta: null, tb: null, b: null, h: 0 };
async function chargerSituer() {
  try {
    const g = await api(API + "/locate"), nom = String(g.volume || "").replace(/\\/g, "/").replace(/\/+$/, "").split("/").pop().replace(/\.zarr$/i, "");
    const r = await fetch("scrolls/index.json"); if (!r.ok) return; const m = (await r.json()).volumes[nom]; if (!m) return;
    const im = new Image(); im.src = "scrolls/" + m.file; await im.decode();
    const [nz, ny, nx] = m.size, c = document.createElement("canvas"); c.width = im.naturalWidth; c.height = im.naturalHeight; const x = c.getContext("2d", { willReadFrequently: true }); x.drawImage(im, 0, 0);
    const vol = new Uint8Array(nz * ny * nx);
    for (let k = 0; k < nz; k++) { const d = x.getImageData((k % m.cols) * nx, Math.floor(k / m.cols) * ny, nx, ny).data, o = k * ny * nx; for (let i = 0; i < ny * nx; i++) vol[o + i] = d[i * 4]; }
    const s = document.createElement("section"); s.className = "coupe"; s.id = "situer";
    s.innerHTML = '<header><span class="sym">◎</span> Where in the scroll <span class="doux">(low resolution · orange: this segment)</span><span class="droite" id="infoSituer"></span></header><canvas id="situerCv" style="cursor:default"></canvas>';
    const b = [nx, 0, ny, 0, nz, 0];              // cadre de ce qui n'est pas vide : les deux vues ne montrent que le rouleau, pas le noir autour
    for (let z = 0, i = 0; z < nz; z++) for (let y = 0; y < ny; y++) for (let xx = 0; xx < nx; xx++, i++) if (vol[i] > 12) { if (xx < b[0]) b[0] = xx; if (xx > b[1]) b[1] = xx; if (y < b[2]) b[2] = y; if (y > b[3]) b[3] = y; if (z < b[4]) b[4] = z; if (z > b[5]) b[5] = z; }
    SIT.b = b[1] > b[0] && b[3] > b[2] && b[5] > b[4] ? [Math.max(0, b[0] - 2), Math.min(nx, b[1] + 3), Math.max(0, b[2] - 2), Math.min(ny, b[3] + 3), Math.max(0, b[4] - 2), Math.min(nz, b[5] + 3)] : [0, nx, 0, ny, 0, nz];
    COUPE.cv.v.parentElement.after(s); SIT.cv = s.querySelector("canvas"); SIT.g = g; SIT.m = m; SIT.vol = vol; agencer(); chargerCoupes();
  } catch (e) { }
}
function dessinerSituer() {
  const c = SIT.cv; if (!c || !SIT.vol) return; const { g, m, vol } = SIT, [nz, ny, nx] = m.size, [fz, fy, fx] = m.factor, borne = (a, n) => Math.max(0, Math.min(n - 1, a));
  const P = point ? g.xyz[borne(Math.round(point.v / g.pas), g.n[0]) * g.n[1] + borne(Math.round(point.u / g.pas), g.n[1])] : null;
  const Wc = c.clientWidth, Hc = SIT.h || 190, cle = (P ? P.join() : "-") + "|" + Wc + "|" + Hc + "|" + dpr(); if (cle === SIT.cle) return; SIT.cle = cle;
  const r = dpr(); c.style.height = Hc + "px"; if (c.width !== Math.round(Wc * r) || c.height !== Math.round(Hc * r)) { c.width = Math.round(Wc * r); c.height = Math.round(Hc * r); }
  const x = c.getContext("2d"); x.setTransform(r, 0, 0, r, 0, 0); x.fillStyle = "#000"; x.fillRect(0, 0, Wc, Hc);
  const zi = borne(Math.floor((P ? P[2] : nz * fz / 2) / fz), nz), yi = borne(Math.floor((P ? P[1] : ny * fy / 2) / fy), ny);
  const petit = (w, h) => { const k = document.createElement("canvas"); k.width = w; k.height = h; const kx = k.getContext("2d"); return { k, kx, d: kx.createImageData(w, h) }; };
  const A = SIT.ta || (SIT.ta = petit(nx, ny)), B = SIT.tb || (SIT.tb = petit(nz, nx));
  for (let i = 0, o = zi * ny * nx; i < ny * nx; i++) { const v = vol[o + i]; A.d.data[i * 4] = A.d.data[i * 4 + 1] = A.d.data[i * 4 + 2] = v; A.d.data[i * 4 + 3] = 255; }
  for (let xx = 0; xx < nx; xx++) for (let z = 0; z < nz; z++) { const v = vol[(z * ny + yi) * nx + xx], i = (xx * nz + z) * 4; B.d.data[i] = B.d.data[i + 1] = B.d.data[i + 2] = v; B.d.data[i + 3] = 255; }
  A.kx.putImageData(A.d, 0, 0); B.kx.putImageData(B.d, 0, 0);
  // à gauche : en travers du rouleau (x → droite, y → bas, à la hauteur z du point) · à droite : en long (z → droite, x → bas, à l'ordonnée y du point)
  const [bx, bx1, by, by1, bz, bz1] = SIT.b, lx = bx1 - bx, ly = by1 - by, lz = bz1 - bz;
  const haut = Hc - 16, e1 = Math.min(haut / ly, Wc * 0.34 / lx), w1 = lx * e1, x2 = w1 + 14, e2 = Math.min(haut / lx, (Wc - x2 - 4) / lz), y0 = 16;
  const X1 = p => (p[0] / fx - bx) * e1, Y1 = p => y0 + (p[1] / fy - by) * e1, X2 = p => x2 + (p[2] / fz - bz) * e2, Y2 = p => y0 + (p[0] / fx - bx) * e2;
  x.imageSmoothingEnabled = true; x.drawImage(A.k, bx, by, lx, ly, 0, y0, w1, ly * e1); x.drawImage(B.k, bz, bx, lz, lx, x2, y0, lz * e2, lx * e2);
  const tr = fz * 1.5, ty = fy * 1.5;
  for (const passe of [0, 1]) {                    // d'abord tout le segment, pâle ; puis, vif, ce qui passe dans le plan de chaque coupe
    x.fillStyle = passe ? OI.orange : "rgba(230,159,0,.22)";
    for (const p of g.xyz) {
      if (!p) continue; const t = passe ? 2 : 1;
      if (!passe || !P || Math.abs(p[2] - P[2]) <= tr) x.fillRect(X1(p) - t / 2, Y1(p) - t / 2, t, t);
      if (!passe || !P || Math.abs(p[1] - P[1]) <= ty) x.fillRect(X2(p) - t / 2, Y2(p) - t / 2, t, t);
    }
  }
  x.font = "11px Segoe UI"; x.fillStyle = "rgba(255,255,255,.8)"; x.textAlign = "left"; x.fillText("across the scroll", 2, 11); x.fillText("along the scroll", x2 + 2, 11);
  if (P) {
    x.strokeStyle = "rgba(86,180,233,.8)"; x.lineWidth = 1; x.setLineDash([4, 3]);
    x.beginPath(); x.moveTo(0, Y1(P)); x.lineTo(w1, Y1(P)); x.moveTo(X2(P), y0); x.lineTo(X2(P), y0 + lx * e2); x.stroke(); x.setLineDash([]);
    for (const [px, py] of [[X1(P), Y1(P)], [X2(P), Y2(P)]]) { x.beginPath(); x.arc(px, py, 4.5, 0, 7); x.fillStyle = OI.jaune; x.fill(); x.strokeStyle = "#000"; x.lineWidth = 1.5; x.stroke(); }
    $("infoSituer").textContent = `x ${fr(P[0], 0)} · y ${fr(P[1], 0)} · z ${fr(P[2], 0)}`;
  } else $("infoSituer").textContent = "";
}

// ───────────── colonne de droite : hauteurs calculées ─────────────
// Les deux coupes, la vue « où dans le rouleau » et la note se partagent la hauteur disponible : tout tient sans défiler, quel que soit l'écran.
// Sur un petit écran la note (reprise dans l'aide) laisse sa place aux images.
function agencer() {
  const col = $("coupes"), note = col.querySelector(".noteCoupe"), sit = $("situer"); if (!col.clientHeight || !DEMI) return;
  const fixe = () => [...col.children].reduce((t, el) => t + (el.classList.contains("coupe") ? el.querySelector("header").offsetHeight : el.offsetHeight), 0);
  if (note) note.style.display = "";
  const part = sit ? 0.36 : 0.5; let libre = col.clientHeight - fixe() - 6;
  if (note && libre * part < 150) { note.style.display = "none"; libre = col.clientHeight - fixe() - 6; }
  const hc = Math.max(60, Math.floor(libre * part)), avant = COUPE.ech; COUPE.ech = hc / (2 * DEMI + 1);
  for (const a of ["u", "v"]) { const v = COUPE.vue[a]; if (!v.k || Math.abs(v.k - avant) < 1e-6) v.k = COUPE.ech; }     // une coupe qu'on n'a pas zoomée suit la nouvelle hauteur
  SIT.h = sit ? Math.max(50, libre - 2 * hc) : 0; SIT.cle = ""; dessinerCoupes();
}
window.addEventListener("resize", () => { if (E) { agencer(); chargerCoupes(); } });

// ───────────── carte des sauts de feuille (26/11) ─────────────
// Depuis le point épinglé (la feuille de référence), le serveur suit cette feuille et dit, nœud par nœud, si la surface est dessus, N feuilles
// plus haut ou plus bas, ou si ce n'est pas sûr. Rien n'est écrit. Orange ╱ = plus haut, bleu ╲ = plus bas (plein à partir de 2 feuilles),
// petits points blancs = pas sûr ; chaque zone porte son chiffre.
let SJ = null;
const SJ_NOM = { 1: "on the reference sheet", 2: "1 sheet above", 3: "2 sheets above", 4: "3 sheets or more above", 5: "1 sheet below", 6: "2 sheets below", 7: "3 sheets or more below", 8: "between two sheets", 9: "not sure" };
function peindreSauts(c, gh, gw) {
  const k = document.createElement("canvas"); k.width = gw; k.height = gh; const im = new ImageData(gw, gh), d = im.data;
  for (let v = 0; v < gh; v++) for (let u = 0; u < gw; u++) {
    const x = c[v * gw + u]; if (x < 2) continue; const o = (v * gw + u) * 4;
    if (x <= 7) { const haut = x <= 4, n = haut ? x - 1 : x - 4, trait = haut ? (u + v) % 4 === 0 : (u - v + 8192) % 4 === 0; d[o] = haut ? 230 : 86; d[o + 1] = haut ? 159 : 180; d[o + 2] = haut ? 0 : 233; d[o + 3] = n >= 2 ? 170 : trait ? 240 : 70; }
    else if (x === 8) { if ((u + v) % 2 === 0) { d[o] = 240; d[o + 1] = 228; d[o + 2] = 66; d[o + 3] = 150; } }
    else if (u % 5 === 0 && v % 5 === 0) { d[o] = d[o + 1] = d[o + 2] = 255; d[o + 3] = 170; }
  }
  k.getContext("2d").putImageData(im, 0, 0); return k;
}
function effacerSauts() { SJ = null; const b = $("sautsCarte"); if (b) { b.hidden = true; b.innerHTML = ""; } demander(); }
async function chercherSauts() {
  const b = $("sautsCarte"); if (!b) return;
  if (!point || !epingle) { message("Sheet jumps: right-click a spot where the surface is on the right sheet first. It becomes the reference.", true); return; }
  b.hidden = false; b.innerHTML = "Following the reference sheet from the pinned point… nothing is written.";
  try {
    const [e, t] = await binaire2(API + "/jumps", { ancre: [Math.round(point.v / PAS), Math.round(point.u / PAS)], saut: $("autoSaut") ? +$("autoSaut").value : 1.5, pont: $("autoPont") ? Math.round(+$("autoPont").value * 1000 / E.um / PAS) : 8 });
    SJ = { e, cv: peindreSauts(t.carte, e.grille[0], e.grille[1]) }; const p = e.parts, pc = x => fr(+x, +x < 10 ? 1 : 0) + " %";
    const haut = +p[2] + +p[3] + +p[4], bas = +p[5] + +p[6] + +p[7];
    b.innerHTML = `<div><b>Sheet jumps</b>, seen from the pinned point <span class="doux">(nothing written)</span></div>
      <div class="legende"><span><i class="pat p-bon"></i> ${pc(p[1])} on the reference sheet</span><span><i class="pat pa-haut"></i> ${pc(haut)} on a sheet above</span>
        <span><i class="pat pa-bas"></i> ${pc(bas)} on a sheet below</span><span><i class="pat pa-refus"></i> ${pc(p[9])} not sure</span></div>
      <div class="doux">${+p[8] ? pc(p[8]) + " between two sheets (yellow dots) · " : ""}sheets are about ${fr(e.espacement, 0)} vx apart here · solid colour = 2 sheets or more</div>` +
      (e.zones.length ? `<div class="sautsZones">${e.zones.map((z, i) => `<button type="button" data-saut="${i}" title="Show this zone">${z.feuilles < 0 ? "▲" : "▼"} ${Math.abs(z.feuilles)}${Math.abs(z.feuilles) >= 3 ? "+" : ""} sheet${Math.abs(z.feuilles) > 1 ? "s" : ""} ${z.feuilles < 0 ? "above" : "below"}${z.mm2 ? " · " + fr(z.mm2, 1) + " mm²" : ""}</button>`).join("")}</div>`
        : `<div><b class="okTxt">✓</b> No zone on another sheet was found where the reference sheet could be followed.</div>`) +
      `<div class="ligne"><button type="button" id="sautsEffacer">Clear the map</button><span class="doux">not sure = the reference sheet is lost before getting there</span></div>`;
    demander();
  } catch (err) { b.innerHTML = "✗ " + err.message; SJ = null; }
}
document.addEventListener("click", ev => {
  if (ev.target.id === "sautsBtn" || (ev.target.closest && ev.target.closest("#sautsBtn"))) chercherSauts();
  else if (ev.target.id === "sautsEffacer") effacerSauts();
  else { const z = ev.target.closest && ev.target.closest("[data-saut]"); if (z && SJ) { const q = SJ.e.zones[+z.dataset.saut]; centrer(q.u * PAS, q.v * PAS, Math.max(V.s, 0.6)); } }
});

// ───────────── gestes ─────────────
let file = Promise.resolve(), pinceau = null, region = [], rangPire = 0, listePire = null;
function geste(nom, params) {
  majSauve("encours");
  file = file.then(async () => { try { appliquer(await api(API + "/gesture", { outil: nom, params })); } catch (e) { message(e.message, true); majSauve(e instanceof TypeError ? "erreur" : undefined); dessinerCoupes(); } });
  return file;
}
function appliquer(r) {
  if (SJ) effacerSauts();                         // la surface vient de changer : la carte des sauts n'est plus à jour
  if (r.rien) { message(r.message); majSauve(); dessinerCoupes(); return; }
  if (r.grille) { rechargerGrille(r); return; }     // 25/11 : extension posée, annulée ou rétablie
  if (r.px) invalider(r.px);
  if (r.carreaux) { const c = r.carreaux, n = c.s1 - c.s0; SC.champs.forEach((ch, k) => c[ch].forEach((x, q) => { SC.m[k * SC.th * SC.tw + (c.t0 + Math.floor(q / n)) * SC.tw + c.s0 + q % n] = x == null ? NaN : x; })); peindreScore(c.t0, c.t1, c.s0, c.s1); }
  if (r.zones) { const [v0, v1, u0, u1] = r.zones.bbox, gw = E.grille[1]; r.zones.masque.forEach((x, q) => { ZN[(v0 + Math.floor(q / (u1 - u0))) * gw + u0 + q % (u1 - u0)] = x; }); peindreZones(v0, v1, u0, u1); const z = r.zones, n = z.s1 - z.s0; z.marquees.forEach((x, q) => { SC.marq[(z.t0 + Math.floor(q / n)) * SC.tw + z.s0 + q % n] = x; }); }
  Object.assign(E, { bilan: r.bilan, pile: r.pile, refaire: r.refaire, enregistre: r.enregistre, gen: r.gen, version: r.version || E.version }); listePire = null; rangPire = 0;
  if ($("auto")) {                               // 25/11 : gestes automatiques
    if (r.auto) { AP = null; $("autoCarte").hidden = false; $("autoChoix").hidden = true; $("autoLegende").hidden = true; $("autoBilan").innerHTML = texteBilan(r.auto, "applied"); }
    else if (AP) effacerApercu();
    else if (r.defait !== undefined && NOMS_AUTO[r.outil]) { $("autoCarte").hidden = false; $("autoBilan").textContent = `${NOMS_AUTO[r.outil]}: ${r.defait ? "undone — the surface is back exactly as it was before" : "redone"}.`; }
    if (V.fibres && r.champ === "h") { clearTimeout(fibT); fibT = setTimeout(chargerFibres, 900); }
  }
  if (r.note_zone && r.champ === "h") {
    const [a, b] = r.note_zone, d = b - a, noms = { ligne: "line dragged in the section", aimant: "magnet", bord: "edge magnet", pousser: "brush ± 1 vx", feuille: "one-sheet shift", suivre: "follow the sheet", aimant_partout: "magnet everywhere", marches: "remove steps", fibres: "best fibres" };
    $("derniere").innerHTML = `Last retouch (${noms[r.outil] || r.outil}):<br>touched area <b>${fr(a)}</b> → <b>${fr(b)}</b> <span class="${d >= 0 ? "monte" : "descend"}">${d > 0.05 ? "▲ up by " + fr(d) : d < -0.05 ? "▼ down by " + fr(-d) : "= unchanged"}</span> · max displacement ${fr(r.deplacement_max)} vx`;
  } else if (r.defait !== undefined) $("derniere").textContent = r.defait ? "Last gesture undone." : "Gesture redone.";
  if (r.defait !== undefined && r.outil === "ligne") {   // les carrés de la coupe suivent l'annulation
    const src = r.defait ? (r.sommet && r.sommet.outil === "ligne" ? r.sommet.params : null) : r.params;
    trait = src && point && src.axe && Math.abs(src.fixe - fixeDe(src.axe)) < 1e-6 ? { axe: src.axe, fixe: src.fixe, points: src.points.map(p => ({ s: p[0], d: p[1] })) } : null;
  }
  majPanneau(); majSauve(); chargerCoupes(); demander(); if (V.vue === "3d") charger3D(true);
}
async function annuler(sens) { majSauve("encours"); file = file.then(async () => { try { appliquer(await api(API + (sens < 0 ? "/undo" : "/redo"), {})); } catch (e) { message(e.message, true); majSauve("erreur"); } }); }

// ───────────── souris sur la page ─────────────
let glisse = null, espace = false;
function epingler(u, v) {                          // clic droit : fixe la coupe sur ce point ; clic droit à nouveau : elle suit de nouveau la souris
  if (epingle) { epingle = false; surbrillance = null; }
  else if (u >= 0 && v >= 0 && u < E.page[1] && v < E.page[0]) { point = { u: Math.round(u), v: Math.round(v) }; epingle = true; trait = null; surbrillance = null; chargerCoupes(); }
  dessinerCoupes(); demander();
}
cv.addEventListener("contextmenu", ev => ev.preventDefault());
cv.addEventListener("pointerdown", ev => {
  cv.focus(); cv.setPointerCapture(ev.pointerId); const rc = cv.getBoundingClientRect(), x = ev.clientX - rc.left, y = ev.clientY - rc.top, [u, v] = versPage(x, y);
  if (ev.button !== 0 || espace) { glisse = { main: true, x, y, x0: x, y0: y, b: ev.button }; cv.style.cursor = "grabbing"; return; }
  glisse = { x0: x, y0: y, x, y };
  if (outil !== "regarder") { pinceau = { points: [[v / PAS, u / PAS]], rayon: rayonNoeuds(), maj: ev.shiftKey }; demander(); }
});
cv.addEventListener("pointermove", ev => {
  const rc = cv.getBoundingClientRect(), x = ev.clientX - rc.left, y = ev.clientY - rc.top, [u, v] = versPage(x, y); survol = { x, y, u, v };
  if (glisse && glisse.main) { V.x -= (x - glisse.x) / V.s; V.y -= (y - glisse.y) / V.s; glisse.x = x; glisse.y = y; demander(); return; }
  if (glisse && pinceau) { const d = pinceau.points[pinceau.points.length - 1]; if (Math.hypot(d[0] - v / PAS, d[1] - u / PAS) >= Math.max(0.7, pinceau.rayon / 6)) pinceau.points.push([+(v / PAS).toFixed(2), +(u / PAS).toFixed(2)]); }
  if (!epingle && !glisse && u >= 0 && v >= 0 && u < E.page[1] && v < E.page[0]) { point = { u: Math.round(u), v: Math.round(v) }; if (trait) trait = null; chargerCoupes(); }
  sousCurseur(u, v); demander();
});
cv.addEventListener("pointerup", ev => {
  const g = glisse; glisse = null; cv.style.cursor = ""; if (!g) return;
  if (g.main) { if (g.b === 2 && Math.hypot(g.x - g.x0, g.y - g.y0) < 5) epingler(...versPage(g.x, g.y)); else memoriser(); return; }   // clic droit sans bouger : épingler ici, ou libérer
  const rc = cv.getBoundingClientRect(), x = ev.clientX - rc.left, y = ev.clientY - rc.top, [u, v] = versPage(x, y), R = +rayonNoeuds().toFixed(2);
  if (outil === "regarder") return;
  const p = pinceau; pinceau = null; if (!p) return;
  if (outil === "aimant") geste("aimant", { points: p.points, rayon: R, borne: +$("borne").value });
  else if (outil === "bord") geste("bord", { points: p.points, rayon: R, borne: +$("borne").value, bord: (p.maj ? 1 : -1) * +$("bord").value });
  else if (outil === "bord2") geste("bord", { points: p.points, rayon: R, borne: +$("borne").value, bord: (p.maj ? -1 : 1) * +$("bord").value });
  else if (outil === "pousser") geste("pousser", { points: p.points, rayon: R, signe: p.maj ? 1 : -1, pas: 1 });
  else if (outil === "marquer" || outil === "gomme") geste("marquer", { points: p.points, rayon: R, valeur: outil === "marquer" ? 1 : 0 });
  else if (outil === "feuille") { region.push({ points: p.points, rayon: R }); majOutil(); }
  demander();
});
cv.addEventListener("pointerleave", () => { survol = null; demander(); });
cv.addEventListener("wheel", ev => {
  ev.preventDefault(); const rc = cv.getBoundingClientRect(), x = ev.clientX - rc.left, y = ev.clientY - rc.top;
  if (ev.shiftKey) { changerCouche(V.couche + (ev.deltaY < 0 ? 1 : -1)); return; }
  const um = x / V.s + V.x, vm = y / V.s + V.y, s = Math.max(0.03, Math.min(10, V.s * Math.exp(-ev.deltaY * 0.0015))); V.s = s; V.x = um - x / s; V.y = vm - y / s; demander(); memoriser();
}, { passive: false });

// ───────────── panneau ─────────────
const VERDICT = [["dist", "Distance to the sheet", "vx", 1, v => v <= 3 ? 0 : v <= 6 ? 1 : 2], ["net", "Sheet sharpness", "%", 0, v => v >= 0.12 ? 0 : v >= 0.06 ? 1 : 2], ["marche", "Step between neighbours", "vx", 1, v => v <= 1 ? 0 : v <= 2 ? 1 : 2],
  ["etir", "Grid stretch", "%", 0, v => v <= 12 ? 0 : v <= 30 ? 1 : 2], ["cis", "Grid shear", "°", 0, v => v <= 10 ? 0 : v <= 25 ? 1 : 2], ["vois", "Neighbouring sheet at", "vx", 0, v => v >= 13 ? 0 : v >= 9 ? 1 : 2]];
const MOTS = ["✓ good", "~ fair", "✗ bad"];
function sousCurseur(u, v) {
  if (!SC) return; const t = Math.floor((v / PAS + 0.5) / CAR), s = Math.floor((u / PAS + 0.5) / CAR), n = t >= 0 && s >= 0 && t < SC.th && s < SC.tw ? sc(0, t, s) : NaN, h = u >= 0 && v >= 0 ? "" : "";
  $("coord").textContent = u >= 0 && v >= 0 && u < E.page[1] && v < E.page[0] ? `x ${fr(u, 0)} · y ${fr(v, 0)} px · ${fr(u * E.um / 1000, 2)} × ${fr(v * E.um / 1000, 2)} mm` : "";
  if (!(n === n)) { $("sousCurseur").textContent = "No surface under the mouse."; return; }
  const o = SC.o[t * SC.tw + s], marq = SC.marq[t * SC.tw + s];
  $("sousCurseur").innerHTML = `<b>Tile under the mouse: ${fr(n, 0)} / 100</b> <span class="doux">(original ${fr(o, 0)}${marq ? " · marked area" : ""})</span><table>` +
    VERDICT.map(([c, nom, unite, nd, f], k) => { const x = sc(k + 1, t, s), val = c === "net" ? x * 100 : x; return `<tr><td>${nom}${c === "vois" && x >= 40 ? " more than" : ""}</td><td>${MOTS[f(x)]}</td><td>${fr(val, nd)} ${unite}</td></tr>`; }).join("") +
    `</table><span class="doux">Biggest penalty here: ${E.criteres[sc(7, t, s)]}.</span>`;
  if (V.fibres && FB) { const i = Math.round((v - FB.x0 - FB.pas / 2) / FB.pas), j = Math.round((u - FB.x0 - FB.pas / 2) / FB.pas), k = i * FB.nx + j; if (i >= 0 && j >= 0 && i < FB.ny && j < FB.nx && FB.m[k] === FB.m[k]) $("sousCurseur").innerHTML += `<br><b>Fibre grid score here: ${fr(FB.m[k], 0)} / 100</b> <span class="doux">(original surface ${fr(FB.o[k], 0)})</span>`; }
}
function majPanneau() {
  const b = E.bilan; if (!b) return; const p = b.page, d = p.note - p.note0;
  $("notePage").textContent = fr(p.note, 1);
  $("noteDiff").innerHTML = Math.abs(d) < 0.005 ? `<span class="doux">= same as the original surface (${fr(p.note0, 1)})</span>` : `<span class="${d > 0 ? "monte" : "descend"}">${d > 0 ? "▲ +" : "▼ −"}${fr(Math.abs(d), 2)} since the original</span> <span class="doux">(before: ${fr(p.note0, 1)})</span>`;
  const ligne = (nom, x) => `<tr><td>${nom}<br><span class="doux">${fr(x.carreaux, 0)} tiles</span></td><td><b>${fr(x.note, 1)}</b></td><td>${fr(x.note0, 1)}</td><td>${x.note == null ? "" : x.note - x.note0 > 0.005 ? "▲" : x.note - x.note0 < -0.005 ? "▼" : "="}</td><td>${fr(x.mauvais, 0)}<br><span class="doux">(${fr(x.mauvais0, 0)})</span></td></tr>`;
  $("tabScore").innerHTML = `<tr><th></th><th>after</th><th>before</th><th></th><th>&lt; 40</th></tr>` + ligne("Marked areas", b.marquees) + ligne("Rest of the page", b.reste) +
    `<tr><td colspan="5" class="doux">Page: ${fr(p.detail.dist, 1)} vx from the sheet on average · steps ${fr(p.detail.marche, 1)} vx · ${fr(b.proche.maintenant, 0)} tiles with a neighbouring sheet closer than ${fr(E.voisine_proche, 0)} vx</td></tr>`;
  $("annuler").disabled = !E.pile; $("retablir").disabled = !E.refaire; $("nGestes").textContent = `${fr(E.pile, 0)} gesture${E.pile > 1 ? "s" : ""}`;
}
const AIDES = {
  regarder: "<b>Mouse</b>: the section follows · <b>right-click</b>: pin the section here, right-click again to release it",
  aimant: "<b>Magnet</b>: click or drag = snap the surface to the nearest sheet",
  bord: "<b>Edge magnet</b>: drag = snap to the sheet, then sit N vx from its core towards the TOP of the section · <b>Shift</b> + drag = towards the BOTTOM",
  bord2: "<b>Reverse edge magnet</b>: drag = snap to the sheet, then sit N vx from its core towards the BOTTOM of the section · <b>Shift</b> + drag = towards the TOP",
  pousser: "<b>Brush</b>: drag = up 1 vx · <b>Shift</b> + drag = down",
  feuille: "<b>Shift one sheet</b>: paint the region, then <kbd>PgUp</kbd> sheet above or <kbd>PgDn</kbd> sheet below",
  marquer: "<b>Mark</b>: paint what looks wrong", gomme: "<b>Eraser</b>: erases marked areas",
};
function majOutil() {
  document.querySelectorAll(".outils button[data-outil]").forEach(b => b.classList.toggle("actif", b.dataset.outil === outil)); $("boutonsFeuille").hidden = outil !== "feuille";
  $("outilInfo").textContent = outil === "regarder" ? "" : { aimant: "Magnet", bord: "Edge magnet → top (Shift = other side)", bord2: "Reverse edge magnet → bottom (Shift = other side)", pousser: "Brush ± 1 vx (Shift = down)", feuille: `Shift one sheet — ${region.length ? region.length + " painted stroke(s): choose ▲ or ▼" : "paint the region"}`, marquer: "Mark a problem area", gomme: "Erase marks" }[outil];
  $("aide").innerHTML = AIDES[outil] + " · <b>wheel</b> zoom · <b>right-click + drag</b> pan · <b>section</b>: drag the orange line · <kbd>Tab</kbd> 2D ⇄ 3D · <kbd>N</kbd> worst tile · <kbd>S</kbd> scores · <kbd>Z</kbd> areas · <kbd>E</kbd> ink · <kbd>↑</kbd><kbd>↓</kbd> depth · <kbd>[</kbd><kbd>]</kbd> reach · <kbd>Ctrl+Z</kbd> <kbd>Ctrl+Y</kbd>";
  cv.style.cursor = outil === "regarder" ? "crosshair" : "none"; demander();
}
function choisirOutil(o) { outil = o; pinceau = null; majOutil(); }
function changerCouche(c) { V.couche = Math.max(-E.couches, Math.min(E.couches, c)); $("couche").value = V.couche; $("coucheVal").textContent = (V.couche > 0 ? "+" : "") + V.couche + " vx"; demander(); dessinerCoupes(); memoriser(); if (V.vue === "3d") charger3D(true); }
function majReglages() { $("porteeVal").textContent = fr(+$("portee").value, 2) + " mm"; $("borneVal").textContent = "± " + $("borne").value + " vx"; $("bordVal").textContent = fr(+$("bord").value, 1) + " vx"; $("opEncre").nextElementSibling.textContent = Math.round(V.opEncre * 100) + " %";
  if ($("extLargeur")) $("extLargeurVal").textContent = fr(+$("extLargeur").value, 2) + " mm";
  if ($("autoSaut")) { $("autoSautVal").textContent = fr(+$("autoSaut").value, 2) + " vx"; $("autoPontVal").textContent = fr(+$("autoPont").value, 2) + " mm"; $("autoSeuilVal").textContent = fr(+$("autoSeuil").value, 1) + " vx"; $("autoPorteeVal").textContent = "± " + $("autoPortee").value + " vx"; }
  demander(); }
function decalerFeuille(sens) {
  if (!region.length) { message("First paint the region to shift (tool F), then choose ▲ or ▼."); return; }
  const traits = region; region = []; majOutil(); geste("feuille", { traits, sens, recoller: true });
}
async function allerAuPire() {
  const marq = $("pireMarquees").checked;
  if (!listePire || listePire.marq !== marq) { listePire = await api(`${API}/worst?n=80&marked=${marq ? 1 : 0}`); listePire.marq = marq; rangPire = 0; }
  if (!listePire.length) { message(marq ? "No scored tile in the marked areas." : "No scored tile."); return; }
  const c = listePire[rangPire % listePire.length]; rangPire++; if (V.vue === "3d") basculer("2d");
  const k = CAR * PAS, u = (c.s + 0.5) * k - PAS / 2, v = (c.t + 0.5) * k - PAS / 2; surbrillance = c; point = { u: Math.round(u), v: Math.round(v) }; epingle = true; trait = null;
  if (!V.score) { V.score = true; $("voirScore").checked = true; }
  centrer(u, v, Math.max(V.s, 1.6)); chargerCoupes(); sousCurseur(u, v);
  message(`Tile #${rangPire} of the ${listePire.length} worst${marq ? " in the marked areas" : ""}: score ${fr(c.note, 0)} — ${E.criteres[sc(7, c.t, c.s)]}. Press N again for the next one.`);
}

// ───────────── calque « fibre score » : note de quadrillage des fibres par fenêtre de 0,3 mm (jamais en couleur seule : points, hachures, croisillons, chiffres) ─────────────
let FB = null, fibT = 0, fibOccupe = false, attT = 0, attN = 0; const cvFib = document.createElement("canvas");
function attente(cible, barre) {                 // pendant un calcul long du serveur : ce qu'il fait, sa part, le temps écoulé
  clearInterval(attT); const moi = ++attN; if ($("autoBarre")) $("autoBarre").hidden = true; if (!cible) return;
  const t0 = Date.now(); if (barre) { barre.hidden = false; barre.firstElementChild.style.width = "0"; }
  attT = setInterval(async () => {
    try { const a = await api(API + "/progress"); if (moi !== attN || !a || !a.texte || a.texte === "done") return; cible.textContent = `${a.texte}${a.part != null ? " " + Math.round(a.part * 100) + " %" : ""} · ${Math.round((Date.now() - t0) / 1000)} s`; if (barre && a.part != null) barre.firstElementChild.style.width = Math.round(a.part * 100) + "%"; } catch (e) { }
  }, 600);
}
function peindreFibres() {
  const K = 4, w = FB.nx * K, h = FB.ny * K; cvFib.width = w; cvFib.height = h; const im = new ImageData(w, h), d = im.data;
  for (let i = 0; i < FB.ny; i++) for (let j = 0; j < FB.nx; j++) {
    const n = FB.m[i * FB.nx + j]; if (!(n === n)) continue; const k = n >= 60 ? 0 : n >= 40 ? 1 : n >= 20 ? 2 : 3; if (!k) continue;
    const col = k === 3 ? [204, 121, 167] : [86, 180, 233];
    for (let y = 0; y < K; y++) for (let x = 0; x < K; x++) {
      const X = j * K + x, Y = i * K + y, o = (Y * w + X) * 4, trait = k === 1 ? (X % 4 === 2 && Y % 4 === 2) : k === 2 ? ((X - Y + 4096) % 4 === 0) : ((X - Y + 4096) % 4 === 0 || (X + Y) % 4 === 0);
      d[o] = col[0]; d[o + 1] = col[1]; d[o + 2] = col[2]; d[o + 3] = trait ? 245 : (k === 1 ? 0 : k === 2 ? 40 : 75);
    }
  }
  cvFib.getContext("2d").putImageData(im, 0, 0);
}
function chargerFibres() {
  if (!V.fibres || !E.auto || fibOccupe || (FB && FB.gen === E.gen)) return; fibOccupe = true; message("Fibre grid score: measuring…"); attente($("message"));
  file = file.then(async () => {
    try {
      const [e, t] = await binaire2(API + "/fibres"); FB = { ny: e.ny, nx: e.nx, pas: e.pas, x0: (e.fenetre - e.pas) / 2, gen: e.gen, m: t.maintenant, o: t.origine, bilan: e.bilan }; peindreFibres(); attente(null);
      const p = e.bilan.page, q = e.bilan.marquees; message(`Fibre grid score (0–100): page ${fr(p.apres, 1)} (original surface ${fr(p.avant, 1)})${q && q.apres != null ? ` · marked areas ${fr(q.apres, 1)} (${fr(q.avant, 1)})` : ""}. Blank = 60 or more, dots 40–60, hatching 20–40, cross-hatching below 20.`);
    } catch (err) { attente(null); message(err.message, true); }
    fibOccupe = false; demander();
  });
}

// ───────────── gestes automatiques : aperçu (rien n'est écrit), bilan chiffré, carte de ce qui bougerait, puis « Apply » = UN geste ─────────────
let AP = null;
const NOMS_AUTO = { suivre: "Follow the sheet", aimant_partout: "Magnet everywhere", marches: "Remove steps", fibres: "Best fibres", etendre: "Extend the surface", page_dessus: "Whole page → sheet above", page_dessous: "Whole page → sheet below" };
const COTES_EXT = { v0: "top", v1: "bottom" };
function paramsAuto(o) {
  const bord = +$("autoBord").value * +$("bord").value, zones = $("autoMarquees").checked, greffe = $("autoGreffe").checked, anc = point && epingle ? [Math.round(point.v / PAS), Math.round(point.u / PAS)] : null;
  if (o === "suivre") {
    if (!anc) { message("Follow the sheet: first click on the page to pin the anchor — a spot where the surface is on the right sheet.", true); return null; }
    return { ancre: anc, saut: +$("autoSaut").value, pont: Math.round(+$("autoPont").value * 1000 / E.um / PAS), bord, seuil: +$("autoSeuil").value, greffe };
  }
  if (o === "etendre") { const c = $("extCote").value, cote = c === "haut" ? "v0" : c === "bas" ? "v1" : (c === "droite") !== V.miroir ? "u1" : "u0"; return { cote, largeur: +$("extLargeur").value, saut: +$("autoSaut").value, pont: Math.round(+$("autoPont").value * 1000 / E.um / PAS) }; }      // le côté est celui de l'écran (page en miroir comprise)
  if (o === "aimant_partout") return { borne: +$("borne").value, bord, zones, greffe };
  if (o === "page_dessus" || o === "page_dessous") return { zones };
  if (o === "marches") return anc ? { seuil: +$("autoSeuil").value, ancre: anc } : { seuil: +$("autoSeuil").value };      // la preuve d'une marche est géométrique : pas de tri par la note des fibres
  return { portee: +$("autoPortee").value, zones, greffe };
}
function texteExtension(b, etat) {              // bilan d'une extension : surface ajoutée, part du bord qui s'est arrêtée parce que la feuille n'est pas sûre
  const pc = (a, t) => t ? fr(100 * a / t, 0) + " %" : "–", cote = COTES_EXT[b.cote] || ((b.cote === "u1") !== V.miroir ? "right" : "left"), L = [];
  L.push(`<b>Extend the surface — ${etat}</b>`);
  L.push(`${b.noeuds ? `<b>+ ${fr(b.mm2, 2)} mm²</b> (${fr(b.noeuds, 0)} nodes) on the ${cote} side` : `Nothing added on the ${cote} side`} · asked for ${fr(b.demande_mm, 2)} mm along ${fr(b.bord_mm, 1)} mm of edge`);
  L.push(`Stopped: sheet not sure on <b>${pc(b.arretees, b.parties)}</b> of the edge (rows that stopped before 80 % of the width; ${pc(b.sans_rien, b.parties)} could not start at all) · went all the way: ${pc(b.complets, b.parties)}`);
  L.push(`Advance: median ${fr(b.avance_mediane_mm, 2)} mm, at most ${fr(b.avance_max_mm, 2)} mm · new nodes sitting on a detected sheet: ${pc(b.surs, b.noeuds)}`);
  L.push(`<span class="doux">Scan read for the band only: ${fr(b.pixels_lus, 0)} pixels (${fr(b.blocs.disque, 0)} blocks from the local cache, ${fr(b.blocs.reseau, 0)} from the public repository${b.blocs.absents ? ", " + fr(b.blocs.absents, 0) + " missing" : ""}). Computed in ${fr(b.ms / 1000, 1)} s. ${etat.startsWith("preview") ? "The band lies beyond the current page: it appears once applied. No ink layer on the new band." : etat === "applied" ? "One Ctrl+Z removes the band." : ""}</span>`);
  return L.map(x => `<div>${x}</div>`).join("");
}
async function rechargerGrille(r) {              // la grille a changé de taille (extension posée, annulée ou rétablie) : tout l'état de la page est repris du serveur
  const [uc, vc] = versPage(cv.clientWidth / 2, cv.clientHeight / 2), dy = r.decale[0], dx = r.decale[1];
  E = r.etat; tuiles.clear(); SC = null; ZN = null; FB = null; AP = null; listePire = null; rangPire = 0; region = []; trait = null; surbrillance = null; if (point) point = { u: point.u + dx, v: point.v + dy };
  await Promise.all([chargerScores(), chargerZones()]); centrer(uc + dx, vc + dy); majPanneau(); majSauve(); majOutil(); chargerCoupes();
  if ($("auto")) { $("autoCarte").hidden = false; $("autoChoix").hidden = true; $("autoLegende").hidden = true; $("autoBilan").innerHTML = r.auto ? texteExtension(r.auto, r.defait === undefined ? "applied" : r.defait ? "undone (the band is removed)" : "redone") : ""; }
  if (V.vue === "3d") charger3D(false); demander();
}
function texteBilan(b, etat) {
  if (b.outil === "etendre") return texteExtension(b, etat);
  const pc = (a, t) => t ? fr(100 * a / t, 1) + " %" : "–", L = [], f = b.fibres, g = b.greffe;
  L.push(`<b>${NOMS_AUTO[b.outil] || b.outil} — ${etat}</b>`);
  L.push(`Nodes that move: <b>${fr(b.deplaces, 0)}</b> of ${fr(b.noeuds, 0)} (${pc(b.deplaces, b.noeuds)}) · median ${fr(b.mediane, 1)} vx · max ${fr(b.max, 1)} vx · ${fr(b.feuille, 0)} by 4 vx or more (sheet change)`);
  if (b.deplaces) L.push(`Direction: ${pc(b.vers_haut, b.deplaces)} towards the top, ${pc(b.vers_bas, b.deplaces)} towards the bottom · median shift ${fr(b.signe[1], 1)} vx, 80 % between ${fr(b.signe[0], 1)} and ${fr(b.signe[2], 1)} (negative = towards the top)`);
  L.push(`Steps &gt; 3 vx: <b>${fr(b.marches3[0], 0)} → ${fr(b.marches3[1], 0)}</b> · steps &gt; 1 vx: ${fr(b.marches1[0], 0)} → ${fr(b.marches1[1], 0)} · steps created: <b>${fr(b.creees, 0)}</b>`);
  if (b.outil === "suivre") L.push(`Followed without a break from the anchor: ${pc(b.suivis, b.noeuds)} of the surface · left as it is because the sheet is not sure: <b>${pc(b.pas_sur, b.champ)}</b> · ${fr(b.conflits, 0)} conflicts (two fronts that disagree)`);
  else if (b.outil === "aimant_partout") L.push(`No sheet within ± ${fr(b.borne, 0)} vx (left as it is, or following its neighbours): <b>${pc(b.pas_sur, b.champ)}</b> of the nodes${b.zones ? " of the marked areas" : ""}${b.bord ? ` · sits ${fr(Math.abs(b.bord), 1)} vx from the core, towards the ${b.bord < 0 ? "top" : "bottom"}` : ""}`);
  else if (b.outil === "page_dessus" || b.outil === "page_dessous") L.push(`Next sheet ${b.sens < 0 ? "above" : "below"} found under <b>${pc(b.trouves, b.champ)}</b> of the nodes${b.zones ? " of the marked areas" : ""} · jump: median <b>${fr(b.saut_median, 1)} vx</b>, 80 % between ${fr(b.saut_p10_p90[0], 1)} and ${fr(b.saut_p10_p90[1], 1)} vx · <b>no sheet found</b> (these nodes follow their neighbours: tight or crushed sheets, crack — check them): <b>${pc(b.pas_sur, b.champ)}</b>${b.hors_marge ? ` · ${fr(b.hors_marge, 0)} nodes stopped at the ± 32 vx margin` : ""}`);
  else if (b.outil === "marches") L.push(`Regions separated by steps &gt; ${fr(b.seuil, 1)} vx: ${fr(b.regions, 0)} · brought back onto the reference sheet: <b>${fr(b.ramenees, 0)}</b> (${fr(b.noeuds_ramenes, 0)} nodes) · not fixed: <b>${fr(b.laissees, 0)}</b> (${fr(b.noeuds_laisses, 0)} nodes; ${fr(b.raisons.couture, 0)} with an unclear seam, ${fr(b.raisons.pas_de_feuille, 0)} with no sheet detected there, ${fr(b.raisons.marge, 0)} beyond ± 32 vx, the others do not touch the reference) · ${fr(b.marches_seuil_internes, 0)} steps fade out inside one region: a shift cannot remove them`);
  else if (b.outil === "fibres") L.push(`Searched ± ${b.portee} vx${b.zones ? " in the marked areas" : ""} · tiles asking to move: ${fr(b.fenetres_qui_bougent, 0)} of ${fr(b.fenetres, 0)} · ${fr(b.a_la_limite, 0)} at the search limit (their best depth may be further away — possibly the next sheet)`);
  if (g) L.push(`Winning parts only: ${fr(g.refuses, 0)} of ${fr(g.proposes, 0)} proposed nodes refused (the fibre grid would get worse) · patches changing sheet: ${fr(g.plaques - g.plaques_refusees, 0)} kept (${fr(g.plaques_par_couture || 0, 0)} of them because they erase an existing step all around), ${fr(g.plaques_refusees, 0)} refused`);
  if (f && f.page && f.page.avant != null) {
    const z = x => x && x.avant != null ? `${fr(x.avant, 1)} → <b>${fr(x.apres, 1)}</b>` : "–";
    L.push(`Fibre grid score (0–100): page ${z(f.page)} · marked areas ${z(f.marquees)} · rest ${z(f.reste)} · tiles up by more than 10: ${fr(f.page.monte, 1)} % · down by more than 10: ${fr(f.page.baisse, 1)} %${g ? ' <span class="doux">(optimistic: the parts were chosen with this same score — judge by eye on the page)</span>' : ""}`);
  }
  L.push(`<span class="doux">Computed in ${fr(b.ms / 1000, 1)} s. ${etat.startsWith("preview") ? "Map on the page = what would move." : etat === "applied" ? "One Ctrl+Z undoes all of it." : ""}</span>`);
  return L.map(x => `<div>${x}</div>`).join("");
}
function peindreApercu(c, gh, gw) {                // orange ╱ = vers le haut, bleu ╲ = vers le bas, plein = 4 vx ou plus, points blancs = proposé puis refusé
  const cvA = document.createElement("canvas"); cvA.width = gw; cvA.height = gh; const im = new ImageData(gw, gh), d = im.data;
  for (let v = 0; v < gh; v++) for (let u = 0; u < gw; u++) {
    const k = c[v * gw + u]; if (!k) continue; const o = (v * gw + u) * 4, sens = k & 3;
    if (sens) { const haut = sens === 1, trait = haut ? (u + v) % 4 === 0 : (u - v + 8192) % 4 === 0; d[o] = haut ? 230 : 86; d[o + 1] = haut ? 159 : 180; d[o + 2] = haut ? 0 : 233; d[o + 3] = (k & 4) ? 150 : trait ? 235 : 40; }
    else if ((k & 16) && u % 4 === 0 && v % 4 === 0) { d[o] = d[o + 1] = d[o + 2] = 255; d[o + 3] = 235; }
  }
  cvA.getContext("2d").putImageData(im, 0, 0); return cvA;
}
function effacerApercu() { AP = null; if ($("auto")) { $("autoChoix").hidden = true; $("autoLegende").hidden = true; $("autoCarte").hidden = true; } demander(); }
function lancerAuto(o) {
  if (!E.auto) return; if (o === "etendre" && !E.auto.includes("etendre")) { message("Extend the surface needs the server to be restarted (it is still running the previous version).", true); return; }
  const p = paramsAuto(o); if (!p) return; effacerApercu(); const boutons = document.querySelectorAll(".autos button[data-auto]");
  $("autoCarte").hidden = false; $("autoBilan").textContent = `${NOMS_AUTO[o]}: computing the preview… nothing is written yet.`; boutons.forEach(b => { b.disabled = true; }); attente($("autoBilan"), $("autoBarre"));
  file = file.then(async () => {
    try {
      const [e, t] = o === "etendre" ? [await api(API + "/preview", { outil: o, params: p }), {}] : await binaire2(API + "/preview", { outil: o, params: p }); attente(null);
      if (e.rien) $("autoBilan").innerHTML = (e.auto ? texteBilan(e.auto, "nothing to apply") : `<b>${NOMS_AUTO[o]}</b>`) + `<div>${e.message}</div>`;
      else { AP = { outil: o, params: p, bilan: e.auto, cv: t.carte ? peindreApercu(t.carte, e.grille[0], e.grille[1]) : null }; $("autoBilan").innerHTML = texteBilan(e.auto, "preview, nothing written yet"); $("autoChoix").hidden = false; $("autoLegende").hidden = !t.carte; $("autoCarte").scrollIntoView({ block: "nearest" }); }
    } catch (err) { attente(null); $("autoCarte").hidden = true; message(err.message, true); }
    boutons.forEach(b => { b.disabled = false; }); demander();
  });
}
function appliquerAuto() {
  if (!AP) return; const a = AP; $("autoChoix").hidden = true; $("autoBilan").innerHTML = texteBilan(a.bilan, "applying…");
  if (a.outil !== "etendre") { geste(a.outil, a.params); return; }
  majSauve("encours"); file = file.then(async () => { try { appliquer(await api(API + "/extend", { params: a.params })); } catch (e) { message(e.message, true); majSauve(e instanceof TypeError ? "erreur" : undefined); } });
}

// ───────────── vue 3D ─────────────
let v3d = null, charge3d = 0;
async function charger3D(garder, repli) {
  if (!v3d) { v3d = Vue3D($("gl"), p => { basculer("2d"); point = { u: Math.round(p.u), v: Math.round(p.v) }; epingle = true; trait = null; centrer(p.u, p.v); chargerCoupes(); }); if (!v3d.ok) { message("3D (WebGL) is not available in this browser.", true); return; } }
  const [uc, vc] = versPage(cv.clientWidth / 2, cv.clientHeight / 2), p = point || { u: Math.round(uc), v: Math.round(vc) }, n = ++charge3d;
  const tout = !!($("v3dTout") && $("v3dTout").checked); if (v3d.dernierTout !== tout) garder = false; v3d.dernierTout = tout;      // 25/11 : tout le segment par défaut (maillage allégé), ou un morceau pleine résolution
  const [e, t] = await binaire(`${API}/patch3d?v=${p.v}&u=${p.u}&r=${$("v3dTaille").value}&c=${V.couche}&e=${encodeURIComponent(V.encre || "")}${tout ? "&whole=1&n=" + (v3d.grand ? 400 : 250) : ""}`); if (n !== charge3d) return;
  v3d.opt.encre = V.opEncre > 1 ? V.opEncre / 100 : V.opEncre; v3d.opt.voisines = $("v3dVoisines").checked;
  if (!v3d.charger(e, t, garder)) {
    if (!repli) { point = { u: Math.round(E.page[1] / 2), v: Math.round(E.page[0] / 2) }; epingle = true; message("No surface at the pinned point: showing the centre of the page instead. Right-click on the papyrus in 2D to choose another spot.", true); return charger3D(false, true); }
    message("No surface here: go back to 2D (Tab) and click on the papyrus.", true); }
}
function basculer(vue) {
  V.vue = vue || (V.vue === "2d" ? "3d" : "2d"); const d3 = V.vue === "3d";
  $("page").hidden = d3; $("gl").hidden = !d3; $("info3d").hidden = !d3; $("echelle").hidden = d3; $("coord").hidden = d3; $("outilInfo").hidden = d3; $("b2d").classList.toggle("actif", !d3); $("b3d").classList.toggle("actif", d3);
  if (d3) { if (!point) { const [u, v] = versPage(cv.clientWidth / 2, cv.clientHeight / 2); point = { u: Math.round(u), v: Math.round(v) }; chargerCoupes(); } charger3D(false); } else { if (point) centrer(point.u, point.v); demander(); }
}

// ───────────── clavier et boutons ─────────────
window.addEventListener("keydown", ev => {
  if (ev.target.tagName === "SELECT" || ev.target.tagName === "TEXTAREA" || (ev.target.tagName === "INPUT" && ev.target.type !== "range" && ev.target.type !== "checkbox")) return;
  if (window.dialogueOuvert && window.dialogueOuvert() && ev.key !== "Escape") return;
  const k = ev.key.toLowerCase();
  if ((ev.ctrlKey || ev.metaKey) && k === "z") { ev.preventDefault(); annuler(ev.shiftKey ? 1 : -1); return; }
  if ((ev.ctrlKey || ev.metaKey) && k === "y") { ev.preventDefault(); annuler(1); return; }
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const outils = { r: "regarder", a: "aimant", d: "bord", x: "bord2", b: "pousser", f: "feuille", m: "marquer", g: "gomme" };
  if (outils[k]) { choisirOutil(outils[k]); return; }
  if (k === "tab") { ev.preventDefault(); basculer(); }
  else if (k === " ") { ev.preventDefault(); espace = true; }
  else if (k === "s") { V.score = !V.score; $("voirScore").checked = V.score; demander(); memoriser(); }
  else if (k === "z") { V.zones = !V.zones; $("voirZones").checked = V.zones; demander(); memoriser(); }
  else if (k === "q" && $("voirFibres") && !$("voirFibres").disabled) { V.fibres = !V.fibres; $("voirFibres").checked = V.fibres; if (V.fibres) chargerFibres(); demander(); }
  else if (k === "p") { V.pics = !V.pics; $("voirPics").checked = V.pics; dessinerCoupes(); memoriser(); }
  else if (k === "e") { const o = $("encre"); o.selectedIndex = (o.selectedIndex + 1) % o.options.length; V.encre = o.value; demander(); memoriser(); if (V.vue === "3d") charger3D(true); }
  else if (k === "n") allerAuPire();
  else if (k === "j") { if (SJ) effacerSauts(); else chercherSauts(); }
  else if (k === "arrowup") { ev.preventDefault(); changerCouche(V.couche - 1); }
  else if (k === "arrowdown") { ev.preventDefault(); changerCouche(V.couche + 1); }
  else if (k === "[" || k === "]") { const p = $("portee"); p.value = Math.max(0.1, Math.min(3, +p.value * (k === "]" ? 1.25 : 0.8))).toFixed(2); majReglages(); memoriser(); }
  else if (k === "pageup") { ev.preventDefault(); decalerFeuille(-1); }
  else if (k === "pagedown") { ev.preventDefault(); decalerFeuille(1); }
  else if (k === "enter") finirTrait();
  else if (k === "escape") { if (window.fermerDialogues && window.fermerDialogues()) return; if (prise || trait) finirTrait(); else if (AP) effacerApercu(); else if (region.length) { region = []; majOutil(); } else if (outil !== "regarder") choisirOutil("regarder"); else { epingle = false; surbrillance = null; dessinerCoupes(); demander(); } }
});
window.addEventListener("keyup", ev => { if (ev.key === " ") espace = false; });
document.querySelectorAll(".outils button[data-outil]").forEach(b => b.addEventListener("click", () => choisirOutil(b.dataset.outil)));
$("b2d").onclick = () => basculer("2d"); $("b3d").onclick = () => basculer("3d");
$("feuilleHaut").onclick = () => decalerFeuille(-1); $("feuilleBas").onclick = () => decalerFeuille(1); $("feuilleVider").onclick = () => { region = []; majOutil(); };
$("portee").oninput = () => { majReglages(); memoriser(); }; $("borne").oninput = () => { majReglages(); memoriser(); }; $("bord").oninput = () => { majReglages(); };
$("couche").oninput = ev => changerCouche(+ev.target.value);
$("encre").onchange = ev => { V.encre = ev.target.value; demander(); memoriser(); if (V.vue === "3d") charger3D(true); }; $("opEncre").oninput = ev => { V.opEncre = +ev.target.value; majReglages(); if (v3d && v3d.ok && V.vue === "3d") { v3d.opt.encre = V.opEncre > 1 ? V.opEncre / 100 : V.opEncre; v3d.dessiner(); } };
$("voirZones").onchange = ev => { V.zones = ev.target.checked; demander(); memoriser(); }; $("voirScore").onchange = ev => { V.score = ev.target.checked; demander(); memoriser(); };
$("voirPics").onchange = ev => { V.pics = ev.target.checked; dessinerCoupes(); memoriser(); };
$("miroir").onchange = ev => { const [u, v] = versPage(cv.clientWidth / 2, cv.clientHeight / 2); V.miroir = ev.target.checked; centrer(u, v); dessinerCoupes(); };
$("annuler").onclick = () => annuler(-1); $("retablir").onclick = () => annuler(1); $("pire").onclick = allerAuPire; $("pireMarquees").onchange = () => { listePire = null; };
$("figer").onclick = async () => { try { const r = await api(API + "/freeze", {}); E.version = r.version; E.enregistre = r.enregistre; majSauve(); message(`Version ${r.figee} frozen (it will not change any more). You continue on ${r.version}.`); } catch (e) { message(e.message, true); } };
$("exporter").onclick = () => window.ouvrirExport && window.ouvrirExport();
$("v3dVoisines").onchange = ev => { v3d.opt.voisines = ev.target.checked; v3d.dessiner(); }; $("v3dCoupes").onchange = ev => { v3d.opt.coupes = ev.target.checked; v3d.dessiner(); }; $("v3dTaille").onchange = () => { if ($("v3dTout")) $("v3dTout").checked = false; charger3D(false); };
if ($("v3dTout")) $("v3dTout").onchange = () => charger3D(false);
if ($("auto")) {                                 // 25/11 : gestes automatiques
  document.querySelectorAll(".autos button[data-auto]").forEach(b => b.addEventListener("click", () => lancerAuto(b.dataset.auto)));
  for (const id of ["autoSaut", "autoPont", "autoSeuil", "autoPortee", "extLargeur"]) if ($(id)) $(id).oninput = majReglages;
  $("autoAppliquer").onclick = appliquerAuto; $("autoAnnuler").onclick = effacerApercu;
}
if ($("voirFibres")) $("voirFibres").onchange = ev => { V.fibres = ev.target.checked; if (V.fibres) chargerFibres(); demander(); };
new ResizeObserver(() => { demander(); if (v3d && v3d.ok && V.vue === "3d") v3d.dessiner(); }).observe($("zonePage"));
new ResizeObserver(() => { dessinerCoupes(); chargerCoupes(); }).observe($("coupes"));
window.addEventListener("error", ev => message("Page error: " + ev.message, true));

// ───────────── démarrage ─────────────
(async function demarrer() {
  try {
    if (!SEG) { const e = new Error("no segment chosen"); e.status = 404; throw e; }
    E = await api(API + "/state"); TU = E.tuile; NIV = E.niveaux; PAS = E.pas; CAR = E.carreau; DEMI = E.demi; HMAX = E.hmax;
    document.title = `Surface Enhancer — ${E.nom}`; $("titre").textContent = E.nom + (E.rouleau ? " · " + E.rouleau : "");
    if ($("auto") && !E.auto) { document.querySelectorAll(".autos button[data-auto]").forEach(b => { b.disabled = true; }); if ($("voirFibres")) $("voirFibres").disabled = true; }
    $("chemins").textContent = `Its versions, journal and exports are in ${E.dossier}`;
    $("encre").innerHTML = `<option value="">none (scan only)</option>` + E.encre.map(c => `<option value="${c.cle}">${c.nom}</option>`).join("");
    V.miroir = E.miroir; let m = null; try { m = JSON.parse(localStorage.getItem("surface_enhancer_" + E.nom)); } catch (e) { }
    if (m && isFinite(m.s) && !location.search.includes("neuf")) { Object.assign(V, { x: m.x, y: m.y, s: m.s, couche: m.couche || 0, encre: E.encre.some(c => c.cle === m.encre) ? m.encre : "", zones: m.zones !== false, score: !!m.score, pics: m.pics !== false, miroir: m.miroir ?? E.miroir }); if (m.portee) $("portee").value = m.portee; if (m.borne) $("borne").value = m.borne; }
    else { V.s = Math.min(cv.clientWidth / E.page[1], cv.clientHeight / E.page[0]) * 0.96; V.x = (E.page[1] - cv.clientWidth / V.s) / 2; V.y = (E.page[0] - cv.clientHeight / V.s) / 2; }
    $("miroir").checked = V.miroir; $("voirZones").checked = V.zones; $("voirScore").checked = V.score; $("voirPics").checked = V.pics; $("encre").value = V.encre; $("couche").value = V.couche;
    brancherCoupe("u"); brancherCoupe("v"); agencer(); changerCouche(V.couche); majReglages(); majOutil(); majSauve();
    await Promise.all([chargerScores(), chargerZones()]); majPanneau(); dessinerCoupes(); demander(); window.PRET = true; if (window.editeurPret) window.editeurPret(); chargerSituer();
  } catch (e) { $("sauve").textContent = e.status ? "segment not opened" : "server unreachable"; $("sauve").className = "erreur"; message(String(e.message || e), true); if (window.editeurEchec) window.editeurEchec(e); }
})();
