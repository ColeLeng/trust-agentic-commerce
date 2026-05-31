"use strict";

const $ = (id) => document.getElementById(id);
const state = { trace: null };

const COLOR_VAR = { green: "--green", lime: "--lime", amber: "--amber", orange: "--orange", red: "--red" };

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
  const level = $("levelSel").value;
  if (spin) $("rerunBtn").classList.add("busy");
  $("loading").classList.remove("hidden");
  try {
    const res = await fetch(`/api/run?level=${level}&fresh=${fresh ? 1 : 0}`);
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
  m.textContent = t.usedRealAgents ? "LIVE CLAUDE" : "MOCK";
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
      <div class="ctx-label">Marketplace</div>
      <div class="notes">${b.nStores} sellers audited in isolation</div>
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
      <div class="planner-ic" style="background:#1d3a2c;color:var(--green)">♚</div>
      <div class="planner-title">Concierge agent
        <small>· the single blue master agent — dispatch phase</small>
      </div>
      <span class="role-tag dispatch">① dispatch · fan-out</span>
    </div>
    <div class="planner-why">${esc(p.note)} The master agent spawns one context-isolated scout per seller — a fake-review flood in one storefront can't pollute another's evaluation.</div>`;
}

function renderConcierge(t) {
  const c = t.concierge;
  const winner = t.sellers.find(s => s.sellerId === c.winnerSellerId);
  $("conciergeNode").innerHTML = `
    <div class="planner-top">
      <div class="planner-ic" style="background:#1d3a2c;color:var(--green)">♚</div>
      <div class="planner-title">Concierge agent
        <small>· same master agent — decision phase, adjudicates ${t.sellers.length} structured reports</small>
      </div>
      <span class="role-tag decide">② adjudicate · trust-gated checkout</span>
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
  const order = t.concierge.ranking && t.concierge.ranking.length
    ? t.concierge.ranking : t.sellers.map(s => s.sellerId);
  const byId = Object.fromEntries(t.sellers.map(s => [s.sellerId, s]));
  const budget = t.buyer.personalContext.budget;
  grid.innerHTML = order.map(id => byId[id]).filter(Boolean).map(s => {
    const a = s.audit;
    const color = cssVar(COLOR_VAR[a.color] || "--line-2");
    const isWinner = s.sellerId === winnerId;
    const blocked = a.overallDecision === "block";
    const overBudget = budget > 0 && s.price > budget;
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
          <div class="seller-id">${esc(s.category)} · ${esc(s.sellerId)}</div>
        </div>
        <span class="decision d-${a.overallDecision}">${a.overallDecision.replace(/_/g, " ")}</span>
      </div>
      <div class="seller-price ${overBudget ? "price-anomaly" : ""}">$${Number(s.price).toFixed(2)}
        <small>${overBudget ? "over budget" : "within budget"}</small></div>
      <div class="seller-domain">${s.reviewsTotal} reviews · ${s.reviewsVerified} verified${s.reviewsFake ? ` · <span style="color:var(--red)">${s.reviewsFake} planted fakes</span>` : ""}</div>
      ${meter("Trust", a.trustScore, color)}
      ${meter("Product", a.productScore, cssVar("--accent"))}
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
      <div class="score-cell"><div class="score-num" style="color:var(--green)">${(sb.recall*100).toFixed(0)}%</div><div class="score-cap">dirty caught</div></div>
      <div class="score-cell"><div class="score-num" style="color:var(--accent)">${(sb.precision*100).toFixed(0)}%</div><div class="score-cap">precision</div></div>
      <div class="score-cell"><div class="score-num">${sb.nDirty}</div><div class="score-cap">dirty sellers</div></div>
      <div class="score-cell"><div class="score-num">${sb.plantedFakesTotal}</div><div class="score-cap">planted fakes</div></div>
    </div>
    <div class="ctx-label" style="margin-bottom:6px">Hidden labels (never seen by scouts)</div>
    ${t.sellers.map(s => {
      const dirty = s.groundTruth.dirty;
      const flagged = s.audit.recommendation !== "safe";
      const correct = dirty === flagged;
      return `<div class="truth-row">
        <span style="display:flex;align-items:center;gap:7px">
          <span class="truth-dot ${dirty ? "truth-dirty" : "truth-clean"}"></span>${esc(s.name)}
        </span>
        <span class="${correct ? "tag-match" : "tag-miss"}" title="${dirty ? s.groundTruth.plantedFakes + " planted fake reviews" : "genuine reviews"}">
          ${dirty ? "✕ " + s.groundTruth.plantedFakes + " fakes" : "✓ clean"}
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
          <span class="loc">signal: ${esc(f.signal)} · ${esc(f.id)}</span>
        </div>
        <div class="evidence">${highlight(f.evidence, [f.evidence])}</div>
        <div class="finding-reason">${esc(f.reason)}</div>
      </div>`).join("");
    return `<div class="subagent">${head}${findings}</div>`;
  }).join("");

  // gather every evidence string so we can highlight the matching review text
  const allEvidence = [];
  a.subAgents.forEach(r => r.findings.forEach(f => allEvidence.push(f.evidence)));

  // consumed context = the reviews this isolated scout actually ingested
  const reviewsHtml = seller.reviews.map(rv => `
    <div class="review-row ${rv.isFake ? "review-fake" : ""}">
      <div class="review-meta">
        <span class="rv-stars">${"★".repeat(Math.round(rv.rating))}${"☆".repeat(5 - Math.round(rv.rating))}</span>
        <span class="rv-author">${esc(rv.author)}</span>
        <span class="rv-flag ${rv.verified ? "rv-verified" : "rv-unverified"}">${rv.verified ? "verified" : "unverified"}</span>
        ${rv.isFake ? '<span class="rv-flag rv-planted">planted fake</span>' : ""}
      </div>
      <div class="review-text">${highlight(rv.text, allEvidence)}</div>
    </div>`).join("");

  const ctx = `
    <div class="dr-section-title">Seller metadata the scout ingested</div>
    <div class="kv">
      <dt>store</dt><dd>${esc(seller.name)} · ${esc(seller.sellerId)}</dd>
      <dt>category</dt><dd>${esc(seller.category)}</dd>
      <dt>asin</dt><dd>${esc(seller.asin)}</dd>
      <dt>price</dt><dd>$${Number(seller.price).toFixed(2)}</dd>
      <dt>reviews</dt><dd>${seller.reviewsTotal} total · ${seller.reviewsVerified} verified</dd>
    </div>
    <div class="dr-section-title">Reviews ingested (isolated context · planted fakes highlighted)</div>
    <div class="reviews-block">${reviewsHtml}</div>`;

  // product fit
  const fit = a.fit;
  const fitHtml = `
    <div class="dr-section-title">Product fit vs personal context</div>
    <div class="kv">
      <dt>product score</dt><dd>${Number(fit.productScore).toFixed(0)}/100 <span style="color:var(--txt-faint)">(verified reviews only)</span></dd>
      <dt>within budget</dt><dd>${fit.withinBudget ? '<span class="tag-match">✓ yes</span>' : '<span class="tag-miss">✗ over budget</span>'}</dd>
    </div>`;

  $("drawerPanel").innerHTML = `
    <button class="dr-close" id="drClose">×</button>
    <div class="dr-head">
      <div class="planner-ic" style="background:var(${COLOR_VAR[a.color]});color:#0a0c10">◫</div>
      <div>
        <div class="dr-title">${esc(seller.name)} <span class="decision ${decClass}">${a.overallDecision.replace(/_/g, " ")}</span></div>
      </div>
    </div>
    <div class="dr-sub">${esc(seller.category)} · ${esc(seller.sellerId)} · trust ${a.trustScore}/100 · product ${a.productScore}/100 · ${a.recommendation}</div>
    <div class="dr-summary ${a.recommendation === "safe" ? "verdict ok" : "verdict bad"}">${esc(a.summary)}</div>
    <div class="dr-section-title">Scouting agent · 4 security sub-agents (run in isolation)</div>
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
$("levelSel").addEventListener("change", () => loadTrace({ fresh: false }));
$("drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
window.addEventListener("resize", () => { clearTimeout(window._rt); window._rt = setTimeout(drawEdges, 120); });

loadTrace();
