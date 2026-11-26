/* RETOUCHEUR DE SURFACE — vue 3D : petit rendu WebGL maison (aucune bibliothèque, rien de téléchargé).
   Le morceau de surface autour du point, texturé par la page ; les deux coupes du scan en rubans translucides ; les feuilles voisines en nuages de points
   (ronds orange = au-dessus, carrés bleus = en dessous). Glisser : tourner · molette : zoom · clic droit + glisser : déplacer · clic : revenir en 2D ici. */
"use strict";
function Vue3D(canvas, surClic) {
  const gl = canvas.getContext("webgl", { antialias: true, alpha: false });
  if (!gl) return { ok: false };
  const opt = { voisines: false, coupes: true, encre: 0.9 };
  const prog = (vs, fs) => {
    const p = gl.createProgram();
    for (const [t, s] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) { const sh = gl.createShader(t); gl.shaderSource(sh, s); gl.compileShader(sh); if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh)); gl.attachShader(p, sh); }
    gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p;
  };
  const pT = prog(`attribute vec3 aPos; attribute vec2 aUV; attribute vec3 aNor; uniform mat4 uMVP; varying vec2 vUV; varying vec3 vNor;
      void main(){ vUV = aUV; vNor = aNor; gl_Position = uMVP * vec4(aPos, 1.0); }`,
    `precision mediump float; varying vec2 vUV; varying vec3 vNor; uniform sampler2D uTex, uEnc; uniform float uAlpha, uOmbre, uEncre; uniform vec3 uLum;
      void main(){ float g = texture2D(uTex, vUV).r; if (uOmbre < 0.5 && g < 0.012) discard;
        float l = mix(1.0, 0.45 + 0.55 * abs(dot(normalize(vNor), uLum)), uOmbre); float e = texture2D(uEnc, vUV).r * uEncre; vec3 c = vec3(g * l) * (1.0 - 0.40 * step(0.001, uEncre)); gl_FragColor = vec4(mix(c, vec3(1.0, 0.85, 0.1), e), uAlpha); }`);
  const pC = prog(`attribute vec3 aPos; uniform mat4 uMVP; uniform float uTaille; void main(){ gl_Position = uMVP * vec4(aPos, 1.0); gl_PointSize = uTaille; }`,
    `precision mediump float; uniform vec4 uCol; uniform float uForme;
      void main(){ if (uForme > 0.5) { vec2 c = gl_PointCoord - 0.5; float d = length(c); if (d > 0.5) discard; if (d > 0.36) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; } } gl_FragColor = uCol; }`);
  const loc = (p, noms) => Object.fromEntries(noms.map(n => [n, n[0] === "a" ? gl.getAttribLocation(p, n) : gl.getUniformLocation(p, n)]));
  const LT = loc(pT, ["aPos", "aUV", "aNor", "uMVP", "uTex", "uEnc", "uEncre", "uAlpha", "uOmbre", "uLum"]), LC = loc(pC, ["aPos", "uMVP", "uCol", "uTaille", "uForme"]);
  let S = null;                                       // scène chargée
  const cam = { t: [0, 0, 0], D: 500, az: 0.5, el: 0.45 };

  // ── petites mathématiques ──
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2], cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => { const n = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / n, a[1] / n, a[2] / n]; };
  const oeil = () => add(cam.t, mul([Math.sin(cam.az) * Math.cos(cam.el), Math.sin(cam.el), Math.cos(cam.az) * Math.cos(cam.el)], cam.D));
  function repere() { const e = oeil(), f = norm(sub(cam.t, e)), r = norm(cross(f, [0, 1, 0])), u = cross(r, f); return { e, f, r, u }; }
  const FOV = 35 * Math.PI / 180;
  function mvp() {
    const { e, f, r, u } = repere(), a = canvas.width / canvas.height, t = 1 / Math.tan(FOV / 2), n = cam.D / 60, fa = cam.D * 12;
    const V = [r[0], u[0], -f[0], 0, r[1], u[1], -f[1], 0, r[2], u[2], -f[2], 0, -dot(r, e), -dot(u, e), dot(f, e), 1];
    const P = [t / a, 0, 0, 0, 0, t, 0, 0, 0, 0, (fa + n) / (n - fa), -1, 0, 0, 2 * fa * n / (n - fa), 0];
    const M = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let l = 0; l < 4; l++) { let s = 0; for (let k = 0; k < 4; k++) s += P[k * 4 + l] * V[c * 4 + k]; M[c * 4 + l] = s; }
    return M;
  }
  const tampon = (data, cible = gl.ARRAY_BUFFER) => { const b = gl.createBuffer(); gl.bindBuffer(cible, b); gl.bufferData(cible, data, gl.STATIC_DRAW); return b; };
  function texture(data, w, h) {
    const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.LUMINANCE, w, h, 0, gl.LUMINANCE, gl.UNSIGNED_BYTE, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); return t;
  }
  function liberer() { if (!S) return; for (const b of S.tampons) gl.deleteBuffer(b); for (const t of S.textures) gl.deleteTexture(t); S = null; }

  /* e : en-tête du serveur (i0, i1, j0, j1 = rectangle de nœuds ; i, j = le point ; pas ; miroir) · t : tableaux (surface, valide, texture, dessus, dessous, rubans, coupes) */
  function charger(e, t, garderCamera) {
    liberer();
    const nv = e.i1 - e.i0, nu = e.j1 - e.j0, P = t.surface, ok = t.valide, at = (a, i, j) => [a[(i * nu + j) * 3], a[(i * nu + j) * 3 + 1], a[(i * nu + j) * 3 + 2]];
    // repère local : X = sens de la largeur de la page (retourné si la page s'affiche en miroir), Y = vers le haut de la page, Z = X × Y (géométrie réelle, simplement tournée)
    let su = [0, 0, 0], sv = [0, 0, 0], c = [0, 0, 0], n = 0;
    for (let i = 0; i < nv - 1; i += 2) for (let j = 0; j < nu - 1; j += 2) if (ok[i * nu + j] && ok[i * nu + j + 1] && ok[(i + 1) * nu + j]) {
      const p = at(P, i, j); su = add(su, sub(at(P, i, j + 1), p)); sv = add(sv, sub(at(P, i + 1, j), p)); c = add(c, p); n++;
    }
    if (!n) return false;
    c = mul(c, 1 / n); const ci = e.i - e.i0, cj = e.j - e.j0; if (!e.tout && ok[ci * nu + cj]) c = at(P, ci, cj);     // segment entier : on tourne autour de son centre
    const pt = e.pas_tex ?? e.pas, dt = e.dec_tex ?? 0.5, prb = e.pas_ruban || [e.pas, e.pas];             // pixels de texture par pas du maillage (25/11 : maillage allégé du segment entier)
    const X = norm(mul(su, e.miroir ? -1 : 1)); let Y = mul(sv, -1); Y = norm(sub(Y, mul(X, dot(Y, X)))); const Z = cross(X, Y);
    const local = (a, k) => { const p = [a[k] - c[0], a[k + 1] - c[1], a[k + 2] - c[2]]; return [dot(p, X), dot(p, Y), dot(p, Z)]; };
    const conv = a => { const o = new Float32Array(a.length); for (let k = 0; k < a.length; k += 3) { if (a[k] !== a[k]) { o[k] = o[k + 1] = o[k + 2] = NaN; continue; } const q = local(a, k); o[k] = q[0]; o[k + 1] = q[1]; o[k + 2] = q[2]; } return o; };
    const Ls = conv(P), uv = new Float32Array(nv * nu * 2), nor = new Float32Array(nv * nu * 3), [th, tw] = t.texture.forme;
    for (let i = 0; i < nv; i++) for (let j = 0; j < nu; j++) {
      const k = i * nu + j; uv[k * 2] = (j * pt + dt) / tw; uv[k * 2 + 1] = (i * pt + dt) / th;
      const a = at(Ls, i, Math.min(j + 1, nu - 1)), b = at(Ls, i, Math.max(j - 1, 0)), d = at(Ls, Math.min(i + 1, nv - 1), j), f = at(Ls, Math.max(i - 1, 0), j);
      const nn = norm(cross(sub(a, b), sub(d, f))); nor[k * 3] = nn[0] || 0; nor[k * 3 + 1] = nn[1] || 0; nor[k * 3 + 2] = nn[2] || 1;
    }
    const idx = []; for (let i = 0; i < nv - 1; i++) for (let j = 0; j < nu - 1; j++) { const a = i * nu + j, b = a + 1, d = a + nu, f = d + 1; if (ok[a] && ok[b] && ok[d] && ok[f]) idx.push(a, b, d, b, f, d); }
    const I = new Uint16Array(nv * nu <= 65535 ? idx : []); const I32 = I.length ? null : new Uint32Array(idx);
    if (I32 && !gl.getExtension("OES_element_index_uint")) return false;
    const pts = a => { const o = []; if (a.length < nv * nu * 3) return new Float32Array(0); for (let i = 0; i < nv; i += 3) for (let j = 0; j < nu; j += 3) { const k = (i * nu + j) * 3; if (a[k] === a[k]) o.push(a[k], a[k + 1], a[k + 2]); } return new Float32Array(o); };
    const dessus = pts(conv(t.dessus)), dessous = pts(conv(t.dessous));
    const ruban = (r, img, pr) => {                              // r : (2, n, 3) bord haut puis bord bas ; img : (81, largeur)
      const m = r.forme[1], L = conv(r), pos = new Float32Array(m * 2 * 3), tuv = new Float32Array(m * 2 * 2), ind = [], [, iw] = img.forme;
      for (let k = 0; k < m; k++) for (let b = 0; b < 2; b++) {
        const s = (b * m + k) * 3, d = (k * 2 + b) * 3; pos[d] = L[s]; pos[d + 1] = L[s + 1]; pos[d + 2] = L[s + 2]; tuv[(k * 2 + b) * 2] = (k * pr + 0.5) / iw; tuv[(k * 2 + b) * 2 + 1] = b ? 1 : 0;
      }
      for (let k = 0; k < m - 1; k++) ind.push(k * 2, k * 2 + 1, k * 2 + 2, k * 2 + 1, k * 2 + 3, k * 2 + 2);
      return { pos: tampon(pos), uv: tampon(tuv), nor: tampon(new Float32Array(m * 2 * 3).fill(1)), idx: tampon(new Uint16Array(ind), gl.ELEMENT_ARRAY_BUFFER), n: ind.length, tex: texture(img, iw, img.forme[0]) };
    };
    const ligne = (pas, fixe, long, enU) => { const o = []; for (let k = 0; k < long - 1; k++) { const a = enU ? fixe * nu + k : k * nu + fixe, b = enU ? a + 1 : a + nu; if (ok[a] && ok[b]) o.push(Ls[a * 3], Ls[a * 3 + 1], Ls[a * 3 + 2], Ls[b * 3], Ls[b * 3 + 1], Ls[b * 3 + 2]); } return new Float32Array(o); };
    const lu = ligne(1, ci, nu, true), lv = ligne(1, cj, nv, false);
    const ru = ruban(t.ruban_u, t.coupe_u, prb[0]), rv = ruban(t.ruban_v, t.coupe_v, prb[1]);
    let ext = 0; for (let k = 0; k < Ls.length; k += 3) if (ok[k / 3]) ext = Math.max(ext, Math.hypot(Ls[k], Ls[k + 1]));
    S = { e, nv, nu, Ls, ok, idx, pos: tampon(Ls), uv: tampon(uv), nor: tampon(nor), ind: tampon(I32 || I, gl.ELEMENT_ARRAY_BUFFER), n: idx.length, type: I32 ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT,
      tex: texture(t.texture, tw, th), dessus: tampon(dessus), nDessus: dessus.length / 3, dessous: tampon(dessous), nDessous: dessous.length / 3, ru, rv, lu: tampon(lu), nLu: lu.length / 3, lv: tampon(lv), nLv: lv.length / 3, ext };
    S.tampons = [S.pos, S.uv, S.nor, S.ind, S.dessus, S.dessous, S.lu, S.lv, ru.pos, ru.uv, ru.nor, ru.idx, rv.pos, rv.uv, rv.nor, rv.idx]; S.textures = [S.tex, ru.tex, rv.tex];
    S.enc = (t.encre && t.encre.forme[0] === th && t.encre.forme[1] === tw) ? texture(t.encre, tw, th) : null; if (S.enc) S.textures.push(S.enc);
    if (!garderCamera) { cam.t = [0, 0, 0]; cam.D = Math.max(ext * 3.3, 60); cam.az = 0.35; cam.el = 0.45; }
    dessiner(); return true;
  }

  function dessiner() {
    const w = Math.max(1, Math.round(canvas.clientWidth * (window.devicePixelRatio || 1))), h = Math.max(1, Math.round(canvas.clientHeight * (window.devicePixelRatio || 1)));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, w, h); gl.clearColor(0.043, 0.039, 0.031, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!S) return;
    const M = mvp(), { f } = repere(); gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.disable(gl.BLEND); gl.depthMask(true);
    const tex = (o, ind, texr, n, type, alpha, ombre, encT, encF) => {
      gl.useProgram(pT); gl.uniformMatrix4fv(LT.uMVP, false, M); gl.uniform1f(LT.uAlpha, alpha); gl.uniform1f(LT.uOmbre, ombre); gl.uniform3f(LT.uLum, -f[0], -f[1], -f[2]);
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, encT || texr); gl.uniform1i(LT.uEnc, 1); gl.uniform1f(LT.uEncre, encT ? (encF || 0) : 0);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texr); gl.uniform1i(LT.uTex, 0);
      for (const [a, b, k] of [[LT.aPos, o.pos, 3], [LT.aUV, o.uv, 2], [LT.aNor, o.nor, 3]]) { gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.enableVertexAttribArray(a); gl.vertexAttribPointer(a, k, gl.FLOAT, false, 0, 0); }
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ind); gl.drawElements(gl.TRIANGLES, n, type, 0);
    };
    const col = (buf, n, mode, c, taille, forme) => {
      if (!n) return; gl.useProgram(pC); gl.uniformMatrix4fv(LC.uMVP, false, M); gl.uniform4fv(LC.uCol, c); gl.uniform1f(LC.uTaille, taille); gl.uniform1f(LC.uForme, forme);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(LC.aPos); gl.vertexAttribPointer(LC.aPos, 3, gl.FLOAT, false, 0, 0); gl.drawArrays(mode, 0, n);
    };
    gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1.5, 1.5); tex(S, S.ind, S.tex, S.n, S.type, 1, 1, S.enc, opt.encre); gl.disable(gl.POLYGON_OFFSET_FILL);
    col(S.lu, S.nLu, gl.LINES, [0.90, 0.62, 0.0, 1], 1, 0); col(S.lv, S.nLv, gl.LINES, [0.34, 0.71, 0.91, 1], 1, 0);
    const dp = window.devicePixelRatio || 1;
    if (opt.voisines) { col(S.dessus, S.nDessus, gl.POINTS, [0.90, 0.62, 0.0, 1], 6 * dp, 1); col(S.dessous, S.nDessous, gl.POINTS, [0.34, 0.71, 0.91, 1], 3.5 * dp, 0); }
    if (opt.coupes) { gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false); tex(S.ru, S.ru.idx, S.ru.tex, S.ru.n, gl.UNSIGNED_SHORT, 0.62, 0); tex(S.rv, S.rv.idx, S.rv.tex, S.rv.n, gl.UNSIGNED_SHORT, 0.62, 0); gl.depthMask(true); gl.disable(gl.BLEND); }
  }

  /* clic → nœud (ligne, colonne, fractions comprises) de la surface sous le curseur, ou null */
  function viser(px, py) {
    if (!S) return null;
    const { e, f, r, u } = repere(), a = canvas.clientWidth / canvas.clientHeight, t = Math.tan(FOV / 2), x = (px / canvas.clientWidth * 2 - 1) * t * a, y = (1 - py / canvas.clientHeight * 2) * t;
    const d = norm(add(f, add(mul(r, x), mul(u, y)))), L = S.Ls, nu = S.nu; let best = Infinity, res = null;
    for (let q = 0; q < S.idx.length; q += 3) {
      const A = S.idx[q], B = S.idx[q + 1], C = S.idx[q + 2], pa = [L[A * 3], L[A * 3 + 1], L[A * 3 + 2]], e1 = [L[B * 3] - pa[0], L[B * 3 + 1] - pa[1], L[B * 3 + 2] - pa[2]], e2 = [L[C * 3] - pa[0], L[C * 3 + 1] - pa[1], L[C * 3 + 2] - pa[2]];
      const h = cross(d, e2), det = dot(e1, h); if (Math.abs(det) < 1e-9) continue;
      const s = sub(e, pa), uu = dot(s, h) / det; if (uu < 0 || uu > 1) continue;
      const qv = cross(s, e1), vv = dot(d, qv) / det; if (vv < 0 || uu + vv > 1) continue;
      const tt = dot(e2, qv) / det; if (tt > 0 && tt < best) { best = tt; const w = 1 - uu - vv, li = n => Math.floor(n / nu), co = n => n % nu; res = [li(A) * w + li(B) * uu + li(C) * vv, co(A) * w + co(B) * uu + co(C) * vv]; }
    }
    const pp = S.e.pas_page ?? S.e.pas; return res && { v: (res[0] + S.e.i0) * pp, u: (res[1] + S.e.j0) * pp };
  }

  let glisse = null;
  canvas.addEventListener("contextmenu", ev => ev.preventDefault());
  canvas.addEventListener("pointerdown", ev => { canvas.setPointerCapture(ev.pointerId); glisse = { x: ev.clientX, y: ev.clientY, x0: ev.clientX, y0: ev.clientY, b: ev.button }; });
  canvas.addEventListener("pointermove", ev => {
    if (!glisse) return; const dx = ev.clientX - glisse.x, dy = ev.clientY - glisse.y; glisse.x = ev.clientX; glisse.y = ev.clientY;
    if (glisse.b === 0 && !ev.shiftKey) { cam.az -= dx * 0.008; cam.el = Math.max(-1.5, Math.min(1.5, cam.el + dy * 0.008)); }
    else { const { r, u } = repere(), k = cam.D * Math.tan(FOV / 2) * 2 / canvas.clientHeight; cam.t = add(cam.t, add(mul(r, -dx * k), mul(u, dy * k))); }
    dessiner();
  });
  canvas.addEventListener("pointerup", ev => {
    if (!glisse) return; const bouge = Math.hypot(ev.clientX - glisse.x0, ev.clientY - glisse.y0), b = glisse.b; glisse = null;
    if (b === 0 && bouge < 4) { const rc = canvas.getBoundingClientRect(), p = viser(ev.clientX - rc.left, ev.clientY - rc.top); if (p && surClic) surClic(p); }
  });
  canvas.addEventListener("wheel", ev => { ev.preventDefault(); cam.D = Math.max(20, Math.min(20000, cam.D * Math.exp(ev.deltaY * 0.0012))); dessiner(); }, { passive: false });
  return { ok: true, charger, dessiner, viser, opt, cam, grand: !!gl.getExtension("OES_element_index_uint"), get scene() { return S; } };      // grand : plus de 65 535 sommets possibles
}
