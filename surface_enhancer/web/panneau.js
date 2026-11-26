/* Surface Enhancer — the left panel: what is in it, in which order, with which icon, and the ⓘ cards.
   This file only builds and explains the interface. It is loaded BEFORE app.js, which then finds every control by its id
   (the ids are the ones app.js has always used). Nothing here changes a retouch.
   Groups: by hand · automatic · display · quality · history. Each automatic tool keeps its own options in a drawer under it.
   Every control has an ⓘ: hover it (or click it to keep it open) for what it does, how to use it, and a small animation. */
"use strict";
(() => {
  const corps = document.getElementById("panneauCorps"); if (!corps) return;
  const $ = id => document.getElementById(id);

  // ───────────── icons (24 × 24, drawn with the text colour) ─────────────
  const rond = (x, y, r) => `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
  const onde = y => `M3 ${y}c3-2 6 2 9 0s6-2 9 0`;
  const IC = {
    regarder: "M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" + rond(12, 12, 3),
    aimant: "M6 4v8a6 6 0 0 0 12 0V4h-4v8a2 2 0 0 1-4 0V4zM6 8h4M14 8h4",
    bord: onde(17) + onde(12) + "M12 8V3M9.5 5.5L12 3l2.5 2.5",
    bord2: onde(7) + onde(12) + "M12 16v5M9.5 18.5L12 21l2.5-2.5",
    pousser: "M12 4v16M8 8l4-4 4 4M8 16l4 4 4-4",
    feuille: onde(6) + onde(18) + "M12 9v6M9.5 12.5L12 15l2.5-2.5",
    marquer: "M5 21V4h12l-2.5 4 2.5 4H5",
    gomme: "M4 15l8-9 7 6-6 8H8zM9.5 9l7 6M3 20h18",
    suivre: rond(5, 18, 2) + "M7 17c5-1 3-9 9-9h4M17 5l3 3-3 3",
    aimant_partout: "M7 3v7a5 5 0 0 0 10 0V3h-3.5v7a1.5 1.5 0 0 1-3 0V3zM3 20h18M6 17v3M12 17v3M18 17v3",
    page_dessus: "M4 17l8 4 8-4M4 12.5l8 4 8-4M12 9V3M9.5 5.5L12 3l2.5 2.5",
    page_dessous: "M4 7l8-4 8 4M4 11.5l8-4 8 4M12 15v6M9.5 18.5L12 21l2.5-2.5",
    marches: "M3 18h6v-6h6V6h6M3 21h18",
    fibres: "M6 3v18M12 3v18M18 3v18M3 6h18M3 12h18M3 18h18",
    etendre: "M3 5h9v14H3zM12 12h9M17.5 8.5L21 12l-3.5 3.5",
    main: "M5 3l14 8-6 1.8L11 19z",
    auto: "M5 19L15.5 8.5M13.5 6.5l4 4M19 3v4M17 5h4M6 4v3M4.5 5.5h3M19 14v3M17.5 15.5h3",
    affichage: "M12 3l9 5-9 5-9-5zM3 12.5l9 5 9-5M3 17l9 5 9-5",
    qualite: "M4 18a9 9 0 1 1 16 0M12 14l4.5-6" + rond(12, 14, 1.2),
    histoire: "M3.5 12a8.5 8.5 0 1 0 2.6-6.1M3 4v5h5M12 7.5V12l3 2",
    reglages: "M3 7h9M17 7h4M3 17h4M12 17h9" + rond(14.5, 7, 2.3) + rond(9.5, 17, 2.3),
    cible: rond(12, 12, 8) + rond(12, 12, 3) + "M12 1v5M12 18v5M1 12h5M18 12h5",
    figer: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
    exporter: "M12 15V3M8 7l4-4 4 4M4 14v6h16v-6",
    vue2d: "M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2zM9 4v14M15 6v14",
    vue3d: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9",
  };
  const ic = n => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="${IC[n] || ""}"/></svg>`;
  const info = k => `<button type="button" class="i" data-info="${k}" aria-label="How it works">i</button>`;

  // ───────────── what the panel holds ─────────────
  const OUTILS = [["regarder", "R", "Look"], ["aimant", "A", "Magnet"], ["bord", "D", "Edge magnet ▲"], ["bord2", "X", "Edge magnet ▼"],
    ["pousser", "B", "Brush ± 1 vx"], ["feuille", "F", "Shift one sheet"], ["marquer", "M", "Mark a problem"], ["gomme", "G", "Erase marks"]];
  const ASTUCE = {
    regarder: "Move the mouse: the sections follow. <b>Right-click</b> pins them. Then drag the orange line in a section.",
    aimant: "<b>Drag on the page</b>: the surface snaps to the nearest sheet under the brush.",
    bord: "<b>Drag</b>: snaps to the sheet, then sits above its core. <b>Shift</b> + drag: below.",
    bord2: "<b>Drag</b>: snaps to the sheet, then sits below its core. <b>Shift</b> + drag: above.",
    pousser: "<b>Drag</b>: the surface goes up 1 voxel per pass. <b>Shift</b> + drag: down.",
    feuille: "<b>Paint a region</b>, then send it to the sheet above or below.",
    marquer: "<b>Paint what looks wrong</b>: the area is kept and scored on its own.",
    gomme: "<b>Paint</b> over marked areas to erase the marks.",
  };
  const AUTOS = [
    ["suivre", "Follow the sheet", "from the pinned point, never jumping", "autoSaut autoPont"],
    ["aimant_partout", "Magnet everywhere", "snap the whole surface to the nearest sheet", "borne*"],
    ["page_dessus", "Whole page: sheet above", "the page moves to the next sheet up", ""],
    ["page_dessous", "Whole page: sheet below", "the page moves to the next sheet down", ""],
    ["marches", "Remove steps", "bring regions cut by a jump back together", "autoSeuil"],
    ["fibres", "Best fibres", "the depth where the fibre grid is sharpest", "autoPortee"],
    ["etendre", "Extend the surface", "grow a band beyond an edge", "extCote extLargeur"],
  ];
  const REGLAGES = {            // id: [label, min, max, step, value]
    portee: ["Brush size / reach", 0.1, 3, 0.05, 0.5], borne: ["Magnet: at most", 2, 16, 1, 6], bord: ["Edge: from core", 0.5, 6, 0.5, 2],
    autoSaut: ["Max jump", 0.5, 3, 0.25, 1.5], autoPont: ["Bridge gaps", 0, 1, 0.05, 0.3], autoSeuil: ["A step is above", 1.5, 8, 0.5, 3],
    autoPortee: ["Search ±", 2, 12, 1, 6], extLargeur: ["Width", 0.25, 5, 0.25, 2], couche: ["Depth", -8, 8, 1, 0], opEncre: ["Ink opacity", 0.1, 1, 0.05, 0.9],
  };
  const curseur = (id, extra = "") => { const [l, a, b, s, v] = REGLAGES[id];
    return `<label class="reglage" ${extra}><span>${l} ${info(id === "bord" ? "bordN" : id)}</span><input id="${id}" type="range" min="${a}" max="${b}" step="${s}" value="${v}"><output${id === "opEncre" ? "" : ` id="${id}Val"`}></output></label>`; };
  const copie = id => `<label class="reglage" data-copie="${id}"><span>${REGLAGES[id][0]} ${info(id === "bord" ? "bordN" : id)}</span></label>`;
  const tiroir = t => t.split(" ").filter(Boolean).map(id => id.endsWith("*") ? copie(id.slice(0, -1)) : id === "extCote"
    ? `<div class="reglage"><span>Side ${info("extCote")}</span><select id="extCote"><option value="droite">right of the page</option><option value="gauche">left of the page</option><option value="haut">top of the page</option><option value="bas">bottom of the page</option></select></div>`
    : curseur(id)).join("");
  const groupe = (cle, icone, titre, sous, dedans, ouvert = true) =>
    `<details class="grp" data-grp="${cle}"${ouvert ? " open" : ""}><summary>${ic(icone)}<span class="gt">${titre}</span><span class="gs">${sous}</span><span class="chevron" aria-hidden="true"></span></summary><div class="gc">${dedans}</div></details>`;

  corps.innerHTML = `
    <div class="rapide">
      <div class="bascule" role="group" aria-label="View">
        <button id="b2d" class="actif">${ic("vue2d")} Flat page</button><button id="b3d">${ic("vue3d")} 3D shape</button>${info("vues")}
      </div>
      <div class="defaire"><button id="annuler" aria-label="Undo"><span class="fl">↶</span> Undo <kbd>Ctrl Z</kbd></button><button id="retablir" aria-label="Redo"><span class="fl">↷</span> Redo <kbd>Ctrl Y</kbd></button>${info("defaire")}</div>
    </div>` +
    groupe("main", "main", "By hand", "one spot at a time", `
      <div class="outils">${OUTILS.map(([o, k, l], n) => `<div class="outil"><button data-outil="${o}"${n ? "" : ' class="actif"'}><kbd>${k}</kbd>${ic(o)}<span>${l}</span></button>${info(o)}</div>`).join("")}</div>
      <div class="options">
        <div id="outilAstuce" class="astuce"></div>
        <div id="boutonsFeuille" class="ligne" hidden>
          <button id="feuilleHaut">▲ sheet above <kbd>PgUp</kbd></button><button id="feuilleBas">▼ sheet below <kbd>PgDn</kbd></button><button id="feuilleVider">clear</button>
        </div>
        ${curseur("portee")}${curseur("borne", 'data-pour="aimant bord bord2"')}${curseur("bord", 'data-pour="bord bord2"')}
      </div>`) +
    groupe("auto", "auto", "Automatic", "whole segment · preview first", `
      <div id="auto">
        <p class="mode"><b>1</b> pick a tool <span>→</span> <b>2</b> check the preview <span>→</span> <b>3</b> Apply</p>
        <div class="autos">${AUTOS.map(([o, l, d, t]) => `<div class="auto" data-nom="${o}"><button data-auto="${o}" class="lancer">${ic(o)}<span class="noms"><b>${l}${o === "etendre" ? ' <em class="beta">beta</em>' : ""}</b><small>${d}</small></span></button>${t
          ? `<button type="button" class="rouage" aria-expanded="false" aria-label="Options of ${l}" title="Options">${ic("reglages")}</button>` : `<span class="rouage vide"></span>`}${info(o)}${t ? `<div class="tiroir" hidden>${tiroir(t)}</div>` : ""}</div>`).join("")}</div>
        <div id="autoCarte" class="carte petit" hidden>
          <div id="autoChoix" class="ligne" hidden><button id="autoAppliquer" class="principal etire">✓ Apply</button><button id="autoAnnuler">✕ Cancel</button><span class="doux">nothing is written until you apply</span></div>
          <div id="autoBarre" class="barre" hidden><i></i></div>
          <div id="autoBilan"></div>
          <div id="autoLegende" class="legende" hidden>
            <span><i class="pat pa-haut"></i> moves towards the top</span><span><i class="pat pa-bas"></i> moves towards the bottom</span>
            <span><i class="pat pa-gros"></i> solid: 4 vx or more (changes sheet)</span><span><i class="pat pa-refus"></i> white dots: proposed, refused</span>
          </div>
        </div>
        <div class="communs">
          <div class="sousTitre">For all automatic tools</div>
          <div class="reglage"><span>Sit on ${info("autoBord")}</span><select id="autoBord"><option value="0">the core of the sheet</option><option value="-1">N vx from the core, towards the top</option><option value="1">N vx from the core, towards the bottom</option></select></div>
          <div id="autoBordN" hidden>${copie("bord")}</div>
          <label class="coche"><input id="autoMarquees" type="checkbox"> only in the marked areas ${info("autoMarquees")}</label>
          <label class="coche"><input id="autoGreffe" type="checkbox" checked> keep only the winning parts ${info("autoGreffe")}</label>
        </div>
        <div id="autoVieux" class="doux petit" hidden>These buttons need the server to be restarted (it is still running the previous version).</div>
      </div>`) +
    groupe("affichage", "affichage", "Display", "what you see on the page", `
      ${curseur("couche")}
      <div class="reglage"><span>Ink ${info("encre")}</span><select id="encre"></select></div>
      <label class="reglage" id="opEncreLigne"><span>Ink opacity</span><input id="opEncre" type="range" min="0.1" max="1" step="0.05" value="0.9"><output></output></label>
      <label class="coche"><input id="voirZones" type="checkbox" checked> <span class="pat pat-zone"></span> problem areas <kbd>Z</kbd>${info("voirZones")}</label>
      <label class="coche"><input id="voirScore" type="checkbox"> <span class="pat pat-score"></span> score map <kbd>S</kbd>${info("voirScore")}</label>
      <label class="coche"><input id="voirFibres" type="checkbox"> <span class="pat pat-fibres"></span> fibre score map <kbd>Q</kbd>${info("voirFibres")}</label>
      <label class="coche"><input id="voirPics" type="checkbox" checked> <span class="pat pat-pics"></span> detected sheets in the sections <kbd>P</kbd>${info("voirPics")}</label>
      <label class="coche"><input id="miroir" type="checkbox"> <span class="pat pat-miroir"></span> mirror left-right ${info("miroir")}</label>`) +
    groupe("qualite", "qualite", "Quality", "score 0–100 per 0.3 mm tile", `
      <div id="score" class="carte">
        <div class="gros"><span id="notePage">–</span><small> / 100 · whole page</small>${info("score")}</div>
        <div id="noteDiff" class="diff"></div>
        <table id="tabScore"></table>
        <div id="derniere" class="derniere">Last retouch: none yet.</div>
      </div>
      <div class="ligne"><button id="pire" class="principal etire">${ic("cible")} Go to the worst tile <kbd>N</kbd></button>${info("pire")}</div>
      <div class="ligne"><button id="sautsBtn" type="button" class="etire">${ic("marches")} Find sheet jumps <kbd>J</kbd></button>${info("sauts")}</div>
      <div id="sautsCarte" class="carte petit" hidden></div>
      <label class="coche"><input id="pireMarquees" type="checkbox"> only in the marked areas</label>
      <div id="sousCurseur" class="carte petit">Move the mouse over the page: the tile details show here.</div>
      <div class="legende">
        <span><i class="pat p-bon"></i> ≥ 80 good</span><span><i class="pat p-moyen"></i> 60–80 fair (dots)</span>
        <span><i class="pat p-faible"></i> 40–60 weak (hatching)</span><span><i class="pat p-mauvais"></i> &lt; 40 bad (cross-hatching)</span>
      </div>`) +
    groupe("histoire", "histoire", "History and export", "nothing is ever lost", `
      <div class="ligne"><span id="nGestes" class="compte"></span></div>
      <div class="ligne"><button id="figer">${ic("figer")} Freeze this version</button>${info("figer")}<button id="exporter" class="principal">${ic("exporter")} Export…</button>${info("exporter")}</div>
      <div id="message" class="doux petit" role="status" aria-live="polite"></div>
      <p class="doux petit pied">The original surface is never modified: you work on a copy. <span id="chemins"></span></p>`, false);

  // ───────────── animations of the ⓘ cards: a small section of the scan (sheets in grey, the surface in orange) ─────────────
  const L = 300, H = 120, XS = Array.from({ length: 31 }, (_, i) => i * 10);
  const trace = fn => XS.map((x, i) => (i ? "L" : "M") + x + " " + fn(x).toFixed(1)).join("");
  const S = x => 60 + 9 * Math.sin(x / 40), S1 = x => 40 + 8 * Math.sin(x / 42), S2 = x => 82 + 8 * Math.sin(x / 42 + 0.5), cloche = (x, c, l) => Math.exp(-(((x - c) / l) ** 2));
  const feuille = fn => `<path d="${trace(fn)}" class="af"/><path d="${trace(fn)}" class="afc"/>`;
  const cadre = (dedans, legende) => `<svg class="anim" viewBox="0 0 ${L} ${H}" role="img" aria-label="${legende}"><rect width="${L}" height="${H}" rx="6" class="afond"/>${dedans}</svg>`;
  const temps = 'dur="4.2s" repeatCount="indefinite"';
  let n = 0;
  // the surface changes all at once, from `avant` to `apres`
  const fondu = (avant, apres, plus = "") => `<path class="as" d="${trace(avant)}"><animate attributeName="d" ${temps} values="${trace(avant)};${trace(avant)};${trace(apres)};${trace(apres)};${trace(avant)}" keyTimes="0;0.2;0.5;0.92;1"/></path>${plus}`;
  // a brush sweeps from left to right: behind it the surface is `apres`, ahead of it still `avant`
  const balai = (avant, apres, { pinceau = true, de = 0, a = L } = {}) => { const k = ++n, v = `${de};${de};${a};${a}`, kt = 'keyTimes="0;0.12;0.78;1"';
    return `<clipPath id="ca${k}"><rect y="0" height="${H}" x="0" width="${de}"><animate attributeName="width" ${temps} values="${v}" ${kt}/></rect></clipPath>
      <clipPath id="cb${k}"><rect y="0" height="${H}" x="${de}" width="${L}"><animate attributeName="x" ${temps} values="${v}" ${kt}/></rect></clipPath>
      ${avant ? `<path class="as" d="${trace(avant)}" clip-path="url(#cb${k})"/>` : ""}<path class="as" d="${trace(apres)}" clip-path="url(#ca${k})"/>
      ${pinceau ? `<circle class="ap" r="15" cy="${H / 2}" cx="${de}"><animate attributeName="cx" ${temps} values="${v}" ${kt}/></circle>` : ""}`; };
  const loin = x => S(x) + 17 + 5 * Math.sin(x / 15);
  const page = dedans => `<rect x="18" y="12" width="150" height="96" rx="3" class="apage"/>${dedans}`;
  const hachure = `<pattern id="ah" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#1c2a33"/><rect width="2" height="6" fill="#56B4E9"/></pattern>`;
  const tache = `<path d="M50 45c14-14 46-8 60 6s8 34-14 38-46 2-54-14 0-22 8-30z" fill="url(#ah)" stroke="#56B4E9" stroke-width="1.5"`;
  const ANIM = {
    regarder: () => cadre(page(`<path d="M30 80C60 30 110 90 150 40" class="achemin"/><g><circle r="5" class="apt"/><path d="M-12 0H12M0 -12V12" class="acroix"/><animateMotion ${temps} path="M30 80C60 30 110 90 150 40" keyTimes="0;0.6;1" keyPoints="0;1;1" calcMode="linear"/></g>
      <rect x="143" y="33" width="14" height="14" class="aepingle"><animate attributeName="opacity" ${temps} values="0;0;1;1" keyTimes="0;0.62;0.66;1"/></rect>`) +
      `<g transform="translate(182 30)"><rect width="104" height="60" rx="3" fill="#000"/><clipPath id="cr"><rect width="104" height="60"/></clipPath><g clip-path="url(#cr)"><g><path d="M-80 32c20-10 40 10 60 0s40-10 60 0 40 10 60 0 40-10 60 0 40 10 60 0" class="af"/><path d="M-80 32c20-10 40 10 60 0s40-10 60 0 40 10 60 0 40-10 60 0 40 10 60 0" class="as"/>
      <animateTransform attributeName="transform" type="translate" ${temps} values="0 0;-60 0;-60 0" keyTimes="0;0.6;1"/></g></g></g><text x="234" y="104" class="at">the sections follow</text>`, "The sections follow the mouse; a right-click pins them"),
    aimant: () => cadre(feuille(S) + balai(loin, S), "The surface snaps to the sheet under the brush"),
    bord: () => cadre(feuille(S) + balai(loin, x => S(x) - 8), "The surface sits above the core of the sheet"),
    bord2: () => cadre(feuille(S) + balai(loin, x => S(x) + 8), "The surface sits below the core of the sheet"),
    pousser: () => { const b = x => S(x) + 14, p = k => trace(x => b(x) - k * 5 * cloche(x, 150, 42));
      return cadre(feuille(S) + `<path class="as" d="${p(0)}"><animate attributeName="d" ${temps} calcMode="discrete" values="${p(0)};${p(1)};${p(2)};${p(3)};${p(3)}" keyTimes="0;0.2;0.4;0.6;1"/></path><circle class="ap" r="26" cx="150" cy="70"/><text x="150" y="112" class="at">one voxel per pass</text>`, "The surface rises one voxel per pass"); },
    feuille: () => { const m = x => cloche(x, 150, 40) > 0.5 ? 1 : 0, lis = x => Math.min(1, Math.max(0, (60 - Math.abs(x - 150)) / 18));
      return cadre(feuille(S1) + feuille(S2) + `<rect x="100" y="8" width="100" height="104" rx="8" class="aregion"/>` + fondu(S2, x => S2(x) + (S1(x) - S2(x)) * lis(x)), "The painted region moves to the sheet above"); },
    marquer: () => cadre(hachure + page(`<clipPath id="cm"><rect x="0" y="0" height="${H}" width="0"><animate attributeName="width" ${temps} values="30;30;140;140" keyTimes="0;0.12;0.78;1"/></rect></clipPath>${tache} clip-path="url(#cm)"/>
      <circle class="ap" r="14" cy="62"><animate attributeName="cx" ${temps} values="30;30;140;140" keyTimes="0;0.12;0.78;1"/></circle>`) + `<text x="234" y="56" class="at">kept, scored</text><text x="234" y="70" class="at">on its own</text>`, "Painting marks a problem area"),
    gomme: () => cadre(hachure + page(`<clipPath id="cg"><rect y="0" height="${H}" width="${L}" x="0"><animate attributeName="x" ${temps} values="30;30;140;140" keyTimes="0;0.12;0.78;1"/></rect></clipPath>${tache} clip-path="url(#cg)"/>
      <circle class="ap" r="14" cy="62"><animate attributeName="cx" ${temps} values="30;30;140;140" keyTimes="0;0.12;0.78;1"/></circle>`) + `<text x="234" y="62" class="at">marks erased</text>`, "Painting erases the marks"),
    suivre: () => { const faux = x => x < 150 ? S1(x) : x > 180 ? S2(x) : S1(x) + (S2(x) - S1(x)) * (x - 150) / 30;
      return cadre(feuille(S1) + feuille(S2) + balai(faux, S1, { pinceau: false, de: 30 }) + `<circle cx="30" cy="${S1(30)}" r="5" class="apt"/><text x="34" y="18" class="at" text-anchor="start">anchor</text><text x="228" y="112" class="at">brought back, no jump</text>`, "From the anchor the surface follows one sheet and never jumps"); },
    aimant_partout: () => cadre(feuille(S) + fondu(loin, S), "The whole surface snaps to the nearest sheet"),
    page_dessus: () => cadre(feuille(S1) + feuille(S2) + fondu(S2, S1), "The whole page moves to the sheet above"),
    page_dessous: () => cadre(feuille(S1) + feuille(S2) + fondu(S1, S2), "The whole page moves to the sheet below"),
    marches: () => cadre(feuille(S) + feuille(x => S(x) + 30) + fondu(x => S(x) + (x > 175 ? 30 : 0), S, `<path d="M175 20v80" class="amarche"/><text x="175" y="14" class="at">step</text>`), "A region cut by a step is brought back onto the reference sheet"),
    fibres: () => { const g = [...Array(9)].map((_, i) => `<path d="M${40 + i * 14} 14v92"/>`).join("") + [...Array(6)].map((_, i) => `<path d="M30 ${22 + i * 15}h130"/>`).join("");
      return cadre(`<filter id="fl"><feGaussianBlur stdDeviation="3.2"/></filter><rect x="24" y="10" width="142" height="100" rx="3" class="apage"/><g class="agrille" filter="url(#fl)">${g}</g><g class="agrille"><animate attributeName="opacity" ${temps} values="0;0;1;1;0" keyTimes="0;0.2;0.55;0.92;1"/>${g}</g>
        <path d="M222 16v88" class="aaxe"/><path d="M212 0h20" class="as"><animateTransform attributeName="transform" type="translate" ${temps} values="0 84;0 84;0 46;0 46;0 84" keyTimes="0;0.2;0.55;0.92;1"/></path><text x="254" y="20" class="at">depth</text><text x="254" y="108" class="at">sharpest</text>`, "The depth that gives the sharpest fibre grid is kept"); },
    etendre: () => { const k = ++n; return cadre(feuille(S) + `<path d="M266 20l-6 14 8 12-8 14 8 14-6 14" class="amarche"/><text x="266" y="14" class="at">tear</text>
      <clipPath id="ce${k}"><rect y="0" height="${H}" x="0" width="170"><animate attributeName="width" ${temps} values="170;170;256;256" keyTimes="0;0.15;0.75;1"/></rect></clipPath><path class="as" d="${trace(S)}" clip-path="url(#ce${k})"/><path d="M170 14v92" class="aaxe"/><text x="166" y="112" class="at" text-anchor="end">edge of the surface</text>`, "A band is added beyond the edge and stops where the sheet is no longer sure"); },
  };
  ANIM.portee = () => cadre(feuille(S) + `<path class="as" d="${trace(S)}"/><circle class="ap" cx="150" cy="60"><animate attributeName="r" ${temps} values="10;34;34;10;10" keyTimes="0;0.4;0.5;0.9;1"/></circle>`, "The brush grows and shrinks");
  ANIM.borne = () => cadre(feuille(S) + feuille(x => S(x) + 42) + fondu(x => S(x) + 20, S) + `<path d="M40 60v40M36 64l4-4 4 4M36 96l4 4 4-4" class="aaxe"/><text x="46" y="114" class="at" text-anchor="start">never further than this</text>`, "The magnet only reaches sheets closer than the limit");
  ANIM.autoBord = () => cadre(feuille(S) + `<path class="as" d="${trace(S)}"><animate attributeName="d" ${temps} calcMode="discrete" values="${trace(S)};${trace(x => S(x) - 8)};${trace(x => S(x) + 8)};${trace(S)}" keyTimes="0;0.33;0.66;1"/></path>`, "On the core of the sheet, above it, or below it");

  // every other card has its animation too
  const clign = (v = "0;0;1;1;0", kt = "0;0.2;0.35;0.85;1") => `<animate attributeName="opacity" ${temps} values="${v}" keyTimes="${kt}"/>`;
  const orHach = `<pattern id="ao" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="6" height="6" fill="#4a3a1a"/><rect width="2" height="6" fill="#E69F00"/></pattern>`;
  const grande = dedans => `<rect x="60" y="10" width="180" height="100" rx="3" class="apage"/>${dedans}`;
  const carreaux = (fn) => [...Array(15)].map((_, i) => { const x = 60 + (i % 5) * 36, y = 10 + Math.floor(i / 5) * 33.3; return fn(i, x, y); }).join("");
  const grille = carreaux((i, x, y) => `<rect x="${x}" y="${y}" width="36" height="33.3" fill="none" stroke="#2f2a22"/>`);
  const points = fn => XS.filter((_, i) => i % 2 === 0).map(x => `<rect x="${x - 1.5}" y="${fn(x) - 1.5}" width="3" height="3" fill="#56B4E9"/>`).join("");
  Object.assign(ANIM, {
    vues: () => { const plat = "M40 30L260 30L260 90L40 90Z", forme = "M40 44Q150 2 260 34L260 86Q150 122 40 76Z";
      return cadre(`<path class="apage" stroke="#E69F00" stroke-width="2" d="${plat}"><animate attributeName="d" ${temps} values="${plat};${plat};${forme};${forme};${plat}" keyTimes="0;0.25;0.5;0.9;1"/></path>
        <text x="150" y="64" class="at">flat page</text><text x="150" y="114" class="at">Tab: the same surface, as it lies in the scan</text>`, "The flat page and the 3D shape are the same surface"); },
    defaire: () => cadre(feuille(S) + fondu(S, loin) + `<text x="150" y="20" class="at" style="font-size:20px">↶${clign("0;0;1;1;0", "0;0.86;0.9;0.98;1")}</text><text x="150" y="112" class="at">a gesture, then Ctrl + Z: back as it was</text>`, "A gesture, then undo: the surface is back as it was"),
    couche: () => cadre(feuille(S) + `<path class="as" d="${trace(S)}"/><path class="aj" d="${trace(S)}"><animate attributeName="d" ${temps} values="${trace(S)};${trace(x => S(x) - 14)};${trace(S)};${trace(x => S(x) + 14)};${trace(S)}" keyTimes="0;0.25;0.5;0.75;1"/></path>
      <text x="150" y="112" class="at">yellow dots: the depth shown · the surface stays</text>`, "The page is shown above or below the surface, which does not move"),
    encre: () => cadre(grande(`<g fill="#F0E442" font-family="Georgia,serif" font-size="30" text-anchor="middle">${clign()}<text x="150" y="56">ΚΑΙ ΤΟΥ</text><text x="150" y="94">ΠΕΡΙ ΦΥ</text></g>`), "An ink prediction appears in yellow over the page"),
    voirZones: () => cadre(hachure + grande(`<g transform="translate(70 -2)">${tache}/>${clign()}</g>`), "The marked areas are shown or hidden"),
    voirScore: () => cadre(orHach + grande(grille + `<g>${clign()}${carreaux((i, x, y) => [3, 7, 8, 12].includes(i) ? `<rect x="${x}" y="${y}" width="36" height="33.3" fill="url(#ao)"/><text x="${x + 18}" y="${y + 21}" class="at" style="fill:#fff;font-weight:700">${[0, 0, 0, 52, 0, 0, 0, 38, 47, 0, 0, 0, 55][i]}</text>` : "")}</g>`), "Weak tiles are hatched, with their score"),
    voirFibres: () => cadre(hachure + grande(grille + `<g>${clign()}${carreaux((i, x, y) => [1, 5, 6, 13].includes(i) ? `<rect x="${x}" y="${y}" width="36" height="33.3" fill="url(#ah)"/><text x="${x + 18}" y="${y + 21}" class="at" style="fill:#fff;font-weight:700">${[0, 31, 0, 0, 0, 24, 36, 0, 0, 0, 0, 0, 0, 18][i]}</text>` : "")}</g>`), "Windows where the fibre grid is not sharp are hatched, with their score"),
    voirPics: () => cadre(feuille(S1) + feuille(S2) + `<g>${clign()}${points(S1)}${points(S2)}</g><path class="as" d="${trace(S1)}"/>`, "Small dots show the sheets detected in the scan"),
    miroir: () => cadre(grande(`<g><text x="0" y="12" fill="#F0E442" font-family="Georgia,serif" font-size="34" text-anchor="middle">ΚΑΙ ΡΕ</text><animateTransform attributeName="transform" type="matrix" calcMode="discrete" ${temps} values="1 0 0 1 150 60;-1 0 0 1 150 60;1 0 0 1 150 60" keyTimes="0;0.5;1"/></g>`), "The display flips left-right"),
    score: () => cadre(`<rect x="40" y="52" width="220" height="18" rx="4" fill="#26221b" stroke="#4a4336"/><rect x="40" y="52" height="18" rx="4" fill="#E69F00" width="130"><animate attributeName="width" ${temps} values="130;130;183;183;130" keyTimes="0;0.25;0.5;0.9;1"/></rect>
      <text x="150" y="38" class="at" style="font-size:22px;fill:#ede6d8">59${clign("1;1;0;0;1", "0;0.36;0.4;0.94;1")}</text><text x="150" y="38" class="at" style="font-size:22px;fill:#ede6d8">83${clign("0;0;1;1;0", "0;0.36;0.4;0.94;1")}</text>
      <text x="150" y="96" class="at">average of the tiles, after each retouch</text>`, "The score of the page changes after each retouch"),
    pire: () => cadre(orHach + grande(grille + carreaux((i, x, y) => i === 8 ? `<rect x="${x}" y="${y}" width="36" height="33.3" fill="url(#ao)"/><text x="${x + 18}" y="${y + 21}" class="at" style="fill:#fff;font-weight:700">21</text>` : i === 11 ? `<rect x="${x}" y="${y}" width="36" height="33.3" fill="url(#ao)" opacity=".55"/><text x="${x + 18}" y="${y + 21}" class="at" style="fill:#fff">34</text>` : "") +
      `<g><circle r="15" fill="none" stroke="#F0E442" stroke-width="2.5"/><path d="M-21 0h12M9 0h12M0 -21v12M0 9v12" stroke="#F0E442" stroke-width="2"/><animateMotion ${temps} path="M90 30L186 60L186 60L114 93L114 93" keyTimes="0;0.3;0.6;0.8;1" calcMode="linear"/></g>`), "The view jumps to the worst tile, then to the next one"),
    figer: () => cadre(`<rect x="50" y="34" width="86" height="52" rx="5" class="apage"/><text x="93" y="58" class="at" style="fill:#fff;font-size:13px">v001</text><text x="93" y="76" class="at">${clign("0;0;1;1;0", "0;0.3;0.4;0.95;1")}🔒 frozen</text>
      <g>${clign("0;0;1;1;0", "0;0.4;0.55;0.95;1")}<path d="M142 60h22M158 54l6 6-6 6" class="aaxe" style="stroke-dasharray:none"/><rect x="170" y="34" width="86" height="52" rx="5" fill="#26221b" stroke="#E69F00" stroke-width="2"/><text x="213" y="58" class="at" style="fill:#fff;font-size:13px">v002</text><text x="213" y="76" class="at">work goes on here</text></g>`, "The version is frozen and work continues on a new one"),
    exporter: () => cadre(`<rect x="40" y="34" width="96" height="52" rx="5" class="apage"/><text x="88" y="58" class="at" style="fill:#fff;font-size:12px">original</text><text x="88" y="76" class="at">never modified</text>
      <g>${clign("0;0;1;1;0", "0;0.25;0.45;0.95;1")}<path d="M142 60h22M158 54l6 6-6 6" class="aaxe" style="stroke-dasharray:none"/><rect x="170" y="34" width="100" height="52" rx="5" fill="#26221b" stroke="#E69F00" stroke-width="2"/><text x="220" y="58" class="at" style="fill:#fff;font-size:12px">new segment</text><text x="220" y="76" class="at">tifxyz + journal</text></g>`, "The retouched surface is written as a new segment"),
    autoPont: () => { const k = ++n; return cadre(`<clipPath id="cp${k}"><rect width="128" height="${H}"/><rect x="176" width="130" height="${H}"/></clipPath><g clip-path="url(#cp${k})">${feuille(S)}</g><path d="M128 30v60M176 30v60" class="aaxe"/><text x="152" y="24" class="at">gap</text>` +
      balai(null, S, { pinceau: false, de: 20 }) + `<text x="150" y="112" class="at">a narrow gap is crossed, a wide one is not</text>`, "The sheet is picked up again across a narrow gap"); },
    autoMarquees: () => cadre(hachure + orHach + grande(`<g transform="translate(70 -2)">${tache}/></g><g transform="translate(70 -2)">${clign()}<path d="M50 45c14-14 46-8 60 6s8 34-14 38-46 2-54-14 0-22 8-30z" fill="url(#ao)" stroke="#E69F00" stroke-width="2"/></g>`) + `<text x="150" y="${H - 2}" class="at"></text>`, "Only the marked area is changed"),
    autoGreffe: () => { const oui = [1, 2, 6, 7, 12], non = [3, 8, 13];
      return cadre(orHach + grande(grille + `<g>${clign("0;0;1;1;1;0", "0;0.1;0.2;0.5;0.95;1")}${carreaux((i, x, y) => oui.includes(i) || non.includes(i) ? `<rect x="${x}" y="${y}" width="36" height="33.3" fill="url(#ao)"/>` : "")}</g>
        <g>${clign("0;0;1;1;0", "0;0.5;0.6;0.95;1")}${carreaux((i, x, y) => non.includes(i) ? `<rect x="${x}" y="${y}" width="36" height="33.3" fill="#4b4840" stroke="#2f2a22"/><text x="${x + 18}" y="${y + 22}" class="at" style="fill:#fff;font-size:14px">✗</text>` : oui.includes(i) ? `<text x="${x + 18}" y="${y + 22}" class="at" style="fill:#fff;font-size:14px;font-weight:700">✓</text>` : "")}</g>`), "Tiles where the score would drop are refused, the others are kept"); },
  });
  ANIM.sauts = ANIM.suivre; ANIM.bordN = ANIM.autoBord; ANIM.autoSaut = ANIM.suivre; ANIM.autoSeuil = ANIM.marches; ANIM.autoPortee = ANIM.fibres; ANIM.extLargeur = ANIM.etendre; ANIM.extCote = ANIM.etendre;

  // ───────────── texts of the ⓘ cards ─────────────
  const T = {
    vues: ["Two views of the same surface", "<b>Flat page</b>: the segment laid flat, where you retouch. <b>3D shape</b>: the surface as it lies in the scan, to see folds and jumps.", [["Tab", "switch between the two"], ["click in 3D", "back to the flat page at that spot"]]],
    defaire: ["Undo and redo", "Every gesture is written to disk at once. Undo has no limit and still works after closing the tab or restarting the server. An automatic tool counts as one gesture.", [["Ctrl + Z", "undo"], ["Ctrl + Y", "redo"]]],
    regarder: ["Look", "Nothing is modified on the page. The two sections on the right show the scan through the point under the mouse.", [["move the mouse", "the sections follow"], ["right-click", "pin the sections here; right-click again releases them"], ["in a section", "drag the orange line onto the sheet, or click where the sheet really runs"]], "This is the tool to use with the sections: pin a spot, then fix it by dragging the orange line."],
    aimant: ["Magnet", "Under the brush, the surface snaps to the nearest sheet detected in the scan. It never moves further than <i>Magnet: at most</i> and never creates a step.", [["click or drag", "snap under the brush"]], "If it grabs the wrong sheet, lower “Magnet: at most” or first bring the line close by hand in a section."],
    bord: ["Edge magnet ▲", "Like the magnet, but the surface then sits N voxels away from the core of the sheet, towards the top of the section. Use it to sit on the face that carries the ink.", [["drag", "sit above the core"], ["Shift + drag", "sit below the core"]], "N is the slider “Edge: from core”."],
    bord2: ["Edge magnet ▼", "The same on the other side: the surface sits N voxels from the core of the sheet, towards the bottom of the section.", [["drag", "sit below the core"], ["Shift + drag", "sit above the core"]]],
    pousser: ["Brush ± 1 voxel", "Moves the surface by hand, one voxel per pass, with soft edges. For the places where no sheet is detected and the magnet has nothing to grab.", [["drag", "up 1 voxel (towards the top of the section)"], ["Shift + drag", "down 1 voxel"]]],
    feuille: ["Shift one sheet", "When a whole patch lies on the neighbouring sheet: paint it, then send it to the sheet above or below. The borders are blended, no step is left.", [["paint", "choose the region (several strokes add up)"], ["PgUp / PgDn", "sheet above / sheet below"], ["Esc", "forget the region"]]],
    marquer: ["Mark a problem", "Paint what looks wrong. The area is kept with the segment, gets its own score, and the automatic tools and “worst tile” can be limited to it.", [["drag", "mark"], ["G", "switch to the eraser"]]],
    gomme: ["Erase marks", "Removes marked areas. It never touches the surface.", [["drag", "erase the marks under the brush"]]],
    portee: ["Brush size / reach", "The radius of the brush on the page. It is also how far a retouch made in a section spreads on each side of the point you drag.", [["[ and ]", "smaller / larger"]]],
    borne: ["Magnet: at most", "The magnet never moves the surface by more than this many voxels. Small: safe, but it will not reach a sheet that is far. Large: reaches far, but may grab the neighbouring sheet."],
    bordN: ["Edge: from core", "How many voxels from the core of the sheet the surface sits, for the two edge magnets and for “Sit on” in the automatic tools. The ink is on one face of the sheet, not in its core."],
    autoSaut: ["Follow: max jump", "A node only takes a detected sheet if it is closer than this to the height its neighbours predict, per grid step. Lower it if the result jumps to another sheet; raise it on steep folds."],
    autoPont: ["Follow: bridge gaps", "How wide a gap without a sure sheet may be crossed before picking the sheet up again. Beyond it, what lies behind the gap is left as it is."],
    autoSeuil: ["Remove steps: threshold", "A jump between two neighbouring nodes counts as a step above this many voxels."],
    autoPortee: ["Best fibres: search range", "How far above and below the current surface the sharpest depth is searched, in steps of one voxel."],
    extCote: ["Extend: side", "Which side of the page grows, as you see it on screen."],
    extLargeur: ["Extend: width", "How wide a band to try. Each row stops earlier if the sheet is no longer sure (tight fold, tear)."],
    suivre: ["Follow the sheet", "Starts from the <b>pinned point</b> (the anchor) and follows ONE sheet step by step. Each node takes, among the sheets detected under it, the one that continues its neighbours, and refuses to jump. A part lying on the neighbouring sheet is brought back. Where the sheet is not sure, nothing is invented.", [["first", "right-click a spot you trust: it becomes the anchor"], ["then", "press the button, check the preview, Apply"]], "This is the tool that fixes a real sheet jump."],
    aimant_partout: ["Magnet everywhere", "The magnet applied to the whole surface at once: each node snaps to the nearest sheet, never further than “Magnet: at most”, never a step of more than one voxel.", null, "It makes the surface smoother on its sheet, but it cannot fix a jump to another sheet: use Follow the sheet for that."],
    page_dessus: ["Whole page: sheet above", "The whole page (or only the marked areas) moves onto the neighbouring sheet towards the top of the section. The jumps are made consistent between neighbours; places that are not sure are counted and shown."],
    page_dessous: ["Whole page: sheet below", "The whole page (or only the marked areas) moves onto the neighbouring sheet towards the bottom of the section."],
    marches: ["Remove steps", "Finds the jumps between neighbouring nodes, cuts the surface into regions along them, keeps the region of the pinned point (or the largest) as the reference, and brings the other regions back onto its sheet when the seam is clear."],
    fibres: ["Best fibres", "For each small tile, looks for the depth around the current surface where vertical AND horizontal fibres are sharpest together, then applies that depth smoothed, without steps."],
    etendre: ["Extend the surface <em class=\"beta\">beta</em>", "<b>Beta:</b> check the new band in the sections before you rely on it. Grows the surface by a band beyond one edge. Each row is prolonged with its direction and curvature, the scan is read for the new band only, and the sheet is followed from the existing edge. Where it is no longer sure, the band stops there and says so."],
    autoBord: ["Sit on", "Where Follow the sheet and Magnet everywhere put the surface: on the core of the sheet, or N voxels from it, to sit on the face that carries the ink."],
    autoMarquees: ["Only in the marked areas", "Magnet everywhere, Best fibres and Whole page then only touch the areas you marked with <kbd>M</kbd>. The rest of the surface does not move."],
    autoGreffe: ["Keep only the winning parts", "The proposal is compared with the current surface tile by tile, with the fibre score. Where the score would drop, or where a patch would change sheet without a clear gain, the surface is left as it is. Slower (the page is measured twice). Not used by Remove steps."],
    couche: ["Depth of the page", "Shows the page a few voxels above or below the retouched surface, without moving it. Useful to see whether the ink or the fibres are sharper just next to it.", [["↑ ↓", "one voxel up / down"], ["Shift + wheel", "the same"]]],
    encre: ["Ink layer", "Shows an ink prediction over the page (in yellow). It was computed on the ORIGINAL surface: it does not follow your retouches.", [["E", "next layer / none"]]],
    voirZones: ["Problem areas", "The areas you marked: blue outline and hatching ╲."],
    voirScore: ["Score map", "The score of each 0.3 mm tile, drawn over the page: nothing = good, dots = fair, hatching = weak, cross-hatching = bad. Numbers appear when you zoom in."],
    voirFibres: ["Fibre score map", "Per 0.3 mm window, 0–100: are vertical AND horizontal fibres visible together? Blank = 60 or more, dots = 40–60, hatching = 20–40, cross-hatching = below 20."],
    voirPics: ["Detected sheets", "The small blue dots in the sections: where a sheet was detected in the scan. This is what the magnets aim at."],
    miroir: ["Mirror left-right", "Flips the display. Use it when the text reads mirrored on this segment. It does not change the surface."],
    score: ["Score of the page", "0–100 per tile of 0.3 mm, then averaged. It combines the distance to the detected sheet, how sharp the sheet is, steps between neighbours, stretch and shear of the grid, and how close the neighbouring sheet is.", null, "It measures the geometry of the surface, not the ink: a better score does not promise more readable ink."],
    sauts: ["Find sheet jumps", "Shows where the surface has slipped onto another sheet. The sheet under the <b>pinned point</b> is the reference: it is followed step by step, without jumping, and every part of the surface is compared with it. Orange ╱ = on a sheet above, blue ╲ = on a sheet below, with the number of sheets; white dots = not sure. Nothing is written.", [["first", "right-click a spot you trust: it is the reference sheet"], ["J", "show / clear the map"], ["a zone in the list", "go to it"]], "“Not sure” is not “wrong”: the reference sheet could not be followed up to there (crushed sheets, a tear, or more than 32 voxels away). Try another reference point closer to it."],
    pire: ["Go to the worst tile", "Jumps to the lowest-scored tile and pins the sections there. Press again for the next one.", [["N", "next worst tile"]]],
    figer: ["Freeze this version", "The working version stops changing and work continues on a new one. A way to keep a state you are happy with before trying something risky."],
    exporter: ["Export", "Writes the retouched surface as a NEW tifxyz segment, with the offset field and the journal of gestures. The original segment is never modified."],
  };
  const TOUCHES = Object.fromEntries(OUTILS.map(([o, k]) => [o, k]));

  // ───────────── the ⓘ card ─────────────
  const bulle = document.createElement("div"); bulle.id = "bulle"; bulle.setAttribute("role", "tooltip"); bulle.hidden = true; document.body.appendChild(bulle);
  const calme = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let ouvertePar = null, epinglee = false, fermeture = 0;
  function montrer(b) {
    const k = b.dataset.info, t = T[k]; if (!t) return; clearTimeout(fermeture); ouvertePar = b;
    let dessin = ANIM[k] ? ANIM[k]() : ""; if (calme) dessin = dessin.replace(/<animate[^>]*\/>/g, "");
    bulle.innerHTML = `${dessin}<div class="bt">${IC[k] ? ic(k) : ""}<b>${t[0]}</b>${TOUCHES[k] ? `<kbd>${TOUCHES[k]}</kbd>` : ""}</div><p>${t[1]}</p>` +
      (t[2] ? `<table>${t[2].map(([g, e]) => `<tr><td>${g}</td><td>${e}</td></tr>`).join("")}</table>` : "") + (t[3] ? `<p class="bn">${t[3]}</p>` : "");
    bulle.hidden = false; const r = b.getBoundingClientRect(), p = $("panneau").getBoundingClientRect(), h = bulle.offsetHeight;
    bulle.style.left = Math.round(p.right + 10) + "px"; bulle.style.top = Math.round(Math.max(8, Math.min(innerHeight - h - 8, r.top - 24))) + "px";
  }
  function cacher(tout) { if (epinglee && !tout) return; epinglee = false; ouvertePar = null; bulle.hidden = true; bulle.innerHTML = ""; }
  const plusTard = () => { clearTimeout(fermeture); fermeture = setTimeout(() => cacher(false), 180); };
  document.addEventListener("mouseover", ev => { const b = ev.target.closest && ev.target.closest(".i"); if (b && !epinglee) montrer(b); else if (ev.target.closest && ev.target.closest("#bulle")) clearTimeout(fermeture); });
  document.addEventListener("mouseout", ev => { if (ev.target.closest && (ev.target.closest(".i") || ev.target.closest("#bulle"))) plusTard(); });
  document.addEventListener("focusin", ev => { if (ev.target.classList && ev.target.classList.contains("i") && !epinglee) montrer(ev.target); });
  document.addEventListener("focusout", ev => { if (ev.target.classList && ev.target.classList.contains("i")) plusTard(); });
  document.addEventListener("click", ev => {
    const b = ev.target.closest && ev.target.closest(".i");
    if (b) { ev.preventDefault(); ev.stopPropagation(); if (epinglee && ouvertePar === b) cacher(true); else { epinglee = false; montrer(b); epinglee = true; } }
    else if (epinglee && !(ev.target.closest && ev.target.closest("#bulle"))) cacher(true);
  }, true);
  window.addEventListener("keydown", ev => { if (ev.key === "Escape" && !bulle.hidden) cacher(true); });

  // ───────────── behaviour of the panel ─────────────
  // the options shown under the tools are those of the tool in hand
  function selonOutil() {
    const a = corps.querySelector(".outils button.actif"), o = a ? a.dataset.outil : "regarder";
    corps.querySelectorAll("[data-pour]").forEach(e => { e.hidden = !e.dataset.pour.split(" ").includes(o); }); $("outilAstuce").innerHTML = ASTUCE[o] || "";
  }
  new MutationObserver(selonOutil).observe(corps.querySelector(".outils"), { subtree: true, attributes: true, attributeFilter: ["class"] }); selonOutil();
  // a second slider for a setting that lives elsewhere (same value, both move together)
  const copies = [];
  corps.querySelectorAll("[data-copie]").forEach(l => {
    const src = $(l.dataset.copie), c = document.createElement("input"), o = document.createElement("output"); c.type = "range"; for (const k of ["min", "max", "step"]) c[k] = src[k];
    l.append(c, o); const lire = () => { c.value = src.value; o.textContent = $(src.id + "Val").textContent; };
    c.addEventListener("input", () => { src.value = c.value; src.dispatchEvent(new Event("input", { bubbles: true })); lire(); }); src.addEventListener("input", lire); copies.push(lire);
  });
  const relire = () => copies.forEach(f => f());
  // drawers of the automatic tools: one open at a time
  corps.querySelectorAll(".rouage:not(.vide)").forEach(b => b.addEventListener("click", () => {
    const t = b.parentElement.querySelector(".tiroir"), ouvrir = t.hidden;
    corps.querySelectorAll(".tiroir").forEach(x => { x.hidden = true; }); corps.querySelectorAll(".rouage:not(.vide)").forEach(x => { x.setAttribute("aria-expanded", "false"); x.parentElement.classList.remove("ouvert"); });
    t.hidden = !ouvrir; b.setAttribute("aria-expanded", String(ouvrir)); b.parentElement.classList.toggle("ouvert", ouvrir); relire();
  }));
  const bordN = () => { $("autoBordN").hidden = $("autoBord").value === "0"; relire(); }; $("autoBord").addEventListener("change", bordN);
  // which groups are open is remembered
  const CLE = "surface_enhancer_panneau"; let memo = {}; try { memo = JSON.parse(localStorage.getItem(CLE) || "{}"); } catch (e) { }
  corps.querySelectorAll("details.grp").forEach(d => { if (d.dataset.grp in memo) d.open = memo[d.dataset.grp];
    d.addEventListener("toggle", () => { memo[d.dataset.grp] = d.open; try { localStorage.setItem(CLE, JSON.stringify(memo)); } catch (e) { } }); });
  // undo / redo stay in sight, under the name of the segment
  const tete = document.querySelector("#panneau .tete"); if (tete) tete.appendChild(corps.querySelector(".rapide"));

  // ───────────── the Segment menu: import, open, save, export, close ─────────────
  // Import / open / close lead to the list of segments, so they only exist where there is one (the page has a “back” link).
  IC.menu = "M4 6h16M4 12h16M4 18h16"; IC.importer = "M12 3v12M8 11l4 4 4-4M4 14v6h16v-6"; IC.ouvrir = "M3 7v12h18V9h-9l-2-2z"; IC.fermer = "M6 6l12 12M18 6L6 18";
  IC.sauver = "M5 3h11l3 3v15H5zM8 3v6h7V3M8 21v-7h8v7";
  const accueil = !!$("retour"), sauve = $("titre");
  let onglets = null; try { if (window.parent !== window && window.parent.SR_TABS) onglets = window.parent.SR_TABS; } catch (e) { }      // this editor is one tab among several (tabs.html)
  const moi = new URLSearchParams(location.search).get("s") || "";
  if (onglets && $("retour")) $("retour").hidden = true;
  if (onglets) document.body.classList.add("dansOnglet");      // the tab strip of tabs.html lies over the top of the page and of the sections: leave it room
  if (sauve) {
    const m = document.createElement("div"); m.className = "menuSeg";
    m.innerHTML = `<button type="button" id="menuBtn" aria-haspopup="true" aria-expanded="false">${ic("menu")} Segment <span class="chevron" aria-hidden="true"></span></button>
      <div id="menuListe" role="menu" hidden>
        ${accueil ? `${onglets ? `<button type="button" role="menuitem" data-onglet="open">${ic("importer")}<span><b>Import a segment…</b><small>a folder, a zip or a VC3D package, in a new tab</small></span></button>`
          : `<a role="menuitem" href="./#tAjout">${ic("importer")}<span><b>Import a segment…</b><small>a folder, a zip or a VC3D package</small></span></a>`}
        ${onglets ? `<button type="button" role="menuitem" data-onglet="open">${ic("ouvrir")}<span><b>Open another segment</b><small>in a new tab; this one stays open</small></span></button>`
          : `<a role="menuitem" href="./">${ic("ouvrir")}<span><b>Open another segment</b><small>the list of prepared segments</small></span></a>`}<hr>` : ""}
        <button type="button" role="menuitem" data-fait="figer">${ic("sauver")}<span><b>Save as a version</b><small>every gesture is already saved; this freezes a version you can come back to</small></span></button>
        <button type="button" role="menuitem" data-fait="exporter">${ic("exporter")}<span><b>Export…</b><small>a new tifxyz segment; the original is never modified</small></span></button>
        ${accueil ? `<hr>${onglets ? `<button type="button" role="menuitem" data-onglet="close">${ic("fermer")}<span><b>Close this segment</b><small>closes its tab; nothing to save: it is already on disk</small></span></button>`
          : `<a role="menuitem" href="./">${ic("fermer")}<span><b>Close this segment</b><small>nothing to save: it is already on disk</small></span></a>`}` : ""}
      </div>`;
    const rang = document.createElement("div"); rang.className = "titreLigne"; sauve.before(rang); rang.append(sauve, m);      // the name of the segment, and its menu on the right
    const btn = $("menuBtn"), liste = $("menuListe"), fermer = () => { liste.hidden = true; btn.setAttribute("aria-expanded", "false"); };
    btn.addEventListener("click", ev => { ev.stopPropagation(); liste.hidden = !liste.hidden; btn.setAttribute("aria-expanded", String(!liste.hidden)); });
    liste.addEventListener("click", ev => { const b = ev.target.closest("[data-fait]"), o = ev.target.closest("[data-onglet]"); fermer(); if (b) $(b.dataset.fait).click(); else if (o && onglets) { if (o.dataset.onglet === "open") onglets.open(); else onglets.close(moi); } });
    document.addEventListener("click", ev => { if (!liste.hidden && !ev.target.closest(".menuSeg")) fermer(); });
    window.addEventListener("keydown", ev => { if (ev.key === "Escape" && !liste.hidden) fermer(); });
    // what the tool answers (version frozen, export written…) is shown under the menu even when “History and export” is folded
    const avis = document.createElement("div"); avis.id = "menuAvis"; avis.setAttribute("role", "status"); avis.hidden = true; rang.after(avis); let t = 0;      // under the title row, never inside it
    new MutationObserver(() => { const msg = $("message"), g = msg.closest("details"); if (!msg.textContent || (g && g.open)) { avis.hidden = true; return; }
      avis.textContent = msg.textContent; avis.className = msg.className.includes("erreur") ? "erreur" : ""; avis.hidden = false; clearTimeout(t); t = setTimeout(() => { avis.hidden = true; }, 12000); })
      .observe($("message"), { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["class"] });
  }


  // ───────────── “Load a segment”, where one server serves one segment (the workshop): the other prepared segments, each in its own browser tab ─────────────
  if (!accueil && sauve) (async () => {
    let segs; try { const r = await fetch("/api/segments", { cache: "no-store" }); if (!r.ok) return; segs = await r.json(); } catch (e) { return; }
    if (!Array.isArray(segs)) return;
    const boite = document.createElement("div"); boite.className = "menuSeg";
    boite.innerHTML = `<button type="button" id="chargerBtn" aria-haspopup="true" aria-expanded="false" title="Open another prepared segment (in a new browser tab)">＋ Load a segment</button><div id="chargerListe" role="menu" hidden></div>`;
    const marque = document.querySelector("#panneau .tete .caps"), haut = document.createElement("div"); haut.className = "hautLigne"; marque.before(haut); haut.append(marque, boite);      // the very first line of the panel: the name of the tool, and Load a segment
    const btn = $("chargerBtn"), liste = $("chargerListe"), fermerC = () => { liste.hidden = true; btn.setAttribute("aria-expanded", "false"); };
    const dessinerC = () => { liste.innerHTML = `<div class="sousTitre">Prepared segments</div>` + segs.map(s =>
      `<button type="button" role="menuitem" data-seg="${s.nom}" ${s.ici ? "disabled" : ""}>${ic(s.port ? "ouvrir" : "importer")}<span><b>${s.nom}${s.ici ? " — this one" : ""}</b><small>${[s.rouleau, s.mm ? s.mm[0] + " × " + s.mm[1] + " mm" : "", s.ici ? "" : s.port ? "already running: opens at once" : "not running: starts its server first"].filter(Boolean).join(" · ")}</small></span></button>`).join(""); };
    btn.addEventListener("click", async ev => { ev.stopPropagation(); if (!liste.hidden) { fermerC(); return; }
      try { segs = await (await fetch("/api/segments", { cache: "no-store" })).json(); } catch (e) { }
      dessinerC(); liste.hidden = false; btn.setAttribute("aria-expanded", "true"); });
    liste.addEventListener("click", async ev => {
      const b = ev.target.closest("[data-seg]"); if (!b || b.disabled) return; const nom = b.dataset.seg, fen = window.open("about:blank", "_blank");      // opened at once, inside the click, so the browser allows it
      b.querySelector("small").textContent = "starting its server… (up to a minute for a large page)"; liste.querySelectorAll("button").forEach(x => { x.disabled = true; });
      try {
        const r = await fetch("/api/lancer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nom }) }), j = await r.json();
        if (!r.ok || j.erreur) throw new Error(j.erreur || r.statusText);
        const url = `http://127.0.0.1:${j.port}/`; if (fen) fen.location = url; else location.href = url; fermerC();
      } catch (e) { if (fen) fen.close(); b.querySelector("small").textContent = "✗ " + e.message; liste.querySelectorAll("button").forEach(x => { x.disabled = x.dataset.seg === (segs.find(s => s.ici) || {}).nom; }); }
    });
    document.addEventListener("click", ev => { if (!liste.hidden && !ev.target.closest("#chargerListe") && ev.target !== btn) fermerC(); });
    window.addEventListener("keydown", ev => { if (ev.key === "Escape") fermerC(); });
  })();

  // once the segment is loaded: hide the automatic tools this server does not have, show the current values
  const pret = setInterval(() => {
    if (!window.PRET) return; clearInterval(pret); relire(); bordN();
    try { if (E && E.auto) corps.querySelectorAll(".auto").forEach(a => { a.hidden = !E.auto.includes(a.dataset.nom); }); } catch (e) { }
  }, 200);
})();
