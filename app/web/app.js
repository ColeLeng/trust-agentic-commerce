"use strict";

const $ = (id) => document.getElementById(id);
const state = { trace: null };

const COLOR_VAR = { green: "--green", lime: "--lime", amber: "--amber", orange: "--orange", red: "--red" };
const CHECK_ICON = { syringe: "⚠", "credit-card": "▣", store: "◫", rotate: "↺" };

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

// wrap any finding-evidence excerpts found in `text` with <mark> (operates on escaped text)
function highlight(text, evidences) {
  let out = esc(text);
  for (const ev of evidences || []) {
    const needle = esc(ev).trim();
    if (needle.length < 4) continue;
    if (out.includes(needle)) out = out.split(needle).join(`<mark>${needle}</mark>`);
  }
  return out;
}

async function loadTrace({ fresh = false, spin = false } = {}) {
  const stores = $("storesSel").value;
  if (spin) $("rerunBtn").classList.add("busy");
  $("loading").classList.remove("hidden");
  try {
    const res = await fetch(`/api/run?stores=${stores}&fresh=${fresh ? 1 : 0}`);
    const trace = await res.json();
    if (trace.error) { alert("Pipeline error: " + trace.error); return; }
    state.trace = trace;
    renderAll(trace);
  } catch (e) {
    console.error(e); alert("Failed to load: " + e.message);
  } finally {
    $("loading").classList.add("hidden");
    $("rerunBtn").classList.remove("busy");
  }
}

function renderAll(t) {
  renderBadges(t);
  renderBuyer(t);
  renderPlanner(t);
  renderSellers(t);
  renderConcierge(t);
  renderTruth(t);
  requestAnimationFrame(() => requestAnimationFrame(drawEdges));
}

function renderBadges(t) {
  const m = $("modeBadge");
  m.textContent = t.usedRealAgents ? "REAL AGENTS" : "MOCK";
  m.className = "badge " + (t.usedRealAgents ? "real" : "mock");
  const w = $("weaveBadge");
  if (t.weaveActive && t.weaveUrl) { w.href = t.weaveUrl; w.classList.remove("hidden"); }
  else w.classList.add("hidden");
}

function renderBuyer(t) {
  const b = t.buyer, c = b.personalContext;
  const initials = (b.name || "B").split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
  $("buyerPanel").innerHTML = `
    <h3>The buyer</h3>
    <div class="buyer-card">
      <div class="avatar">${esc(initials)}</div>
      <div>
        <div class="buyer-name">${esc(b.name)}</div>
        <div class="buyer-vertical">${esc(b.vertical)}</div>
      </div>
    </div>
    <div class="question">“${esc(b.question)}”</div>
    <div class="ctx-block">
      <div class="ctx-label">Budget</div>
      <div class="budget">$${Number(c.budget).toFixed(0)}</div>
    </div>
    <div class="ctx-block">
      <div class="ctx-label">Priorities</div>
      <div class="chips">${(c.priorities || []).map(p => `<span class="chip">${esc(p)}</span>`).join("")}</div>
    </div>
    <div class="ctx-block">
      <div class="ctx-label">Must-haves</div>
      <div class="chips">${(c.mustHaves || []).map(p => `<span class="chip must">${esc(p)}</span>`).join("")}</div>
    </div>
    <div class="ctx-block">
      <div class="ctx-label">Notes</div>
      <div class="notes">${esc(c.notes)}</div>
    </div>
    <div class="legend">
      <div class="ctx-label">Trust scale</div>
      ${["green", "lime", "amber", "orange", "red"].map(c2 =>
        `<div class="legend-row"><span class="swatch" style="background:var(${COLOR_VAR[c2]})"></span>${c2}</div>`).join("")}
    </div>`;
}

function renderPlanner(t) {
  const p = t.planner;
  $("plannerNode").innerHTML = `
    <div class="planner-top">
      <div class="planner-ic">◇</div>
      <div class="planner-title">Planner agent
        <small>· dispatches the scouts (fan-out)</small>
      </div>
    </div>
    <div class="planner-why">${esc(p.note)} Each scout sees only its own seller — contamination can't cross context boundaries.</div>`;
}

function renderConcierge(t) {
  const c = t.concierge;
  const winner = t.sellers.find(s => s.sellerId === c.winnerSellerId);
  $("conciergeNode").innerHTML = `
    <div class="planner-top">
      <div class="planner-ic" style="background:#1d3a2c;color:var(--green)">♚</div>
      <div class="planner-title">Concierge agent
        <small>· consumes ${t.sellers.length} scout reports → final decision</small>
      </div>
    </div>
    <div class="planner-why">${winner ? `Buys from <span class="planner-winner">${esc(winner.name)}</span>. ` : ""}${esc(c.why)}</div>`;
}

function sellerCheckSeverity(seller, checkId) {
  const r = (seller.audit.subAgents || []).find(a => a.agent === checkId);
  if (!r || !r.detected) return "pass";
  return r.riskLevel; // low|medium|high|critical
}

function renderSellers(t) {
  const grid = $("sellerGrid");
  const winnerId = t.concierge.winnerSellerId;
  // concierge ranking order
  const order = t.concierge.ranking || t.sellers.map(s => s.sellerId);
  const byId = Object.fromEntries(t.sellers.map(s => [s.sellerId, s]));
  grid.innerHTML = order.map(id => byId[id]).filter(Boolean).map(s => {
    const a = s.audit;
    const color = cssVar(COLOR_VAR[a.color] || "--line-2");
    const isWinner = s.sellerId === winnerId;
    const blocked = a.overallDecision === "block";
    const anomaly = s.price < 0.6 * s.marketReference;
    const checks = t.checks.map(c => {
      const sev = sellerCheckSeverity(s, c.id);
      const cls = sev === "pass" ? "pass" : (sev === "low" ? "medium" : sev);
      const ic = sev === "pass" ? "✓" : "✕";
      return `<div class="check-cell ${cls}" title="${esc(c.label)}: ${sev}">
        <div class="ck-ic">${ic}</div><div class="ck-lbl">${esc(c.label.split(" ")[0])}</div></div>`;
    }).join("");
    return `
    <div class="seller ${isWinner ? "winner" : ""} ${blocked ? "blocked" : ""}" data-id="${s.sellerId}" style="--c:${color}">
      <div class="seller-top">
        <div>
          <div class="seller-name">${isWinner ? '<span class="crown">♚</span> ' : ""}${esc(s.name)}</div>
          <div class="seller-id">${esc(s.sellerId)}</div>
        </div>
        <span class="decision d-${a.overallDecision}">${a.overallDecision.replace(/_/g, " ")}</span>
      </div>
      <div class="seller-price ${anomaly ? "price-anomaly" : ""}">$${Number(s.price).toFixed(2)}
        <small>/ mkt $${Number(s.marketReference).toFixed(0)}</small></div>
      <div class="seller-domain">${esc(s.domain)}</div>
      ${meter("Trust", a.trustScore, color)}
      ${meter("Fit", a.fitScore, cssVar("--accent"))}
      <div class="checks-row">${checks}</div>
    </div>`;
  }).join("");
  grid.querySelectorAll(".seller").forEach(el =>
    el.addEventListener("click", () => openDrawer(byId[el.dataset.id])));
}

function meter(label, val, color) {
  const v = Math.max(0, Math.min(100, Number(val)));
  return `<div class="meter">
    <div class="meter-label"><span>${label}</span><span>${v.toFixed(0)}</span></div>
    <div class="meter-track"><div class="meter-fill" style="width:${v}%;background:${color}"></div></div>
  </div>`;
}

function renderTruth(t) {
  const sb = t.scoreboard;
  const winnerOk = sb.winnerIsClean;
  $("truthPanel").innerHTML = `
    <h3>Ground truth & scoreboard</h3>
    <div class="verdict ${winnerOk ? "ok" : "bad"}">
      ${winnerOk ? "✓ Concierge bought from a clean seller" : "✗ Concierge picked a contaminated seller"}
    </div>
    <div class="score-grid">
      <div class="score-cell"><div class="score-num" style="color:var(--green)">${(sb.recall*100).toFixed(0)}%</div><div class="score-cap">attacks caught</div></div>
      <div class="score-cell"><div class="score-num" style="color:var(--accent)">${(sb.precision*100).toFixed(0)}%</div><div class="score-cap">precision</div></div>
      <div class="score-cell"><div class="score-num">${sb.nDirty}</div><div class="score-cap">dirty sellers</div></div>
      <div class="score-cell"><div class="score-num">${sb.nClean}</div><div class="score-cap">clean sellers</div></div>
    </div>
    <div class="ctx-label" style="margin-bottom:6px">Hidden labels (never seen by agents)</div>
    ${t.sellers.map(s => {
      const dirty = s.groundTruth.dirty;
      const flagged = s.audit.overallDecision !== "allow";
      const correct = dirty === flagged;
      return `<div class="truth-row">
        <span style="display:flex;align-items:center;gap:7px">
          <span class="truth-dot ${dirty ? "truth-dirty" : "truth-clean"}"></span>${esc(s.name)}
        </span>
        <span class="${correct ? "tag-match" : "tag-miss"}" title="${esc(s.groundTruth.attacks.join(", ") || "clean")}">
          ${dirty ? "✕ " + s.groundTruth.attacks.length + " atk" : "✓ clean"}
        </span>
      </div>`;
    }).join("")}`;
}

function drawEdges() {
  const svg = $("edges");
  const flow = $("flow");
  const planner = $("plannerNode");
  if (!svg || !planner) return;
  const fr = flow.getBoundingClientRect();
  svg.setAttribute("width", fr.width);
  svg.setAttribute("height", fr.height);
  svg.setAttribute("viewBox", `0 0 ${fr.width} ${fr.height}`);
  const pr = planner.getBoundingClientRect();
  const x0 = pr.left + pr.width / 2 - fr.left;
  const y0 = pr.bottom - fr.top;
  const winnerId = state.trace ? state.trace.concierge.winnerSellerId : null;
  let paths = "";
  document.querySelectorAll(".seller").forEach(card => {
    const cr = card.getBoundingClientRect();
    const x1 = cr.left + cr.width / 2 - fr.left;
    const y1 = cr.top - fr.top;
    const id = card.dataset.id;
    const seller = state.trace.sellers.find(s => s.sellerId === id);
    const color = cssVar(COLOR_VAR[seller.audit.color] || "--line-2");
    const win = id === winnerId;
    const my = (y0 + y1) / 2;
    paths += `<path class="edge ${win ? "edge-dash" : ""}" d="M ${x0} ${y0} C ${x0} ${my}, ${x1} ${my}, ${x1} ${y1}"
      stroke="${color}" style="opacity:${win ? .9 : .4}; stroke-width:${win ? 2.4 : 1.6}"/>`;
  });
  // winner card -> concierge node (the purchase decision)
  const concierge = $("conciergeNode");
  if (winnerId && concierge) {
    const wc = document.querySelector(`.seller[data-id="${winnerId}"]`);
    if (wc) {
      const wr = wc.getBoundingClientRect();
      const cr = concierge.getBoundingClientRect();
      const wx = wr.left + wr.width / 2 - fr.left, wy = wr.bottom - fr.top;
      const cx = cr.left + cr.width / 2 - fr.left, cy = cr.top - fr.top;
      const my = (wy + cy) / 2;
      const g = cssVar("--green");
      paths += `<path class="edge edge-dash" d="M ${wx} ${wy} C ${wx} ${my}, ${cx} ${my}, ${cx} ${cy}"
        stroke="${g}" style="opacity:.9;stroke-width:2.4"/>`;
    }
  }
  svg.innerHTML = paths;
}

// ---------- drawer ----------
function fieldForPath(path) {
  if (path.includes("description")) return "description";
  if (path.includes("policies.return")) return "returnPolicy";
  if (path.includes("payment")) return "paymentHandler";
  if (path.includes("offers.price")) return "price";
  if (path.includes("provider.url")) return "providerUrl";
  if (path.includes("supportChannel") || path.includes("identity")) return "identity";
  if (path.includes("image")) return "imageUrl";
  return "other";
}

function openDrawer(seller) {
  const t = state.trace;
  const a = seller.audit;
  const decClass = "d-" + a.overallDecision;
  const subHtml = a.subAgents.map(r => {
    const meta = t.checks.find(c => c.id === r.agent) || {};
    const head = `<div class="sa-head">
      <div>
        <div class="sa-name">${esc(meta.label || r.agent)}</div>
        <div class="sa-q">${esc(meta.question || "")}</div>
      </div>
      <span class="decision ${"d-" + r.decision}">${r.decision.replace(/_/g, " ")}</span>
    </div>`;
    if (!r.findings.length) return `<div class="subagent">${head}<div class="sa-clean">✓ no material signal — “good”</div></div>`;
    const findings = r.findings.map(f => `
      <div class="finding">
        <div class="finding-top">
          <span class="sev ${f.severity}">${f.severity}</span>
          <span class="loc">${esc(f.sourceFile)} · ${esc(f.sourcePath)}</span>
        </div>
        <div class="evidence">${highlight(f.evidence, [f.evidence])}</div>
        <div class="finding-reason">${esc(f.reason)}</div>
        <div class="finding-control">${esc(f.recommendedControl)}</div>
      </div>`).join("");
    const constraints = r.requiredConstraints.length
      ? `<div class="finding"><div class="constraints">${r.requiredConstraints.map(c => `<span class="constraint">${esc(c)}</span>`).join("")}</div></div>`
      : "";
    return `<div class="subagent">${head}${findings}${constraints}</div>`;
  }).join("");

  // consumed context with offending spans highlighted
  const evByField = {};
  a.subAgents.forEach(r => r.findings.forEach(f => {
    const key = fieldForPath(f.sourcePath);
    (evByField[key] = evByField[key] || []).push(f.evidence);
  }));
  const ctx = `
    <div class="dr-section-title">Raw merchant context the scout ingested</div>
    <div class="kv">
      <dt>products.json · name</dt><dd>${esc(seller.productName)}</dd>
      <dt>offers.price</dt><dd>$${Number(seller.price).toFixed(2)} <span style="color:var(--txt-faint)">(market ~$${Number(seller.marketReference).toFixed(0)})</span></dd>
      <dt>provider.url</dt><dd>${esc(seller.providerUrl)} · domain age ${seller.domainAgeDays}d</dd>
      <dt>payment.handler</dt><dd>${highlight(JSON.stringify(seller.paymentHandler), evByField.paymentHandler)}</dd>
      <dt>identity.support</dt><dd>${seller.supportChannel ? esc(seller.supportChannel) : '<span style="color:var(--red)">(none)</span>'}</dd>
    </div>
    <div class="dr-section-title">products.json · description</div>
    <div class="context-block">${highlight(seller.description, evByField.description)}</div>
    <div class="dr-section-title">ucp.json · return policy</div>
    <div class="context-block">${highlight(seller.returnPolicy, evByField.returnPolicy)}</div>`;

  // fit breakdown
  const fit = a.fit;
  const fitHtml = `
    <div class="dr-section-title">Product fit vs personal context</div>
    <div class="kv">
      <dt>within budget</dt><dd>${fit.withinBudget ? '<span class="tag-match">✓ yes</span>' : '<span class="tag-miss">✗ over budget</span>'}</dd>
      <dt>priorities met</dt><dd class="tag-match">${(fit.prioritiesMet || []).map(esc).join(", ") || "—"}</dd>
      <dt>priorities missed</dt><dd class="tag-miss">${(fit.prioritiesMissed || []).map(esc).join(", ") || "—"}</dd>
      <dt>must-haves missed</dt><dd class="tag-miss">${(fit.mustHavesMissed || []).map(esc).join(", ") || "—"}</dd>
    </div>`;

  $("drawerPanel").innerHTML = `
    <button class="dr-close" id="drClose">×</button>
    <div class="dr-head">
      <div class="planner-ic" style="background:var(${COLOR_VAR[a.color]});color:#0a0c10">◫</div>
      <div>
        <div class="dr-title">${esc(seller.name)} <span class="decision ${decClass}">${a.overallDecision.replace(/_/g, " ")}</span></div>
      </div>
    </div>
    <div class="dr-sub">${esc(seller.productName)} · ${esc(seller.domain)} · trust ${a.trustScore}/100 · fit ${a.fitScore}/100</div>
    <div class="dr-summary ${a.overallDecision === "allow" ? "verdict ok" : "verdict bad"}">${esc(a.summary)}</div>
    <div class="dr-section-title">Scouting agent · 4 security sub-agents</div>
    ${subHtml}
    ${fitHtml}
    ${ctx}
    <div class="dr-section-title">Aggregated sub-agent output (final JSON)</div>
    <div class="context-block">${esc(JSON.stringify(a.finalJson, null, 2))}</div>`;
  $("drawer").classList.remove("hidden");
  $("drClose").addEventListener("click", closeDrawer);
}

function closeDrawer() { $("drawer").classList.add("hidden"); }

// ---------- wire-up ----------
$("rerunBtn").addEventListener("click", () => loadTrace({ fresh: true, spin: true }));
$("storesSel").addEventListener("change", () => loadTrace({ fresh: false }));
$("drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
window.addEventListener("resize", () => { clearTimeout(window._rt); window._rt = setTimeout(drawEdges, 120); });

loadTrace();
