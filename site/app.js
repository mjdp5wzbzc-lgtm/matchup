/* MatchUp Perso — site statique, toutes les données viennent de data/*.json */
(() => {
"use strict";
const $app = document.getElementById("app");
const STATS = { pts:"Points", reb:"Rebonds", ast:"Passes", tpm:"3 points", pr:"Pts+Reb", pa:"Pts+Pas", ra:"Reb+Pas", pra:"Pts+Reb+Pas", stl:"Interceptions", blk:"Contres" };
const PARTS = { pts:["pts"], reb:["reb"], ast:["ast"], tpm:["tpm"], pr:["pts","reb"], pa:["pts","ast"], ra:["reb","ast"], pra:["pts","reb","ast"], stl:["stl"], blk:["blk"] };
const TAGS = { DEF:"Défense", PACE:"Rythme", FORM:"Forme", MIN:"Minutes", ABS:"Absences", H2H:"H2H", VEN:"Dom/Ext", STY:"Style", B2B:"Fatigue", B2BO:"Adv. fatigué" };
const BUCKET = { G:"Meneurs / arrières", F:"Ailiers", C:"Pivots" };
const BUCKET1 = { G:"Arrière", F:"Ailier", C:"Pivot" };
const IDX = { avg:0, l5:1, l10:2, line:3, book:4, score:5, tags:6, hit:7, n:8, sty:9 };
const styLv = (p, st) => (p.s[st] && p.s[st][9]) || 0;
const STYLAB = ["", "🎯 Style favorable", "🎯 Style très favorable"];

const store = {
  get(k, d){ try { const v = localStorage.getItem("mu_" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v){ try { localStorage.setItem("mu_" + k, JSON.stringify(v)); } catch {} }
};
const S = { stat: store.get("stat", "pts"), game: "all", sort: store.get("sort", "ctx"), q: "", tab: store.get("tab", "fac"), dvpPos: "C", dvpStat: "pts", styOnly: false };
let T = null, DVP = null;
const cache = {};

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const f1 = x => x == null ? "–" : (Math.round(x * 10) / 10).toFixed(1);
const pct = (a, b) => b ? Math.round(100 * a / b) : null;
const team = t => (T && T.teams[t] && T.teams[t].short) || t;
const timeOf = iso => { try { return new Date(iso).toLocaleTimeString("fr-FR", { hour:"2-digit", minute:"2-digit" }); } catch { return ""; } };
const SING = new Set(["Heat", "Jazz", "Magic", "Thunder"]);
const one = t => SING.has(team(t));
const les = t => (one(t) ? "le " : "les ") + esc(team(t));
const Les = t => (one(t) ? "Le " : "Les ") + esc(team(t));
const aux = t => (one(t) ? "au " : "aux ") + esc(team(t));
const des = t => (one(t) ? "du " : "des ") + esc(team(t));
const concede = t => `${Les(t)} ${one(t) ? "concède" : "concèdent"}`;
const isOut = st => st && /out|doubtful|susp/i.test(st);
const stBadge = st => !st ? "" : `<span class="st ${isOut(st) ? "out" : "q"}">${esc(stFr(st))}</span>`;
function stFr(st){ const m = { "out":"OUT", "doubtful":"Douteux", "questionable":"Incertain", "day-to-day":"Au jour le jour", "probable":"Probable", "suspension":"Suspendu" }; return m[(st||"").toLowerCase()] || st; }
function lineKey(pid, s){ return `line_${pid}_${s}`; }
function userLine(pid, s, def){ const v = store.get(lineKey(pid, s), null); return v == null ? def : v; }
function hitCls(p){ return p == null ? "" : p >= 60 ? "good" : p <= 40 ? "bad" : "meh"; }

async function getJSON(url){
  const r = await fetch(url + (url.includes("?") ? "&" : "?") + "v=" + (T ? encodeURIComponent(T.generated) : Date.now()));
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

/* ------------------------------------------------------------------ routeur */
async function route(){
  const h = location.hash || "#/";
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.toggle("on", (h.startsWith("#/dvp") ? "dvp" : h.startsWith("#/tennis") ? "tennis" : "list") === a.dataset.nav));
  if (h.startsWith("#/tennis")) {
    try { return await renderTennis(h); }
    catch (e) { $app.innerHTML = `<div class="empty">Données tennis introuvables pour l'instant.<br><small>Elles arrivent au prochain passage du robot.</small></div>`; console.error(e); return; }
  }
  try {
    if (!T) T = await getJSON("data/today.json");
    const meta = document.getElementById("meta");
    meta.textContent = `Mis à jour le ${new Date(T.generated).toLocaleString("fr-FR")} · ${T.n_games_db} matchs en base · saison ${T.season}`;
    if (h.startsWith("#/p/")) return renderPlayer(h.slice(4));
    if (h.startsWith("#/dvp")) return renderDvp();
    renderList();
  } catch (e) {
    $app.innerHTML = `<div class="empty">Données introuvables pour l'instant.<br><small>Lance la mise à jour (onglet Actions de GitHub) puis recharge la page.</small></div>`;
    console.error(e);
  }
}
window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); });

/* ------------------------------------------------------------------ liste du soir */
function statChips(){
  return `<div class="chips" id="statchips">${Object.entries(STATS).map(([k, v]) => `<button class="chip ${k === S.stat ? "on" : ""}" data-stat="${k}">${v}</button>`).join("")}</div>`;
}

function renderList(){
  const nOut = Object.values(T.injuries).flat().filter(i => isOut(i.status)).length;
  const d = new Date(T.date + "T12:00:00");
  const dl = d.toLocaleDateString("fr-FR", { weekday:"long", day:"numeric", month:"long" });
  $app.innerHTML = `
  <div class="hero">
    <div><h1>Matchups du soir</h1><div class="sub">Nuit du ${esc(dl)} · heures affichées chez toi${T.has_book_lines ? "" : " · lignes = moyenne arrondie (pas de clé cotes)"}</div></div>
    <div class="kpis">
      <div class="kpi"><div class="big">${T.games.length}</div><small>Matchs</small></div>
      <div class="kpi"><div class="big">${T.players.length}</div><small>Joueurs</small></div>
      <div class="kpi out"><div class="big">${nOut}</div><small>OUT</small></div>
    </div>
  </div>
  ${statChips()}
  <div class="chips" id="gamechips">
    <button class="chip ${S.game === "all" ? "on" : ""}" data-game="all">Tous les matchs</button>
    ${T.games.map(g => `<button class="chip game ${S.game === g.id ? "on" : ""}" data-game="${g.id}">${esc(g.away)} @ ${esc(g.home)}<small>${g.state === "pre" ? timeOf(g.start) : esc(g.detail || "")}${g.pace ? " · rythme " + f1(g.pace) : ""}</small></button>`).join("")}
  </div>
  <div class="tools">
    <input id="q" type="search" placeholder="Chercher un joueur ou une équipe…" value="${esc(S.q)}">
    <select id="sort">
      <option value="ctx">Trier : contexte</option><option value="avg">Moyenne</option>
      <option value="form">Forme (5 derniers)</option><option value="hit">Réussite sur 10</option><option value="edge">Moyenne − ligne</option><option value="sty">Style favorable</option>
    </select>
    <button class="chip ${S.styOnly ? "on" : ""}" id="styonly">🎯 Style favorable</button>
  </div>
  <div id="stystrip"></div>
  <div class="list" id="list"></div>
  <section class="sec"><h2>Absences et relais</h2><div class="abs" id="abs"></div></section>`;
  document.getElementById("sort").value = S.sort;
  bindList();
  drawRows();
  drawAbs();
}

function rowsData(){
  const q = S.q.trim().toLowerCase();
  let ps = T.players.filter(p => p.s[S.stat] && (S.game === "all" || p.g === S.game) && (!S.styOnly || styLv(p, S.stat) > 0));
  if (q) ps = ps.filter(p => (p.n + " " + p.t + " " + p.o + " " + team(p.t) + " " + team(p.o)).toLowerCase().includes(q));
  const v = p => {
    const s = p.s[S.stat], line = userLine(p.id, S.stat, s[IDX.line]);
    switch (S.sort) {
      case "avg": return s[IDX.avg];
      case "form": return (s[IDX.l5] - s[IDX.avg]) / (s[IDX.avg] || 1);
      case "hit": return s[IDX.n] ? s[IDX.hit] / s[IDX.n] : 0;
      case "edge": return s[IDX.avg] - line;
      case "sty": return styLv(p, S.stat) * 1000 + s[IDX.score] * 10 + s[IDX.avg] / 100;
      default: return s[IDX.score] * 100 + s[IDX.avg];
    }
  };
  ps.sort((a, b) => (isOut(a.st) - isOut(b.st)) || (v(b) - v(a)));
  return ps;
}

function drawStrip(){
  const el = document.getElementById("stystrip");
  const ps = T.players.filter(p => styLv(p, S.stat) > 0 && !isOut(p.st) && (S.game === "all" || p.g === S.game))
    .sort((a, b) => styLv(b, S.stat) - styLv(a, S.stat) || b.s[S.stat][IDX.score] - a.s[S.stat][IDX.score]);
  if (!ps.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<div class="stystrip"><div class="sth">🎯 Matchups de style du soir · ${STATS[S.stat]} <small>${ps.length}</small></div>
    <div class="chips">${ps.slice(0, 15).map(p => { const s = p.s[S.stat], lv = styLv(p, S.stat); return `<a class="stycard lv${lv}" href="#/p/${p.id}"><small>${esc(p.t)} ${p.h ? "vs" : "@"} ${esc(p.o)}</small><b>${esc(p.n)}</b><span class="tag style">${esc(p.sty)}</span><span class="lvl">${lv === 2 ? "Très favorable" : "Favorable"}</span><span class="mini">Moy. ${f1(s[IDX.avg])} · ligne ${userLine(p.id, S.stat, s[IDX.line])}</span></a>`; }).join("")}</div></div>`;
}

function drawRows(){
  drawStrip();
  const ps = rowsData();
  const el = document.getElementById("list");
  if (!ps.length) { el.innerHTML = `<div class="empty">Aucun joueur.</div>`; return; }
  el.innerHTML = ps.map(p => {
    const s = p.s[S.stat];
    const line = userLine(p.id, S.stat, s[IDX.line]);
    const custom = line !== s[IDX.line];
    const sc = s[IDX.score];
    const tags = (s[IDX.tags] || []).map(t => { const k = t.slice(0, -1), pos = t.endsWith("+"); return `<span class="f ${pos ? "p" : "m"}">${pos ? "▲" : "▼"} ${TAGS[k] || k}</span>`; }).join("");
    const hitTxt = custom ? "" : `<div class="hit">ligne passée <b>${s[IDX.hit]}/${s[IDX.n]}</b></div>`;
    const lv = styLv(p, S.stat);
    return `<a class="row ${isOut(p.st) ? "isout" : ""} ${lv ? "styhot lv" + lv : ""}" href="#/p/${p.id}">
      <div class="who">
        <div class="l1">${esc(p.t)} ${p.h ? "vs" : "@"} ${esc(team(p.o))} ${stBadge(p.st)}</div>
        <div class="name">${esc(p.n)}</div>
        <div class="l3"><span class="tag style">${esc(p.sty)}</span>${lv ? `<span class="sbadge lv${lv}">${STYLAB[lv]}</span>` : ""}<span>${f1(p.min)} min</span>${hitTxt}</div>
        ${tags ? `<div class="ctx">${tags}</div>` : ""}
      </div>
      <div class="nums">
        <div class="c"><small>Moy.</small><div class="big">${f1(s[IDX.avg])}</div></div>
        <div class="c hide-s"><small>5 der.</small><div class="big">${f1(s[IDX.l5])}</div></div>
        <div class="c"><small>Ligne${s[IDX.book] && !custom ? ' <span class="book">●</span>' : ""}</small><div class="big line">${line ?? "–"}</div></div>
        <div class="score ${sc > 0 ? "p" : sc < 0 ? "m" : "z"}" title="Somme des facteurs favorables (+) et défavorables (−)">${sc > 0 ? "+" : ""}${sc}</div>
      </div></a>`;
  }).join("");
}

function drawAbs(){
  const el = document.getElementById("abs");
  const games = T.games.filter(g => S.game === "all" || g.id === S.game);
  const html = [];
  for (const g of games) for (const t of [g.away, g.home]) {
    const inj = (T.injuries[t] || []);
    if (!inj.length) continue;
    const rel = Object.fromEntries((T.relief[t] || []).map(r => [r.name, r.relief]));
    html.push(`<div class="card"><div class="t"><span>${esc(team(t))}</span><span class="tag">${t === g.home ? "dom." : "ext."} · ${esc(team(t === g.home ? g.away : g.home))}</span></div>
      ${inj.map(i => {
        const r = rel[i.name] || [];
        return `<div class="p">${stBadge(i.status)} <b>${esc(i.name)}</b>${i.comment ? `<div class="rel">${esc(i.comment)}</div>` : ""}
        ${r.length ? `<div class="rel">Sans lui : ${r.map(x => `<a href="#/p/${x.id}">${esc(x.name)} <b>+${f1(x.d_pts)} pts</b></a>`).join(" · ")}</div>` : ""}</div>`;
      }).join("")}</div>`);
  }
  el.innerHTML = html.join("") || `<div class="empty">Aucune absence signalée.</div>`;
}

function bindList(){
  document.getElementById("statchips").onclick = e => { const b = e.target.closest("[data-stat]"); if (!b) return; S.stat = b.dataset.stat; store.set("stat", S.stat); document.querySelectorAll("#statchips .chip").forEach(c => c.classList.toggle("on", c === b)); drawRows(); };
  document.getElementById("gamechips").onclick = e => { const b = e.target.closest("[data-game]"); if (!b) return; S.game = b.dataset.game; document.querySelectorAll("#gamechips .chip").forEach(c => c.classList.toggle("on", c === b)); drawRows(); drawAbs(); };
  document.getElementById("q").oninput = e => { S.q = e.target.value; drawRows(); };
  document.getElementById("styonly").onclick = e => { S.styOnly = !S.styOnly; e.currentTarget.classList.toggle("on", S.styOnly); drawRows(); };
  document.getElementById("sort").onchange = e => { S.sort = e.target.value; store.set("sort", S.sort); drawRows(); };
}

/* ------------------------------------------------------------------ fiche joueur */
const TABS = [["fac","⭐ Facteurs clés"],["form","📈 Forme"],["h2h","🆚 H2H"],["abs","🚑 Absences"],["sty","🎯 Style de jeu"],["def","🛡️ Défense"],["pace","⚡ Rythme"],["shot","📐 Type de shoot"],["car","📊 Carrière"]];

async function renderPlayer(id){
  const p = T.players.find(x => x.id === id);
  if (!p) { $app.innerHTML = `<div class="empty">Ce joueur ne joue pas ce soir. <a href="#/" style="color:var(--acc2)">Retour à la liste</a></div>`; return; }
  $app.innerHTML = `<div class="loading">Chargement de la fiche…</div>`;
  let D = cache[id];
  if (!D) { D = cache[id] = await getJSON(`data/p/${id}.json`); D.rows = D.logs.map(a => Object.fromEntries(D.cols.map((c, i) => [c, a[i]]))); D.rows.reverse(); }
  if (!p.s[S.stat]) S.stat = "pts";
  const draw = () => {
    const s = p.s[S.stat];
    const line = userLine(id, S.stat, s[IDX.line]);
    $app.innerHTML = `
    <a class="back" href="#/">← Liste du soir</a>
    <div class="ph">
      <div class="l1">${esc(team(D.team))} ${D.home ? "vs" : "@"} ${esc(team(D.opp))} · ${BUCKET1[D.bucket]} (${esc(D.pos)}) ${stBadge(D.status)}</div>
      <h1>${esc(D.name)}</h1>
      <span class="tag style">${esc(D.style)}</span>${styLv(p, S.stat) ? ` <span class="sbadge lv${styLv(p, S.stat)}">${STYLAB[styLv(p, S.stat)]}</span>` : ""}
      ${D.injury && D.injury.comment ? `<div class="note">${esc(D.injury.comment)}</div>` : ""}
      <div class="stats">
        <div><small>Moyenne</small><div class="big">${f1(s[IDX.avg])}</div></div>
        <div><small>5 derniers</small><div class="big">${f1(s[IDX.l5])}</div></div>
        <div><small>Minutes</small><div class="big">${f1(p.min)}</div></div>
        <div><small>Ligne ${s[IDX.book] ? '<span class="book">● bookmaker</span>' : "(modifiable)"}</small>
          <div class="linebox"><button data-l="-0.5">−</button><input id="line" inputmode="decimal" value="${line}"><button data-l="0.5">+</button></div></div>
      </div>
    </div>
    ${statChips()}
    <div class="tabs">${TABS.map(([k, v]) => `<button class="tab ${k === S.tab ? "on" : ""}" data-tab="${k}">${v}</button>`).join("")}</div>
    <div id="tab"></div>`;
    document.getElementById("statchips").onclick = e => { const b = e.target.closest("[data-stat]"); if (!b || !p.s[b.dataset.stat]) return; S.stat = b.dataset.stat; store.set("stat", S.stat); draw(); };
    document.querySelector(".tabs").onclick = e => { const b = e.target.closest("[data-tab]"); if (!b) return; S.tab = b.dataset.tab; store.set("tab", S.tab); document.querySelectorAll(".tab").forEach(t => t.classList.toggle("on", t === b)); drawTab(); };
    const inp = document.getElementById("line");
    const setLine = v => { v = Math.max(0, Math.round(v * 2) / 2); inp.value = v; store.set(lineKey(id, S.stat), v === s[IDX.line] ? null : v); drawTab(); };
    document.querySelectorAll("[data-l]").forEach(b => b.onclick = () => setLine(parseFloat(inp.value || 0) + parseFloat(b.dataset.l)));
    inp.onchange = () => setLine(parseFloat(String(inp.value).replace(",", ".")) || 0);
    const tabEl = document.querySelector(".tab.on"); if (tabEl) tabEl.scrollIntoView({ block:"nearest", inline:"center" });
    drawTab();
  };
  const drawTab = () => {
    const line = parseFloat(document.getElementById("line").value);
    const fn = { fac:tFac, form:tForm, h2h:tH2H, abs:tAbs, sty:tSty, def:tDef, pace:tPace, shot:tShot, car:tCar }[S.tab] || tFac;
    document.getElementById("tab").innerHTML = fn(D, p, S.stat, line);
    const sel = document.getElementById("bucketSel");
    if (sel) sel.onclick = e => { const b = e.target.closest("[data-b]"); if (!b) return; D._b = b.dataset.b; drawTab(); };
  };
  draw();
}

const val = (r, s) => PARTS[s].reduce((a, k) => a + (r[k] || 0), 0);
function lineFor(D, r, s, line){ const a = D.lines && D.lines[r.date] && D.lines[r.date][s]; return a != null ? [a, true] : [line, false]; }
function hits(D, rows, s, line){ let o = 0; for (const r of rows) { const [l] = lineFor(D, r, s, line); if (val(r, s) > l) o++; } return [o, rows.length]; }
function box(title, o, n, sub){ const p = pct(o, n); return `<div class="box"><small>${title}</small><div class="big ${hitCls(p)}">${p == null ? "–" : p + "%"}</div><div class="s">${n ? `${o} / ${n}${sub ? " · " + sub : ""}` : "aucun match"}</div></div>`; }
const seasonOf = r => r.season;

function tFac(D, p, s, line){
  const F = (D.factors[s] || []);
  const last10 = D.rows.slice(0, 10), [o, n] = hits(D, last10, s, line);
  const sc = F.reduce((a, f) => a + f[0], 0);
  const plus = F.filter(f => f[0] > 0).length, minus = F.filter(f => f[0] < 0).length;
  return `<div class="clair"><b>💡 EN CLAIR</b>${esc(D.name)} a dépassé ${line} ${STATS[s].toLowerCase()} ${o} fois sur ses ${n} derniers matchs. Ce soir : ${plus} facteur${plus > 1 ? "s" : ""} favorable${plus > 1 ? "s" : ""}, ${minus} défavorable${minus > 1 ? "s" : ""} (bilan ${sc > 0 ? "+" : ""}${sc}).</div>
  <div class="card">${F.length ? F.map(f => `<div class="fac ${f[0] > 0 ? "p" : "m"}"><span class="ic">${f[0] > 0 ? "▲" : "▼"}</span><div>${esc(f[1])}</div></div>`).join("") : `<div class="note">Rien de marquant ce soir : contexte neutre par rapport à sa moyenne.</div>`}</div>
  <p class="note">Les facteurs comparent le contexte du soir à sa moyenne de saison. Ce n'est pas une prédiction.</p>`;
}

function barChart(D, rows, s, line, valueFn = val, lineFn = null){
  rows = rows.slice().reverse();
  if (!rows.length) return "";
  const W = 640, H = 200, pad = 24, bw = (W - pad) / rows.length;
  const max = Math.max(line || 0, ...rows.map(r => valueFn(r, s))) * 1.15 || 1;
  const y = v => H - 22 - (v / max) * (H - 40);
  let g = "";
  rows.forEach((r, i) => {
    const v = valueFn(r, s), l = lineFn ? lineFn(r) : line, over = v > l;
    const x = pad + i * bw + bw * 0.15, w = bw * 0.7;
    g += `<rect x="${x}" y="${y(v)}" width="${w}" height="${Math.max(1, H - 22 - y(v))}" rx="3" fill="${over ? "var(--up)" : "var(--dn)"}" opacity=".85"/>`;
    g += `<text x="${x + w / 2}" y="${y(v) - 4}" text-anchor="middle" font-size="11" fill="var(--tx)">${Math.round(v * 10) / 10}</text>`;
    g += `<text x="${x + w / 2}" y="${H - 6}" text-anchor="middle" font-size="9" fill="var(--tx3)">${esc(r.opp)}</text>`;
  });
  const ly = y(line);
  g += `<line x1="${pad}" x2="${W}" y1="${ly}" y2="${ly}" stroke="var(--acc)" stroke-dasharray="5 4" stroke-width="1.5"/><text x="2" y="${ly + 4}" font-size="11" fill="var(--acc2)">${line}</text>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Derniers matchs">${g}</svg>`;
}

function gameTable(D, rows, s, line, extra = true){
  return `<div class="tw"><table><thead><tr><th>Date</th><th>Adv.</th><th>Min</th><th>${STATS[s]}</th><th>Ligne</th>${extra ? "<th>Tirs</th>" : ""}</tr></thead><tbody>
  ${rows.map(r => { const v = val(r, s), [l, arch] = lineFor(D, r, s, line); return `<tr><td>${r.date.slice(5).split("-").reverse().join("/")}${r.season !== D.rows[0].season ? ` <small style="color:var(--tx3)">${r.date.slice(0, 4)}</small>` : ""}</td><td>${r.home ? "vs" : "@"} ${esc(r.opp)}</td><td>${Math.round(r.min)}</td><td class="${v > l ? "o" : "u"}"><span class="dot ${v > l ? "o" : "u"}"></span>${v}</td><td>${l}${arch ? ' <span class="arch">●</span>' : ""}</td>${extra ? `<td>${r.fgm}/${r.fga} · ${r.tpm}/${r.tpa}</td>` : ""}</tr>`; }).join("")}
  </tbody></table></div>`;
}

function tForm(D, p, s, line){
  const r5 = D.rows.slice(0, 5), r10 = D.rows.slice(0, 10), r20 = D.rows.slice(0, 20);
  const cur = D.rows.filter(r => r.season === D.rows[0].season);
  const [a, b] = hits(D, r5, s, line), [c, d] = hits(D, r10, s, line), [e, f] = hits(D, cur, s, line);
  return `<div class="grid3">${box("5 derniers", a, b)}${box("10 derniers", c, d)}${box("Saison", e, f)}</div>
  <h3>15 derniers matchs (ligne en pointillés)</h3><div class="card">${barChart(D, D.rows.slice(0, 15), s, line)}</div>
  <h3>Détail des matchs</h3><div class="card">${gameTable(D, r20, s, line)}</div>`;
}

function tH2H(D, p, s, line){
  const rows = D.rows.filter(r => r.opp === D.opp);
  const cur = rows.filter(r => r.season === D.rows[0].season);
  const home = rows.filter(r => r.home === (D.home ? 1 : 0));
  const [a, b] = hits(D, rows, s, line), [c, d] = hits(D, cur, s, line), [e, f] = hits(D, home, s, line);
  const avg = rows.length ? rows.reduce((x, r) => x + val(r, s), 0) / rows.length : null;
  return `<div class="clair"><b>💡 EN CLAIR</b>${rows.length ? `Face ${aux(D.opp)}, ${esc(D.name)} tourne à ${f1(avg)} ${STATS[s].toLowerCase()} sur ${rows.length} match${rows.length > 1 ? "s" : ""} (moyenne actuelle ${f1(p.s[s][IDX.avg])}).` : `Aucun match contre ${les(D.opp)} dans l'historique.`}</div>
  <div class="grid3">${box("Tous les H2H", a, b)}${box("Cette saison", c, d)}${box(D.home ? "À domicile" : "À l'extérieur", e, f)}</div>
  ${rows.length ? `<h3>Tous ses matchs contre ${les(D.opp)}</h3><div class="card">${gameTable(D, rows, s, line)}<p class="note"><span class="arch">●</span> = vraie ligne bookmaker archivée ce jour-là ; sinon la ligne actuelle.</p></div>` : ""}`;
}

function tAbs(D, p, s){
  const W = D.withwo || [];
  const inj = (T.injuries[D.team] || []);
  const MIN = 8;
  const cmp = (lab, a, b) => { const d = (b ?? 0) - (a ?? 0); return `<tr><td>${lab}</td><td>${f1(a)}</td><td class="${d > 0.5 ? "o" : d < -0.5 ? "u" : ""}">${f1(b)}</td><td class="${d > 0.5 ? "o" : d < -0.5 ? "u" : ""}">${d >= 0 ? "+" : ""}${f1(d)}</td></tr>`; };
  return `<div class="clair"><b>💡 EN CLAIR</b>${inj.length ? `${inj.length} joueur${inj.length > 1 ? "s" : ""} ${des(D.team)} sur le rapport de blessures.` : `Personne sur le rapport de blessures ${des(D.team)}.`} Ci-dessous, ses chiffres avec et sans chaque coéquipier absent ce soir. Un écart ne compte dans les facteurs qu'à partir de ${MIN} matchs sans le joueur.</div>
  ${W.length ? W.map(m => `<div class="card" style="margin-bottom:8px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><b>${esc(m.name)}</b>${stBadge(m.status)}</div>
    ${m.n_wo < MIN ? `<div class="note" style="margin:0 0 6px;color:var(--mid)">⚠️ Seulement ${m.n_wo} match${m.n_wo > 1 ? "s" : ""} sans lui : échantillon trop petit, à prendre avec prudence.</div>` : ""}
    <div class="tw"><table><thead><tr><th></th><th>Avec<br><small>${m.n_with} m.</small></th><th>Sans<br><small>${m.n_wo} m.</small></th><th>Écart</th></tr></thead><tbody>
      ${cmp(STATS[s], m.with[s], m.wo[s])}
      ${cmp("Minutes", m.with.min, m.wo.min)}
      ${m.with.fga != null ? cmp("Tirs tentés", m.with.fga, m.wo.fga) + cmp("Tirs à 3 pts", m.with.tpa, m.wo.tpa) + cmp("Lancers francs", m.with.fta, m.wo.fta) : ""}
    </tbody></table></div></div>`).join("")
  : `<div class="card note">Pas assez de matchs sans les absents du soir pour comparer (minimum 2).</div>`}
  ${inj.length ? `<h3>Rapport de blessures · ${esc(team(D.team))}</h3><div class="card">${inj.map(i => `<div class="fac"><div>${stBadge(i.status)} <b>${esc(i.name)}</b><div class="note" style="margin:2px 0 0">${esc(i.comment || "")}</div></div></div>`).join("")}</div>` : ""}`;
}

function tSty(D, p, s, line){
  const prof = (T.teams[D.opp] || {}).profile || "Équilibrée";
  const rows = D.rows.filter(r => (T.teams[r.opp] || {}).profile === prof && r.season >= D.rows[0].season - 1);
  const ext = rows.filter(r => !r.home), dom = rows.filter(r => r.home);
  const [a, b] = hits(D, rows, s, line), [c, d] = hits(D, ext, s, line), [e, f] = hits(D, dom, s, line);
  const agg = (D.same_style_vs_opp || {})[s];
  const tags = (T.teams[D.opp] || {}).tags || [];
  const E = (D.style_edge || {})[s];
  const hot = E ? `<div class="stybox lv${E.level}"><div class="t">${STYLAB[E.level]} ce soir</div>
    ${E.own ? `<div>Lui face aux défenses « ${esc(E.profile)} » : <b>${f1(E.own.avg)}</b> de moyenne sur ${E.own.n} matchs, contre ${f1(E.own.base)} au global (${E.own.rel >= 0 ? "+" : ""}${Math.round(E.own.rel * 100)} %).</div>` : ""}
    ${E.grp ? `<div>Les « ${esc(D.style)} » face ${aux(D.opp)} : au-dessus de leur moyenne <b>${Math.round(E.grp.rate * 100)} %</b> du temps (${E.grp.n} matchs).</div>` : ""}
    <div class="note" style="margin-top:6px">${E.level === 2 ? "Ses propres matchs ET ceux des joueurs de son style vont dans le même sens." : "Un des deux signaux est nettement favorable, l'autre ne le contredit pas."}</div></div>` : "";
  return `${hot}<div class="clair"><b>💡 EN CLAIR</b>Défense ${des(D.opp)} : « ${esc(prof)} »${tags.length > 1 ? ` (aussi : ${tags.slice(1).map(esc).join(", ")})` : ""}. ${D.home ? "À domicile" : "À l'extérieur"}, il passe la ligne ${D.home ? `${e} fois sur ${f}` : `${c} fois sur ${d}`} face à ce type de défense.</div>
  <h3>Lui vs défenses « ${esc(prof)} » (2 saisons)</h3>
  <div class="grid3">${box("Global", a, b)}${box("Extérieur", c, d)}${box("Domicile", e, f)}</div>
  <h3>Les « ${esc(D.style)} » vs ${esc(team(D.opp))}</h3>
  ${agg ? `<div class="grid2">${box("Toutes saisons", agg[1], agg[0], "matchs")}${box("Cette saison", agg[3], agg[2], "matchs")}</div><p class="note">Part des matchs où les joueurs de ce style ont dépassé leur propre moyenne de saison face à cette équipe.</p>` : `<div class="card note">Pas encore de données pour ce style face à cette équipe.</div>`}
  ${rows.length ? `<h3>Ses matchs face à ce profil</h3><div class="card">${gameTable(D, rows.slice(0, 15), s, line, false)}</div>` : ""}`;
}

function rkStyle(rank){ const t = (rank - 1) / 29; const c = t < .5 ? `rgba(47,210,124,${.35 - t * .6})` : `rgba(255,90,95,${(t - .5) * .7})`; return `background:${c}`; }
function tDef(D, p, s){
  const b = D._b || D.bucket;
  const dv = (D.dvp || {})[b] || {};
  const me = dv[s];
  return `<div class="clair"><b>💡 EN CLAIR</b>${me ? `${concede(D.opp)} ${me[0]} ${STATS[s].toLowerCase()} par match aux ${BUCKET[b].toLowerCase()} : rang ${me[1]}/30 (1 = la plus généreuse), ${me[2] >= 1 ? "+" : ""}${Math.round((me[2] - 1) * 100)} % par minute vs la moyenne.` : "Données défensives indisponibles."}</div>
  <div class="chips" id="bucketSel">${Object.entries(BUCKET).map(([k, v]) => `<button class="chip ${k === b ? "on" : ""}" data-b="${k}">${v}${k === D.bucket ? " (son poste)" : ""}</button>`).join("")}</div>
  <div class="card"><div class="tw"><table><thead><tr><th>Stat</th><th>Concédé / match</th><th>vs moy.</th><th>Rang</th></tr></thead><tbody>
  ${Object.keys(STATS).map(k => { const x = dv[k]; return x ? `<tr${k === s ? ' style="background:var(--card2)"' : ""}><td>${STATS[k]}</td><td>${x[0]}</td><td class="${x[2] >= 1.05 ? "o" : x[2] <= .95 ? "u" : ""}">${x[2] >= 1 ? "+" : ""}${Math.round((x[2] - 1) * 100)} %</td><td><span class="rk" style="${rkStyle(x[1])}">${x[1]}</span></td></tr>` : ""; }).join("")}
  </tbody></table></div><p class="note">Rang 1 = défense qui concède le plus à ce poste. Comparaison par minute jouée, pondérée vers la saison en cours. <a href="#/dvp" style="color:var(--acc2)">Voir les 30 équipes →</a></p></div>`;
}

function tPace(D, p, s, line){
  const P = D.pace || {};
  const diff = P.proj && P.league ? P.proj - P.league : 0;
  const mins = D.rows.slice(0, 15);
  return `<div class="clair"><b>💡 EN CLAIR</b>Rythme attendu : ${f1(P.proj)} possessions par équipe (moyenne NBA ${f1(P.league)}), soit un match ${Math.abs(diff) < 1 ? "dans la norme" : diff > 0 ? "plus rapide que la moyenne" : "plus lent que la moyenne"}.</div>
  <div class="grid3"><div class="box"><small>${esc(team(D.team))}</small><div class="big">${f1(P.team)}</div><div class="s">rang ${P.team_rank ?? "–"}/30</div></div>
  <div class="box"><small>${esc(team(D.opp))}</small><div class="big">${f1(P.opp)}</div><div class="s">rang ${P.opp_rank ?? "–"}/30</div></div>
  <div class="box"><small>Projection</small><div class="big ${diff >= 2 ? "good" : diff <= -2 ? "bad" : ""}">${f1(P.proj)}</div><div class="s">${diff >= 0 ? "+" : ""}${f1(diff)} vs NBA</div></div></div>
  <h3>Temps de jeu · 15 derniers matchs</h3><div class="card">${barChart(D, mins, "min", Math.round(p.min * 2) / 2, (r) => Math.round(r.min))}</div>`;
}

function tShot(D){
  const x = D.shot || {};
  return `<div class="grid3">
    <div class="box"><small>Tirs tentés</small><div class="big">${f1(x.fga)}</div><div class="s">${f1(x.fg)} % de réussite</div></div>
    <div class="box"><small>Tirs à 3 pts</small><div class="big">${f1(x.tpa)}</div><div class="s">${f1(x.tp)} % · ${f1(x.three_share)} % de ses tirs</div></div>
    <div class="box"><small>Lancers francs</small><div class="big">${f1(x.fta)}</div><div class="s">${f1(x.ft)} % · taux ${f1(x.fta_rate)}</div></div></div>
  <h3>Répartition de ses tirs</h3><div class="card">
    <div style="display:flex;height:16px;border-radius:8px;overflow:hidden"><div style="width:${x.two_share}%;background:var(--acc)"></div><div style="width:${x.three_share}%;background:var(--acc2)"></div></div>
    <div class="note"><span class="dot" style="background:var(--acc)"></span>2 points ${f1(x.two_share)} % &nbsp; <span class="dot" style="background:var(--acc2)"></span>3 points ${f1(x.three_share)} %</div></div>
  ${x.opp_dvp && x.opp_dvp.tpm ? `<p class="note">${concede(D.opp)} ${x.opp_dvp.tpm[0]} paniers à 3 pts par match aux ${BUCKET[D.bucket].toLowerCase()} (rang ${x.opp_dvp.tpm[1]}/30).</p>` : ""}`;
}

function tCar(D, p, s){
  return `<div class="card"><div class="tw"><table><thead><tr><th>Saison</th><th>Équipe</th><th>MJ</th><th>Min</th><th>${STATS[s]}</th><th>Pts</th><th>Reb</th><th>Pas</th><th>3P</th><th>FG%</th><th>3P%</th></tr></thead><tbody>
  ${D.career.map(c => `<tr><td>${c.season}</td><td>${esc(c.team)}</td><td>${c.gp}</td><td>${f1(c.min)}</td><td><b>${f1(c[s])}</b></td><td>${f1(c.pts)}</td><td>${f1(c.reb)}</td><td>${f1(c.ast)}</td><td>${f1(c.tpm)}</td><td>${f1(c.fg)}</td><td>${f1(c.tp)}</td></tr>`).join("")}
  </tbody></table></div>${D.career.map(c => c.style ? `<span class="tag" style="margin:8px 6px 0 0">${c.season} · ${esc(c.style)}</span>` : "").join("")}</div>`;
}

/* ------------------------------------------------------------------ défense vs poste */
async function renderDvp(){
  if (!DVP) DVP = await getJSON("data/dvp.json");
  const tonight = new Set(T.games.flatMap(g => [g.home, g.away]));
  const draw = () => {
    const rows = Object.keys(DVP.dvp).map(t => ({ t, x: DVP.dvp[t][S.dvpPos] || {} })).filter(r => r.x[S.dvpStat]);
    rows.sort((a, b) => a.x[S.dvpStat][1] - b.x[S.dvpStat][1]);
    const cols = Object.keys(STATS);
    $app.innerHTML = `<div class="hero"><div><h1>Défense vs poste</h1><div class="sub">Ce que chaque défense concède par match, saison ${esc(DVP.season)}. Vert = généreuse, rouge = hermétique.</div></div></div>
    <div class="chips" id="pos">${Object.entries(BUCKET).map(([k, v]) => `<button class="chip ${k === S.dvpPos ? "on" : ""}" data-p="${k}">${v}</button>`).join("")}</div>
    <div class="card dvp"><div class="tw"><table><thead><tr><th>Équipe</th><th>Profil</th>${cols.map(k => `<th data-s="${k}" class="${k === S.dvpStat ? "on" : ""}">${STATS[k]}</th>`).join("")}</tr></thead><tbody>
    ${rows.map(r => `<tr><td>${tonight.has(r.t) ? "🏀 " : ""}<b>${esc(team(r.t))}</b></td><td><span class="tag">${esc((DVP.profiles[r.t] || {}).profile || "")}</span></td>${cols.map(k => { const v = r.x[k]; if (!v) return "<td>–</td>"; const q = Math.min(5, Math.floor((v[1] - 1) / 6) + 1); return `<td class="rk${q}">${v[0]}<small>${v[1]}</small></td>`; }).join("")}</tr>`).join("")}
    </tbody></table></div><p class="note">Petit chiffre = rang (1 = concède le plus). Clique sur une colonne pour trier. 🏀 = joue ce soir.</p></div>`;
    document.getElementById("pos").onclick = e => { const b = e.target.closest("[data-p]"); if (b) { S.dvpPos = b.dataset.p; draw(); } };
    document.querySelector(".dvp thead").onclick = e => { const th = e.target.closest("[data-s]"); if (th) { S.dvpStat = th.dataset.s; draw(); } };
  };
  draw();
}

/* ================================================================== TENNIS */
let TN = null;
const SURF = { hard:"Dur", clay:"Terre battue", grass:"Gazon" };
const TS = { tour:"all", value:false, sort:"time", tab:"res" };
const pctS = x => x == null ? "–" : Math.round(x * 100) + "%";
const odd = x => x ? x.toFixed(2) : "–";
const VAL = { Strong:"Strong", Moderate:"Moderate", Slight:"Slight" };

async function renderTennis(h){
  if (!TN) TN = await getJSON("data/tennis.json");
  document.getElementById("meta").textContent = `Tennis mis à jour le ${new Date(TN.generated).toLocaleString("fr-FR")} · ${TN.n_hist} matchs en base`;
  if (h.startsWith("#/tennis/m/")) return renderTennisMatch(h.slice(11));
  const draw = () => {
    let ms = TN.matches.filter(m => (TS.tour === "all" || m.tour === TS.tour) && (!TS.value || m.value));
    if (TS.sort === "value") ms = ms.slice().sort((a, b) => ((b.value || {}).gap || 0) - ((a.value || {}).gap || 0));
    const nV = TN.matches.filter(m => m.value).length;
    $app.innerHTML = `<div class="hero"><div><h1>Tennis du jour</h1><div class="sub">ATP et WTA · probabilités Elo par surface, styles de jeu, face à face${TN.has_odds ? "" : " · pas de clé cotes : value signals désactivés"}</div></div>
      <div class="kpis"><div class="kpi"><div class="big">${TN.matches.length}</div><small>Matchs</small></div><div class="kpi"><div class="big" style="color:var(--acc)">${nV}</div><small>Value</small></div></div></div>
      <div class="chips" id="ttour">${[["all","Tous"],["atp","ATP"],["wta","WTA"]].map(([k, v]) => `<button class="chip ${TS.tour === k ? "on" : ""}" data-t="${k}">${v}</button>`).join("")}
        <button class="chip ${TS.value ? "on" : ""}" id="tval">💎 Value seulement</button>
        <button class="chip ${TS.sort === "value" ? "on" : ""}" id="tsort">Trier par value</button></div>
      <div class="list">${ms.map(tCard).join("") || `<div class="empty">Aucun match.</div>`}</div>
      <p class="note">Les value signals comparent la cote à une probabilité mélangeant notre modèle et le marché, par prudence. Analyse statistique, pas un pronostic.</p>`;
    document.getElementById("ttour").onclick = e => { const b = e.target.closest("[data-t]"); if (b) { TS.tour = b.dataset.t; draw(); } };
    document.getElementById("tval").onclick = () => { TS.value = !TS.value; draw(); };
    document.getElementById("tsort").onclick = () => { TS.sort = TS.sort === "value" ? "time" : "value"; draw(); };
  };
  draw();
}

function pRow(P, p, o, isVal){
  return `<div class="tp"><div class="tn"><b>${esc(P.name)}</b>${P.rank ? ` <small>#${P.rank}</small>` : ""}${P.style ? ` <span class="tag style">${esc(TN.styles[P.style])}</span>` : ""}</div>
    <div class="tnum"><span class="big">${pctS(p)}</span>${o ? `<span class="todd ${isVal ? "v" : ""}">${odd(o)}</span>` : ""}</div></div>`;
}
function tCard(m){
  const v = m.value;
  const t = m.state === "pre" ? timeOf(m.date + "Z") : esc(m.detail || "");
  return `<a class="row tcard ${v ? "styhot lv" + (v.level === "Strong" ? 2 : 1) : ""}" href="#/tennis/m/${m.id}">
    <div class="tl1"><span class="st q">${m.tour.toUpperCase()}</span> ${esc(m.event)} · ${esc(m.round)} · ${SURF[m.surface]} · ${t}
      ${v ? `<span class="sbadge lv${v.level === "Strong" ? 2 : 1}">💎 ${v.level} +${Math.round(v.gap * 100)}%</span>` : ""}</div>
    ${pRow(m.A, m.p, m.odds[0], v && v.side === 0)}${pRow(m.B, 1 - m.p, m.odds[1], v && v.side === 1)}
    <div class="pbar"><i style="width:${Math.round(m.p * 100)}%"></i></div>
    ${m.h2h.length ? `<div class="note" style="margin-top:4px">H2H ${m.h2h.filter(x => x.w).length}-${m.h2h.filter(x => !x.w).length}</div>` : ""}
  </a>`;
}

function renderTennisMatch(id){
  const m = TN.matches.find(x => x.id === id);
  if (!m) { $app.innerHTML = `<div class="empty">Match introuvable. <a href="#/tennis" style="color:var(--acc2)">Retour</a></div>`; return; }
  const TABS = [["res","⭐ Résumé"],["sty","🎯 Styles"],["h2h","🆚 H2H"],["form","📈 Forme"],["fat","🔋 Fatigue"],["odds","💶 Cotes"]];
  const draw = () => {
    $app.innerHTML = `<a class="back" href="#/tennis">← Tennis du jour</a>
    <div class="ph"><div class="l1">${m.tour.toUpperCase()} · ${esc(m.event)} · ${esc(m.round)} · ${SURF[m.surface]}</div>
      <h1 style="font-size:26px">${esc(m.A.name)} <span style="color:var(--tx3)">vs</span> ${esc(m.B.name)}</h1>
      <div class="stats"><div><small>${esc(m.A.name.split(" ").slice(-1)[0])}</small><div class="big">${pctS(m.p)}</div></div>
      <div><small>${esc(m.B.name.split(" ").slice(-1)[0])}</small><div class="big">${pctS(1 - m.p)}</div></div>
      ${m.value ? `<div><small>Value</small><div class="big" style="color:var(--acc2)">${m.value.level}</div></div>` : ""}</div>
      <div class="pbar" style="margin-top:12px"><i style="width:${Math.round(m.p * 100)}%"></i></div></div>
    <div class="tabs">${TABS.map(([k, v]) => `<button class="tab ${k === TS.tab ? "on" : ""}" data-tab="${k}">${v}</button>`).join("")}</div>
    <div id="tab">${({ res:tRes, sty:tSt, h2h:tH, form:tF, fat:tFa, odds:tO }[TS.tab] || tRes)(m)}</div>`;
    document.querySelector(".tabs").onclick = e => { const b = e.target.closest("[data-tab]"); if (b) { TS.tab = b.dataset.tab; draw(); } };
  };
  draw();
}
function who(m, sgn){ return sgn > 0 ? m.A.name : sgn < 0 ? m.B.name : null; }
function tRes(m){
  const fav = m.p >= 0.5 ? m.A : m.B, pf = Math.max(m.p, 1 - m.p);
  return `<div class="clair"><b>💡 EN CLAIR</b>${esc(fav.name)} est favori${m.tour === "wta" ? "te" : ""} du modèle à ${pctS(pf)}${m.p_mkt ? `, le marché le donne à ${pctS(m.p >= 0.5 ? m.p_mkt : 1 - m.p_mkt)}` : ""}.${m.value ? ` Value « ${m.value.level} » sur ${esc((m.value.side ? m.B : m.A).name)} : cote ${odd(m.value.odds)} contre une cote juste estimée à ${odd(m.value.fair)} (écart +${Math.round(m.value.gap * 100)} %).` : ""}</div>
  <div class="card">${m.fac.map(f => `<div class="fac ${f[0] ? (f[0] > 0 ? "p" : "m") : ""}"><span class="ic" style="${f[0] ? "" : "background:var(--card2);color:var(--tx3)"}">${f[0] ? "●" : "i"}</span><div>${f[0] ? `<small style="color:var(--tx3)">Avantage ${esc(who(m, f[0]))}</small><br>` : ""}${esc(f[1])}</div></div>`).join("")}</div>
  <h3>D'où vient la probabilité</h3><div class="grid3">
    <div class="box"><small>Elo global</small><div class="big">${pctS(m.p_all)}</div><div class="s">${m.A.elo} / ${m.B.elo}</div></div>
    <div class="box"><small>Elo ${SURF[m.surface].toLowerCase()}</small><div class="big">${pctS(m.p_surf)}</div><div class="s">${m.A.selo} / ${m.B.selo}</div></div>
    <div class="box"><small>Modèle final</small><div class="big">${pctS(m.p)}</div><div class="s">+ styles et fatigue</div></div></div>
  <p class="note">Probabilités pour ${esc(m.A.name)}. Fiabilité : ${m.conf} matchs mini dans l'historique pour l'un des deux${m.conf < 15 ? " (faible)" : ""}.</p>`;
}
function tSt(m){
  const a = m.arche;
  const card = P => `<div class="box"><small>${esc(P.name)}</small><div class="big" style="font-size:20px">${P.style ? esc(TN.styles[P.style]) : "Style inconnu"}</div><div class="s">${esc(P.style_note || "Pas assez d'informations fiables sur ce joueur.")}${P.style_src ? ` · <a href="${esc(P.style_src)}" target="_blank" rel="noopener" style="color:var(--acc2)">source</a>` : ""}</div></div>`;
  const rec = (P, O) => O.style ? `<div class="grid2">${box(`${esc(P.name)} vs « ${esc(TN.styles[O.style])} »`, P.vs_style[0], P.vs_style[1], "toutes surfaces")}${box(`Sur ${SURF[m.surface].toLowerCase()}`, P.vs_style_s[0], P.vs_style_s[1])}</div>` : "";
  return `${a ? `<div class="stybox ${((a.surf[1] >= 30 ? a.surf : a.all)[0] / Math.max(1, (a.surf[1] >= 30 ? a.surf : a.all)[1])) >= .55 || ((a.surf[1] >= 30 ? a.surf : a.all)[0] / Math.max(1, (a.surf[1] >= 30 ? a.surf : a.all)[1])) <= .45 ? "lv2" : ""}"><div class="t">Insight d'archétype</div>
     <div>Les « ${esc(TN.styles[m.A.style])} » contre les « ${esc(TN.styles[m.B.style])} » : <b>${a.surf[1] ? Math.round(100 * a.surf[0] / a.surf[1]) + " %" : "–"}</b> de victoires sur ${SURF[m.surface].toLowerCase()} (${a.surf[1]} matchs), ${a.all[1] ? Math.round(100 * a.all[0] / a.all[1]) : "–"} % toutes surfaces (${a.all[1]} matchs).</div></div>` : `<div class="clair"><b>💡 EN CLAIR</b>${!m.A.style || !m.B.style ? "Le style d'au moins un des deux joueurs n'est pas connu." : "Les deux joueurs ont le même style : pas d'avantage d'archétype."}</div>`}
  <div class="grid2">${card(m.A)}${card(m.B)}</div>
  ${rec(m.A, m.B) ? `<h3>Bilan face à ce style</h3>${rec(m.A, m.B)}${rec(m.B, m.A)}` : ""}`;
}
function tH(m){
  if (!m.h2h.length) return `<div class="card note">Jamais affrontés dans notre historique (depuis 2024, circuit principal).</div>`;
  const wa = m.h2h.filter(x => x.w).length;
  return `<div class="grid2">${box(`Victoires ${esc(m.A.name)}`, wa, m.h2h.length)}${box(`Sur ${SURF[m.surface].toLowerCase()}`, m.h2h.filter(x => x.w && x.s === m.surface).length, m.h2h.filter(x => x.s === m.surface).length)}</div>
  <div class="card" style="margin-top:8px"><div class="tw"><table><thead><tr><th>Date</th><th>Tournoi</th><th>Surface</th><th>Vainqueur</th><th>Score</th></tr></thead><tbody>
  ${m.h2h.map(x => `<tr><td>${x.d.split("-").reverse().join("/")}</td><td>${esc(x.ev)} <small style="color:var(--tx3)">${esc(x.r)}</small></td><td>${SURF[x.s]}</td><td class="${x.w ? "o" : "u"}">${esc(x.w ? m.A.name : m.B.name)}</td><td>${esc(x.sc)}</td></tr>`).join("")}</tbody></table></div></div>`;
}
function tF(m){
  const blk = P => `<h3>${esc(P.name)} · ${P.form.split("").map(c => `<span class="dot ${c === "V" ? "o" : "u"}"></span>`).join("")}</h3>
  <div class="grid2">${box("12 derniers mois", P.yr[0], P.yr[1])}${box(`Sur ${SURF[m.surface].toLowerCase()}`, P.yr_s[0], P.yr_s[1])}</div>
  <div class="card" style="margin-top:8px"><div class="tw"><table><thead><tr><th>Date</th><th>Adversaire</th><th>Surface</th><th>Résultat</th><th>Score</th></tr></thead><tbody>
  ${P.last.map(x => `<tr><td>${x.d.slice(5).split("-").reverse().join("/")}</td><td>${esc(x.o)}</td><td>${SURF[x.s]}</td><td class="${x.w ? "o" : "u"}">${x.w ? "V" : "D"}${x.ret ? " (ab.)" : ""}</td><td>${esc(x.sc)}</td></tr>`).join("")}</tbody></table></div></div>`;
  return blk(m.A) + blk(m.B);
}
function tFa(m){
  const f = P => `<div class="box"><small>${esc(P.name)}</small><div class="big">${P.d7}</div><div class="s">matchs sur 7 jours · ${P.d7_sets} sets · ${P.d3} sur 3 jours</div></div>`;
  return `<div class="clair"><b>💡 EN CLAIR</b>Plus un joueur a enchaîné les matchs et les sets récemment, plus le modèle le pénalise légèrement.</div><div class="grid2">${f(m.A)}${f(m.B)}</div>`;
}
function tO(m){
  if (!m.odds[0]) return `<div class="card note">${TN.has_odds ? "Pas de cote trouvée pour ce match (souvent le cas hors ATP/WTA principal)." : "Ajoute ta clé The Odds API (secret ODDS_API_KEY) pour voir les cotes et les value signals."}</div>`;
  const r = (P, o, p) => `<tr><td>${esc(P.name)}</td><td>${odd(o)}</td><td>${pctS(1 / o)}</td><td>${pctS(p)}</td><td>${odd(1 / p)}</td><td class="${p * o - 1 > 0 ? "o" : "u"}">${(p * o - 1 >= 0 ? "+" : "") + Math.round((p * o - 1) * 100)} %</td></tr>`;
  return `<div class="card"><div class="tw"><table><thead><tr><th>Joueur</th><th>Meilleure cote</th><th>Proba implicite</th><th>Proba modèle</th><th>Cote juste</th><th>Écart</th></tr></thead><tbody>${r(m.A, m.odds[0], m.p)}${r(m.B, m.odds[1], 1 - m.p)}</tbody></table></div>
  <p class="note">Seuils : Slight dès +8 %, Moderate dès +15 %, Strong dès +25 %, calculés sur une probabilité mélangeant modèle et marché pour limiter les faux signaux. Un écart positif n'est jamais une garantie.</p></div>`;
}

route();
})();
