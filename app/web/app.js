"use strict";

// Flow console: replays the audit trace as messages moving between
// buyer -> concierge -> isolated scouts -> sellers and back.

const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";
const SEV_RANK = { low: 1, medium: 2, high: 3, critical: 4 };
const KIND_COLOR = { req: "--req", raw: "--raw", bad: "--bad", json: "--json", buy: "--buy" };

const state = {
  trace: null,
  gen: 0,            // bumps on every replay so stale coroutines stop
  paused: false,
  speed: 1,
  sim: 0,            // simulated ms, advances only while playing
  lastTs: 0,
  waits: [],
  packets: [],
  events: [],
  selected: null,
  pinned: false,     // user picked a log line -> stop auto-following
  edges: {},
  kpi: {},
};

// ---------- helpers ----------
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
const money = (n) => "$" + Number(n).toFixed(2);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const json = (o) => esc(JSON.stringify(o, null, 2));

function highlight(text, evidences) {
  let out = esc(text);
  for (const ev of evidences || []) {
    const needle = esc(ev).trim();
    if (needle.length >= 4 && out.includes(needle)) out = out.split(needle).join(`<mark>${needle}</mark>`);
  }
  return out;
}
function plainReason(reason) {
  const r = String(reason || ""), i = r.indexOf(":");
  const body = (i > -1 && i < 40 ? r.slice(i + 1) : r).trim();
  return body.charAt(0).toUpperCase() + body.slice(1);
}
const checkLabel = (id) => ((state.trace.checks.find(c => c.id === id) || {}).label || id);
const findings = (s) => s.audit.subAgents.flatMap(r => r.findings.map(f => ({ ...f, agent: r.agent })));
function topFinding(s) {
  return findings(s).sort((a, b) => (SEV_RANK[b.severity] || 0) - (SEV_RANK[a.severity] || 0))[0] || null;
}
const isOk = (s) => s.audit.overallDecision === "allow" || s.audit.overallDecision === "allow_with_constraints";
const rawChars = (s) => (s.description || "").length + (s.returnPolicy || "").length + JSON.stringify(s.paymentHandler || {}).length;
function pill(decision) {
  const cls = decision === "allow" ? "allow" : decision === "block" ? "block" : decision === "pending" ? "pending" : "review";
  const label = { allow: "safe", allow_with_constraints: "safe w/ limits", needs_manual_review: "review", block: "blocked", pending: "…" }[decision] || decision;
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

// ---------- simulated clock (pause / speed aware) ----------
function tick() {
  const ts = performance.now();
  const dt = state.lastTs ? Math.min(1000, ts - state.lastTs) : 0;
  state.lastTs = ts;
  if (!state.paused) state.sim += dt * state.speed;
  state.waits = state.waits.filter(w => (w.until <= state.sim ? (w.res(), false) : true));
  state.packets = state.packets.filter(p => {
    const k = Math.min(1, (state.sim - p.start) / p.dur);
    const len = p.path.getTotalLength();
    const pt = p.path.getPointAtLength(len * (p.reverse ? 1 - k : k));
    p.el.setAttribute("cx", pt.x); p.el.setAttribute("cy", pt.y);
    if (k >= 1) { p.el.remove(); p.res(); return false; }
    return true;
  });
}
// a timer rather than requestAnimationFrame so playback keeps going in throttled/background tabs
setInterval(tick, 16);

const ABORT = Symbol("abort");
async function sleep(ms, gen) {
  await new Promise(res => state.waits.push({ until: state.sim + ms, res }));
  if (gen !== state.gen) throw ABORT;
}
async function send(path, kind, dur, gen, reverse = false) {
  const el = document.createElementNS(SVGNS, "circle");
  const color = cssVar(KIND_COLOR[kind]);
  el.setAttribute("r", kind === "bad" ? 6 : 4.5);
  el.setAttribute("fill", color);
  el.setAttribute("class", "packet");
  el.style.color = color;
  $("edges").appendChild(el);
  await new Promise(res => state.packets.push({ path, el, reverse, start: state.sim, dur, res }));
  if (gen !== state.gen) throw ABORT;
}

// ---------- data loading ----------
async function loadTrace(fresh = false) {
  $("loading").classList.remove("hidden");
  try {
    const res = await fetch(`/api/run?stores=${$("storesSel").value}&fresh=${fresh ? 1 : 0}`);
    const t = await res.json();
    if (t.error) { alert("Pipeline error: " + t.error); return; }
    state.trace = t;
    renderBadges(t);
    play();
  } catch (e) {
    console.error(e); alert("Failed to load: " + e.message);
  } finally {
    $("loading").classList.add("hidden");
  }
}

function renderBadges(t) {
  const m = $("modeBadge");
  m.textContent = t.usedRealAgents ? "live agents" : "mock run";
  m.className = "badge " + (t.usedRealAgents ? "real" : "");
  const w = $("weaveBadge");
  if (t.weaveActive && t.weaveUrl) { w.href = t.weaveUrl; w.classList.remove("hidden"); } else w.classList.add("hidden");
}

// ---------- static layout ----------
function renderNodes(t) {
  const b = t.buyer, c = b.personalContext;
  $("buyerNode").innerHTML = `
    <div class="node-kicker">Buyer</div>
    <div class="node-title">${esc(b.name)}</div>
    <div class="q">“${esc(b.question)}”</div>
    <div class="node-line">Budget $${Number(c.budget).toFixed(0)} · must have ${esc((c.mustHaves || []).join(", "))}</div>
    <div class="node-state" id="buyerState">waiting</div>`;
  $("conciergeNode").innerHTML = `
    <div class="node-kicker">Concierge</div>
    <div class="node-title">Master agent</div>
    <div class="node-line">Reads structured reports only</div>
    <div class="node-state" id="concState">idle</div>
    <div class="meter"><i id="concMeter"></i></div>
    <div class="node-line" id="concCount" style="margin-top:4px">0/${t.sellers.length} reports</div>
    <div class="decision hidden" id="concDecision"></div>`;

  $("lanes").innerHTML = t.sellers.map(s => `
    <div class="lane" id="lane-${s.sellerId}">
      <span class="lane-tag">context · ${esc(s.sellerId)}</span>
      <div class="node scout" id="scout-${s.sellerId}" data-id="${s.sellerId}">
        <div class="node-title">Scout ${pill("pending")}</div>
        <div class="node-line" id="sstate-${s.sellerId}">idle</div>
        <div class="checks">${t.checks.map(ch => `<span class="ck" data-check="${ch.id}" title="${esc(ch.label)}"></span>`).join("")}</div>
        <div class="contain-note hidden" id="note-${s.sellerId}"></div>
      </div>
      <div></div>
      <div class="node seller" id="seller-${s.sellerId}" data-id="${s.sellerId}">
        <div class="node-title">${esc(s.name)} <span class="node-line">${money(s.price)}</span></div>
        <div class="node-line">${esc(s.domain)}</div>
        <div class="node-line" id="mstate-${s.sellerId}" style="color:var(--txt-3)">idle</div>
        <div class="truth ${s.groundTruth.dirty ? "dirty" : "clean"}">${s.groundTruth.dirty ? "planted: " + esc(s.groundTruth.attacks.map(checkLabel).join(", ")) : "honest seller"}</div>
      </div>
    </div>`).join("");

  // node clicks -> inspect the most relevant message for that node
  $("buyerNode").onclick = () => inspectWhere(e => e.kind === "req" && e.from === "Buyer");
  $("conciergeNode").onclick = () => inspectWhere(e => e.step === "decision") || inspectWhere(e => e.kind === "req");
  document.querySelectorAll(".scout").forEach(el => el.onclick = () => inspectWhere(e => e.step === "report" && e.sellerId === el.dataset.id));
  document.querySelectorAll(".seller").forEach(el => el.onclick = () => inspectWhere(e => e.step === "raw" && e.sellerId === el.dataset.id));
}

// ---------- edges ----------
function rel(el) {
  const c = $("canvas").getBoundingClientRect(), r = el.getBoundingClientRect();
  return { l: r.left - c.left, r: r.right - c.left, t: r.top - c.top, b: r.bottom - c.top, cx: r.left - c.left + r.width / 2, cy: r.top - c.top + r.height / 2 };
}
function curve(a, b) {
  const mx = (a.x + b.x) / 2;
  return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
}
function ensurePath(key, cls) {
  if (!state.edges[key]) {
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("class", "edge " + (cls || ""));
    $("edges").prepend(p);
    state.edges[key] = p;
  }
  return state.edges[key];
}
function layoutEdges() {
  const t = state.trace;
  if (!t) return;
  const svg = $("edges"), cv = $("canvas");
  svg.setAttribute("width", cv.scrollWidth); svg.setAttribute("height", cv.scrollHeight);
  const B = rel($("buyerNode")), C = rel($("conciergeNode"));
  ensurePath("b2c").setAttribute("d", curve({ x: B.r, y: B.cy }, { x: C.l, y: C.cy }));
  for (const s of t.sellers) {
    const S = rel($("scout-" + s.sellerId)), M = rel($("seller-" + s.sellerId));
    ensurePath("c2s-" + s.sellerId).setAttribute("d", curve({ x: C.r, y: C.cy }, { x: S.l, y: S.cy }));
    ensurePath("s2m-" + s.sellerId).setAttribute("d", curve({ x: S.r, y: S.cy }, { x: M.l, y: M.cy }));
  }
  const w = t.concierge.winnerSellerId && $("seller-" + t.concierge.winnerSellerId);
  if (w) {
    const W = rel(w), L = rel($("lane-" + t.concierge.winnerSellerId));
    const top = L.t - 6;
    ensurePath("buy", "off").setAttribute("d",
      `M ${C.r} ${C.cy - 14} C ${C.r + 60} ${C.cy - 14}, ${C.r + 40} ${top}, ${C.r + 110} ${top} L ${W.cx - 40} ${top} C ${W.cx} ${top}, ${W.cx} ${top}, ${W.cx} ${W.t}`);
  }
}
function edgeClass(key, cls) { const p = state.edges[key]; if (p) p.setAttribute("class", "edge " + cls); }

// ---------- events / log / inspector ----------
function logEvent(ev) {
  ev.t = state.sim / 1000;
  ev.idx = state.events.length;
  state.events.push(ev);
  const li = document.createElement("li");
  li.dataset.idx = ev.idx;
  li.innerHTML = `<span class="t">${ev.t.toFixed(1)}s</span><span class="k" style="background:var(${KIND_COLOR[ev.kind]})"></span>
    <span class="m"><span class="route">${esc(ev.from)} → ${esc(ev.to)}</span> · <span class="what">${esc(ev.what)}</span>${ev.flag ? ` <span class="flag">${esc(ev.flag)}</span>` : ""}</span>`;
  li.onclick = () => { state.pinned = true; select(ev); };
  const log = $("log");
  log.appendChild(li);
  log.scrollTop = log.scrollHeight;
  state.kpi.msgs = state.events.length;
  $("logCount").textContent = `${state.events.length} messages`;
  renderKpis();
  if (!state.pinned) select(ev);
  return ev;
}
function inspectWhere(pred) {
  const ev = state.events.find(pred);
  if (ev) { state.pinned = true; select(ev); }
  return ev;
}
function select(ev) {
  state.selected = ev;
  document.querySelectorAll(".log li").forEach(li => li.classList.toggle("sel", Number(li.dataset.idx) === ev.idx));
  $("inspector").innerHTML = `
    <div class="ins-route">${esc(ev.from)} → ${esc(ev.to)}</div>
    <div class="ins-kind">${esc(ev.what)} · t=${ev.t.toFixed(1)}s</div>
    ${ev.body()}`;
}

// ---------- KPIs ----------
function renderKpis() {
  const t = state.trace, k = state.kpi;
  const n = t.sellers.length;
  const done = k.decision;
  $("kpis").innerHTML = `
    <div class="kpi"><div class="kpi-cap">Messages exchanged</div><div class="kpi-num">${k.msgs || 0}</div><div class="kpi-sub">${k.reports || 0}/${n} scout reports in</div></div>
    <div class="kpi"><div class="kpi-cap">Raw seller text held in scouts</div><div class="kpi-num">${(k.held || 0).toLocaleString()} chars</div><div class="kpi-sub">descriptions, policies, payment config</div></div>
    <div class="kpi good"><div class="kpi-cap">Raw seller text reaching concierge</div><div class="kpi-num">0 chars</div><div class="kpi-sub">only structured reports cross</div></div>
    <div class="kpi ${k.contained ? "bad" : ""}"><div class="kpi-cap">Attacks contained</div><div class="kpi-num">${k.contained || 0} sellers</div><div class="kpi-sub">${k.findings || 0} flagged passages kept out</div></div>
    <div class="kpi ${done ? "good" : ""}"><div class="kpi-cap">Purchase</div><div class="kpi-num">${done ? esc(done) : "—"}</div><div class="kpi-sub">${done ? esc(k.accuracy) : "deciding…"}</div></div>`;
}

// ---------- the replay ----------
function resetRun() {
  state.gen++;
  state.waits = []; state.packets = []; state.events = []; state.edges = {};
  state.pinned = false; state.sim = 0; state.kpi = {};
  $("edges").innerHTML = ""; $("log").innerHTML = ""; $("inspector").innerHTML = "";
  $("phaseLabel").textContent = "starting";
  renderNodes(state.trace);
  renderKpis();
  requestAnimationFrame(layoutEdges);
}
const setPhase = (p) => { $("phaseLabel").textContent = p; };
function pulse(el) { el.classList.add("pulse"); setTimeout(() => el.classList.remove("pulse"), 500); }

async function play() {
  resetRun();
  const gen = state.gen;
  await sleep(250, gen).catch(() => {});
  if (gen !== state.gen) return;
  layoutEdges();
  try { await runFlow(gen); } catch (e) { if (e !== ABORT) console.error(e); }
}

async function runFlow(gen) {
  const t = state.trace, b = t.buyer, c = t.concierge;
  const E = state.edges;
  const winner = t.sellers.find(s => s.sellerId === c.winnerSellerId);

  // 1. buyer -> concierge
  setPhase("1 · request");
  $("buyerState").textContent = "sent request"; $("buyerState").className = "node-state on";
  edgeClass("b2c", "req");
  logEvent({
    kind: "req", step: "request", from: "Buyer", to: "Concierge", what: "shopping request",
    body: () => `<div class="boundary info">The buyer's goal and preferences. This is the only thing the buyer sends.</div>
      <div class="f-label">Question</div><div class="code">${esc(b.question)}</div>
      <div class="f-label">Personal context</div><div class="code">${json(b.personalContext)}</div>`,
  });
  await send(E.b2c, "req", 900, gen);
  pulse($("conciergeNode"));
  $("concState").textContent = "dispatching scouts"; $("concState").className = "node-state on";

  // 2-5. one isolated lane per seller, run in parallel
  setPhase("2 · fan-out to isolated scouts");
  let reports = 0;
  await Promise.all(t.sellers.map((s, i) => runLane(s, i, gen, () => {
    reports++;
    state.kpi.reports = reports;
    $("concMeter").style.width = (100 * reports / t.sellers.length) + "%";
    $("concCount").textContent = `${reports}/${t.sellers.length} reports`;
    if (reports === t.sellers.length) setPhase("4 · adjudicating");
  })));

  // 6. concierge decides
  setPhase("4 · adjudicating");
  $("concState").textContent = "comparing reports";
  await sleep(700, gen);
  const blocked = t.sellers.filter(s => !isOk(s));
  $("concState").textContent = "decided"; $("concState").className = "node-state done";
  const dec = $("concDecision");
  dec.classList.remove("hidden");
  dec.innerHTML = winner ? `Buy from <b>${esc(winner.name)}</b> · ${money(winner.price)}<br><span class="muted">rejected ${blocked.length} seller${blocked.length === 1 ? "" : "s"}</span>` : esc(c.why);
  logEvent({
    kind: "req", step: "decision", from: "Concierge", to: "Concierge", what: "adjudicate reports",
    body: () => `<div class="boundary ok">Decision made from ${t.sellers.length} structured reports. No seller-written text was read.</div>
      <div class="f-label">Reasoning</div><div class="code">${esc(c.why)}</div>
      <div class="f-label">Ranking</div><div class="code">${esc((c.ranking || []).map(id => (t.sellers.find(s => s.sellerId === id) || {}).name || id).join("  >  "))}</div>
      <div class="f-label">Rejected</div><div class="code">${(c.rejected || []).map(r => `${esc(r.name)}: ${esc((r.attacksDetected || []).map(checkLabel).join(", "))}`).join("\n") || "none"}</div>`,
  });

  if (!winner) { setPhase("done · no safe seller"); return; }

  // 7. recommendation back to buyer
  setPhase("5 · recommend");
  logEvent({
    kind: "req", step: "recommend", from: "Concierge", to: "Buyer", what: `recommend ${winner.name}`,
    body: () => `<div class="boundary info">What the buyer sees: one vetted pick and why.</div>
      <div class="code">${json({ seller: winner.name, product: winner.productName, price: winner.price, trustScore: winner.audit.trustScore, fitScore: winner.audit.fitScore, rejected: blocked.length })}</div>`,
  });
  await send(E.b2c, "req", 900, gen, true);
  pulse($("buyerNode"));
  $("buyerState").textContent = "approved purchase"; $("buyerState").className = "node-state done";

  // 8. checkout with the winning seller only
  setPhase("6 · checkout");
  const constraints = [...new Set(winner.audit.subAgents.flatMap(r => r.requiredConstraints || []))];
  edgeClass("buy", "buy");
  logEvent({
    kind: "buy", step: "checkout", from: "Concierge", to: winner.name, what: "checkout",
    body: () => `<div class="boundary buy">Payment goes only to the seller that passed every check.</div>
      <div class="code">${json({ seller: winner.name, product: winner.productName, amount: winner.price, currency: winner.priceCurrency, paymentHandler: winner.paymentHandler, constraints })}</div>`,
  });
  await send(E.buy, "buy", 1300, gen);
  $("lane-" + winner.sellerId).classList.add("chosen");
  $("mstate-" + winner.sellerId).innerHTML = `<span style="color:var(--safe)">order placed</span>`;
  t.sellers.forEach(s => { if (s.sellerId !== winner.sellerId) state.edges["c2s-" + s.sellerId].classList.add("dim"); });

  const correct = t.sellers.filter(s => s.groundTruth.dirty === (s.audit.overallDecision !== "allow")).length;
  state.kpi.decision = `${winner.name} · ${money(winner.price)}`;
  state.kpi.accuracy = `${correct}/${t.sellers.length} verdicts match hidden labels`;
  renderKpis();
  setPhase("done");
}

async function runLane(s, i, gen, onReport) {
  const t = state.trace, id = s.sellerId, a = s.audit;
  const scout = $("scout-" + id), sstate = $("sstate-" + id), mstate = $("mstate-" + id);
  const fs = findings(s), flagged = fs.length > 0;
  await sleep(i * 110, gen);

  // dispatch
  edgeClass("c2s-" + id, "req");
  logEvent({
    kind: "req", step: "dispatch", sellerId: id, from: "Concierge", to: `Scout·${s.name}`, what: "spawn scout",
    body: () => `<div class="boundary info">A fresh scout with an empty context. It will only ever see ${esc(s.name)}.</div>
      <div class="code">${json({ task: "audit_seller", sellerId: id, seller: s.name, checks: t.checks.map(c => c.id) })}</div>`,
  });
  await send(state.edges["c2s-" + id], "req", 700, gen);
  sstate.textContent = "fetching seller pages";

  // fetch
  logEvent({
    kind: "raw", step: "fetch", sellerId: id, from: `Scout·${s.name}`, to: s.name, what: "GET product + policy",
    body: () => `<div class="code">GET ${esc(s.productUrl)}\nGET ${esc(s.providerUrl)}/ucp.json</div>`,
  });
  await send(state.edges["s2m-" + id], "raw", 550, gen);
  mstate.textContent = "serving pages";

  // raw content back (stays in the scout's context)
  const top = topFinding(s);
  const evs = fs.map(f => f.evidence);
  logEvent({
    kind: flagged ? "bad" : "raw", step: "raw", sellerId: id, from: s.name, to: `Scout·${s.name}`,
    what: `raw content · ${rawChars(s).toLocaleString()} chars`, flag: flagged ? `⚠ ${checkLabel(top.agent)}` : "",
    body: () => `<div class="boundary held">Held inside Scout·${esc(s.name)}'s context. Never forwarded to the concierge or any other scout.</div>
      ${fs.map(f => `<div class="finding"><span class="sev">${esc(f.severity)}</span>${esc(checkLabel(f.agent))} · <span class="muted">${esc(f.sourcePath)}</span>
        <div>${esc(plainReason(f.reason))}</div><div class="ctl">Control: ${esc(f.recommendedControl)}</div></div>`).join("")}
      <div class="f-label">Description</div><div class="code">${highlight(s.description, evs)}</div>
      <div class="f-label">Return policy</div><div class="code">${highlight(s.returnPolicy, evs)}</div>
      <div class="f-label">Payment handler</div><div class="code">${highlight(JSON.stringify(s.paymentHandler), evs)}</div>`,
  });
  await send(state.edges["s2m-" + id], flagged ? "bad" : "raw", 850, gen, true);
  if (flagged) edgeClass("s2m-" + id, "bad");
  state.kpi.held = (state.kpi.held || 0) + rawChars(s);
  renderKpis();
  mstate.textContent = "done";

  // audit: light up the 4 checks
  sstate.textContent = "running checks";
  for (const ck of scout.querySelectorAll(".ck")) {
    await sleep(140, gen);
    const r = a.subAgents.find(x => x.agent === ck.dataset.check);
    ck.className = "ck " + (!r || !r.detected ? "pass" : (r.riskLevel === "low" || r.riskLevel === "medium" ? "warn" : "hit"));
  }
  scout.querySelector(".node-title").innerHTML = `Scout ${pill(a.overallDecision)}`;
  sstate.textContent = `trust ${Math.round(a.trustScore)} · fit ${Math.round(a.fitScore)}`;
  if (!isOk(s)) {
    $("lane-" + id).classList.add("contained");
    const note = $("note-" + id);
    note.textContent = `${checkLabel(top ? top.agent : "")} contained`;
    note.classList.remove("hidden");
    state.kpi.contained = (state.kpi.contained || 0) + 1;
  }
  state.kpi.findings = (state.kpi.findings || 0) + fs.length;

  // structured report crosses the boundary
  logEvent({
    kind: "json", step: "report", sellerId: id, from: `Scout·${s.name}`, to: "Concierge", what: `report · ${a.overallDecision.replace(/_/g, " ")}`,
    body: () => `<div class="boundary ok">Crosses the context boundary as structured fields only. No seller-written text inside.</div>
      <div class="code">${json({ sellerId: id, seller: s.name, price: s.price, decision: a.overallDecision, trustScore: a.trustScore, fitScore: a.fitScore, checks: a.finalJson })}</div>`,
  });
  edgeClass("c2s-" + id, isOk(s) ? "json" : "bad");
  await send(state.edges["c2s-" + id], "json", 800, gen, true);
  pulse($("conciergeNode"));
  onReport();
}

// ---------- wire-up ----------
$("playBtn").onclick = () => {
  state.paused = !state.paused;
  $("playBtn").textContent = state.paused ? "▶" : "❚❚";
};
$("replayBtn").onclick = () => { state.paused = false; $("playBtn").textContent = "❚❚"; play(); };
$("speedSel").onchange = (e) => { state.speed = Number(e.target.value); };
$("storesSel").onchange = () => loadTrace(false);
$("truthToggle").onchange = (e) => { $("canvas").classList.toggle("show-truth", e.target.checked); layoutEdges(); };
window.addEventListener("resize", () => { clearTimeout(window._rt); window._rt = setTimeout(layoutEdges, 100); });

loadTrace();
