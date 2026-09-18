/* Darukaa.Earth front end.
 *
 * Motion model (Apple's fluid-interface guidance, translated to the web):
 *   - No CSS transitions/keyframes for anything a finger can touch. Everything gesture-driven is a
 *     spring integrated in rAF, so it can be grabbed and reversed mid-flight.
 *   - Springs are described by damping ratio + response (seconds), not duration.
 *   - Drags track 1:1 from the grab offset; release velocity is handed to the spring; the landing
 *     point is projected from momentum; boundaries rubber-band instead of stopping hard.
 *   - prefers-reduced-motion replaces springs with instant state changes.
 */

const rm = matchMedia("(prefers-reduced-motion: reduce)");
const reduced = () => rm.matches;

/* ──────────────────────────── spring engine ──────────────────────────── */

class Spring {
  /** @param {{damping?: number, response?: number, value?: number, onUpdate: (v: number) => void}} o */
  constructor(o) {
    this.zeta = o.damping ?? 1;          // 1 = critically damped (no overshoot)
    this.response = o.response ?? 0.4;   // seconds to reach target — not a duration
    this.value = o.value ?? 0;
    this.target = this.value;
    this.velocity = 0;
    this.onUpdate = o.onUpdate;
    this.running = false;
  }

  /** Re-target without losing the current value or velocity (interruption, reversal). */
  to(target, { velocity, damping, response } = {}) {
    this.target = target;
    if (velocity !== undefined) this.velocity = velocity;
    if (damping !== undefined) this.zeta = damping;
    if (response !== undefined) this.response = response;
    if (reduced()) {                      // gentle, non-vestibular equivalent: no travel
      this.velocity = 0;
      this.set(target);
      return;
    }
    if (!this.running) { this.running = true; loop.add(this); }
  }

  /** Set the live value (used while dragging, so animation always starts from what's on screen). */
  set(value) {
    this.value = value;
    this.onUpdate(value);
  }

  stop() { this.running = false; this.velocity = 0; loop.remove(this); }

  /** Detach from the loop but keep velocity — a grab mid-flight inherits the motion. */
  hold() { this.running = false; loop.remove(this); }

  step(dt) {
    const omega = (2 * Math.PI) / this.response;
    // sub-step so a long frame can't make the integration explode
    const steps = Math.max(1, Math.ceil(dt / 0.004));
    const h = dt / steps;
    for (let i = 0; i < steps; i++) {
      const a = -omega * omega * (this.value - this.target) - 2 * this.zeta * omega * this.velocity;
      this.velocity += a * h;
      this.value += this.velocity * h;
    }
    if (Math.abs(this.value - this.target) < 0.05 && Math.abs(this.velocity) < 0.5) {
      this.value = this.target;
      this.velocity = 0;
      this.onUpdate(this.value);
      this.running = false;
      return false;
    }
    this.onUpdate(this.value);
    return true;
  }
}

/** Single display-synced clock for every spring. */
const loop = {
  springs: new Set(),
  last: 0,
  add(s) { this.springs.add(s); if (this.springs.size === 1) { this.last = performance.now(); requestAnimationFrame(this.tick); } },
  remove(s) { this.springs.delete(s); },
  tick: (now) => {
    const dt = Math.min((now - loop.last) / 1000, 0.064);
    loop.last = now;
    for (const s of [...loop.springs]) if (!s.step(dt)) loop.springs.delete(s);
    if (loop.springs.size) requestAnimationFrame(loop.tick);
  },
};

/** Apple's momentum projection (exponential decay), not the v²/2a textbook form. */
const project = (velocity, decelerationRate = 0.998) =>
  ((velocity / 1000) * decelerationRate) / (1 - decelerationRate);

/** Progressive resistance past a boundary. */
const rubberband = (overshoot, dimension, c = 0.55) =>
  (overshoot * dimension * c) / (dimension + c * Math.abs(overshoot));

const nearest = (value, points) => points.reduce((a, b) => (Math.abs(b - value) < Math.abs(a - value) ? b : a));

/* ──────────────────────────── small helpers ──────────────────────────── */

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html !== undefined) n.innerHTML = html; return n; };
const pill = (text, tone = "") => `<span class="pill ${tone}">${esc(text)}</span>`;
const chip = (text) => `<span class="chip">${esc(text)}</span>`;
const nice = (s) => String(s ?? "").replace(/_/g, " ");
/** Older stored answers can predate a field; never let a missing list break a render. */
const arr = (x) => (Array.isArray(x) ? x : []);
/** Minimal inline markdown: **bold**, *italic*, `code`. */
const md = (s) => citations(esc(s)
  .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
  .replace(/(^|\s)\*(?!\s)([^*]+?)\*/g, "$1<em>$2</em>")
  .replace(/`([^`]+?)`/g, "<code>$1</code>"));

/** Inline [ev_x] citations become compact source marks, so prose stays readable. */
const citations = (html) => html.replace(
  /\[((?:ev|pdf)_[a-z0-9_]+(?:\s*,\s*(?:ev|pdf)_[a-z0-9_]+)*)\]/g,
  (_, group) => group.split(/\s*,\s*/).map((id) => `<span class="cite" title="${id}">${id.replace(/^(ev|pdf)_/, "")}</span>`).join(""));

const HORIZON = { short: "< 1 year", medium: "1–5 years", long: "> 5 years" };
const CONF_TONE = { high: "good", medium: "warn", low: "bad" };
const SEV_TONE = { 3: "bad", 2: "warn", 1: "info" };
const DIR = { increase: ["up", "▲"], decrease: ["down", "▼"], protect: ["keep", "◆"] };

/** Short, meaningful haptic — only on a commit, never decoratively. */
const tap = (ms = 8) => {
  if (navigator.userActivation && !navigator.userActivation.hasBeenActive) return;  // browsers block it anyway
  try { navigator.vibrate?.(ms); } catch { /* unsupported */ }
};

function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3200);
}

/* ──────────────────────────── bottom sheet ──────────────────────────── */

const sheet = {
  node: $("#sheet"),
  scrim: $("#scrim"),
  body: $("#sheet-body"),
  title: $("#sheet-title"),
  height: 0,
  snaps: [0],
  open: false,

  init() {
    this.spring = new Spring({
      damping: 0.8, response: 0.3,      // Apple's drawer values
      onUpdate: (y) => this.paint(y),
    });
    $("#sheet-close").addEventListener("click", () => this.close());
    this.scrim.addEventListener("click", () => this.close());
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && this.open) this.close(); });

    // Drag from the grabber/header always; from the body only when it is scrolled to the top.
    for (const handle of [$("#sheet-grab"), $(".sheet-head")]) this.bindDrag(handle, false);
    this.bindDrag(this.body, true);
    addEventListener("resize", () => { if (this.open) this.measure(); });
  },

  measure() {
    this.height = this.node.offsetHeight;
    const peek = this.height * 0.45;
    this.snaps = this.height > innerHeight * 0.6 ? [0, peek, this.height] : [0, this.height];
  },

  paint(y) {
    const progress = this.height ? 1 - Math.min(Math.max(y / this.height, 0), 1) : 0;
    this.node.style.transform = `translate3d(0, ${y}px, 0)`;
    this.scrim.style.opacity = String(progress * 0.9);
    // depth: push the app shell back a little while a modal surface is up
    document.documentElement.style.setProperty("--sp", reduced() ? "0" : String(progress));
  },

  show(title, node) {
    this.title.textContent = title;
    this.body.replaceChildren(node);
    this.body.scrollTop = 0;
    this.node.hidden = false;
    this.scrim.hidden = false;
    this.measure();
    if (!this.open) { this.spring.set(this.height); }
    this.open = true;
    this.spring.to(0, { damping: 0.8, response: 0.3 });
    $("#sheet-close").focus({ preventScroll: true });
  },

  close(velocity = 0) {
    if (!this.open) return;
    this.open = false;
    if (reduced()) { this.paint(this.height); this.finishClose(); return; }
    this.spring.to(this.height, { velocity, damping: 1, response: 0.3 });
    clearTimeout(this._closeTimer);
    this._closeTimer = setTimeout(() => { if (!this.open) this.finishClose(); }, 520);
  },

  finishClose() {
    this.node.hidden = true;
    this.scrim.hidden = true;
    this.spring.stop();
    document.documentElement.style.setProperty("--sp", "0");
  },

  bindDrag(handle, isBody) {
    let dragging = false, startY = 0, startValue = 0, history = [];

    handle.addEventListener("pointerdown", (e) => {
      if (isBody && this.body.scrollTop > 0) return;       // let the content scroll first
      if (e.target.closest("button, a, input, textarea, summary")) return;
      dragging = true;
      handle.setPointerCapture(e.pointerId);
      this.spring.hold();                                   // grab mid-flight, keep the live value
      startY = e.clientY;
      startValue = this.spring.value;                       // respect where they grabbed it
      history = [{ t: performance.now(), y: e.clientY }];
    });

    handle.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const raw = startValue + (e.clientY - startY);
      if (isBody && raw < 0) return;                        // dragging up inside the body = scroll
      // 1:1 with the finger, with progressive resistance past the open position
      const y = raw < 0 ? -rubberband(-raw, this.height || innerHeight) : raw;
      this.spring.set(y);
      history.push({ t: performance.now(), y: e.clientY });
      if (history.length > 6) history.shift();
      e.preventDefault();
    }, { passive: false });

    const end = (e) => {
      if (!dragging) return;
      dragging = false;
      const now = performance.now();
      const old = history.find((p) => now - p.t < 120) ?? history[0];
      const dt = Math.max((now - old.t) / 1000, 0.001);
      const velocity = (e.clientY - old.y) / dt;            // px/s at release
      // animate to where the gesture was going, not where it stopped
      const projected = this.spring.value + project(velocity);
      const target = nearest(projected, this.snaps);
      if (target >= this.height) { this.close(velocity); tap(6); return; }
      // bounce is justified here: the gesture itself carried momentum
      this.spring.to(target, { velocity, damping: 0.8, response: 0.3 });
      tap(5);
    };
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  },
};

/* ──────────────────────────── API ──────────────────────────── */

const api = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  async del(path) {
    const r = await fetch(path, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      throw new Error(detail.detail || `${r.status} ${r.statusText}`);
    }
    return r.json();
  },
};

const store = {
  get session() { return localStorage.getItem("darukaa.session") || null; },
  set session(id) { if (id) localStorage.setItem("darukaa.session", id); },
  get previous() { return localStorage.getItem("darukaa.previous") || null; },
  /** Park the id instead of deleting it: a refresh starts fresh, but the work is still reachable. */
  park() {
    const id = this.session;
    if (id) localStorage.setItem("darukaa.previous", id);
    localStorage.removeItem("darukaa.session");
  },
  clear() { localStorage.removeItem("darukaa.session"); localStorage.removeItem("darukaa.previous"); },
};

function startNew() {
  store.park();
  location.href = location.pathname;   // fresh page, no query flags
}

function openSession(id) {
  localStorage.setItem("darukaa.session", id);
  location.href = `${location.pathname}?session=${encodeURIComponent(id)}`;
}

/** "3 minutes ago" / "yesterday" — history is easier to scan by recency than by timestamp. */
function ago(iso) {
  const then = new Date((iso || "").replace(" ", "T") + "Z");
  const mins = Math.max(0, Math.round((Date.now() - then.getTime()) / 60000));
  if (!isFinite(mins)) return "";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/* ──────────────────────────── renderers ──────────────────────────── */

function renderUser(text) {
  const node = el("div", "bubble-user");
  node.innerHTML = md(text).replace(/```json\n?([\s\S]*?)```/g, (_, code) => `<code>${code.trim()}</code>`);
  return node;
}

function metricsList(rec) {
  const wrap = el("div");
  for (const m of arr(rec.impacted_metrics)) {
    const [cls, glyph] = DIR[m.direction];
    wrap.append(el("div", "mx", `<div class="dir ${cls}">${glyph}</div>
      <div><b>${esc(nice(m.metric))}</b><div class="est">${esc(m.estimate)}</div>
      <div>${pill(m.horizon + "-term", "info")}${chip(m.source_id)}</div></div>`));
  }
  return wrap;
}

function recommendationDetail(rec) {
  const wrap = el("div");
  const head = [pill(`${rec.confidence} confidence · ${rec.confidence_score}`, CONF_TONE[rec.confidence]),
    pill(`${rec.time_horizon}-term · ${HORIZON[rec.time_horizon]}`, "info"),
    rec.prerequisite ? pill("prerequisite", "warn") : "",
    rec.screening ? pill("screening-level", "warn") : ""].join("");
  wrap.append(el("div", "meta-row", head));
  wrap.append(el("div", "", `<h4>What to do</h4><p>${md(rec.what_to_do)}</p>`));
  wrap.append(el("div", "", `<h4>Why it works</h4><p>${md(rec.why_it_works)}</p>`));
  if (rec.site_specific_reasoning) {
    wrap.append(el("div", "", `<h4>Why for your site</h4><p>${md(rec.site_specific_reasoning)}</p>`));
  }
  for (const a of arr(rec.adaptations)) wrap.append(el("div", "note info", `🧭 ${esc(a)}`));
  if (arr(rec.tradeoffs).length) wrap.append(el("div", "note warn", `⚖️ ${esc(arr(rec.tradeoffs).join(" "))}`));

  if (arr(rec.projections).length) {
    wrap.append(el("h4", "", "Projected for your site"));
    const rows = el("div", "rows");
    for (const pr of arr(rec.projections)) {
      rows.append(el("div", "row", `<b>${esc(nice(pr.metric))}</b>
        <div class="t"><b>${pr.baseline}</b> → <b>${pr.low}–${pr.high}</b> ${esc(pr.unit)} over ${pr.years} years
        (${pr.change_low > 0 ? "+" : ""}${pr.change_low} to ${pr.change_high > 0 ? "+" : ""}${pr.change_high})</div>
        <div class="t">${esc(pr.method)} ${chip(pr.evidence_id)}</div>`));
    }
    wrap.append(rows);
    wrap.append(el("p", "small", "Evidence applied to your measured baseline — an estimate, not a prediction. Assumes: "
      + esc(arr(arr(rec.projections)[0].assumptions).join("; "))));
  }

  wrap.append(el("h4", "", "Impacted metrics"));
  wrap.append(metricsList(rec));

  if (arr(rec.monitoring).length) {
    wrap.append(el("h4", "", "How to verify it is working"));
    const rows = el("div", "rows");
    for (const m of arr(rec.monitoring)) {
      rows.append(el("div", "row", `<b>${esc(m.indicator)}</b><div class="t">${esc(m.method)}</div>${pill(m.frequency)}`));
    }
    wrap.append(rows);
  }

  wrap.append(el("h4", "", "Evidence"));
  for (const ref of arr(rec.references)) {
    const link = ref.url ? ` · <a href="${esc(ref.url)}" target="_blank" rel="noopener">source</a>` : "";
    wrap.append(el("div", "ref", `<b>${esc(ref.citation)}</b>${link} ${pill("tier " + ref.tier)}
      <div class="x">${esc(ref.excerpt || "")}</div>`));
  }
  wrap.append(el("div", "meta-row", `${chip("addresses: " + arr(rec.addresses).join(", "))}
    ${chip("links: " + arr(rec.variables_linked).map(nice).join(", "))}`));
  wrap.append(el("p", "small", esc("Confidence basis: " + rec.confidence_reason)));
  return wrap;
}

function renderAssessment(r) {
  const wrap = el("div", "assistant");

  const summary = (r.message.split("\n\n**Diagnosis**")[0] || "").replace("### Assessment\n", "").trim();
  wrap.append(el("div", "meta-row", [
    r.llm_used ? pill("LLM-synthesised · verified", "good") : pill("deterministic reasoning"),
    pill(`${arr(r.known_variables).length} variables`, "info"),
    pill(`${arr(r.diagnosis).length} problems`, "bad"),
    pill(`${arr(r.recommendations).filter((x) => x.kind === "do").length} recommendations`, "good"),
  ].join("")));
  wrap.append(el("div", "card summary", md(summary)));

  if (arr(r.diagnosis).length) {
    wrap.append(el("h3", "", "Diagnosis"));
    const stack = el("div", "stack");
    for (const f of arr(r.diagnosis)) {
      stack.append(el("div", `dx ${SEV_TONE[f.severity] || ""}`,
        `<b>${esc(f.label)}</b><span>${esc(f.explanation)} ${chip(f.evidence_id || "")}</span>`));
    }
    wrap.append(stack);
  }

  if (arr(r.causal_chains).length) {
    wrap.append(el("h3", "", "How the variables interact"));
    const stack = el("div", "stack");
    for (const c of arr(r.causal_chains)) {
      const nodes = arr(c.path).map((v, i) =>
        `<span class="node${i === arr(c.path).length - 1 ? " end" : ""}">${esc(nice(v))}</span>`).join('<span class="arrow">→</span>');
      stack.append(el("div", "chain", nodes));
    }
    wrap.append(stack);
  }

  if (arr(r.recommendations).length) {
    wrap.append(el("h3", "", "Recommendations"));
    const stack = el("div", "stack");
    let n = 0;
    for (const rec of arr(r.recommendations)) {
      const avoid = rec.kind === "avoid";
      if (!avoid) n += 1;
      const card = el("button", `rec${avoid ? " avoid" : ""}`);
      card.type = "button";
      card.innerHTML = `<div class="rec-top"><div class="num">${avoid ? "✕" : n}</div>
          <div><h3>${esc(rec.title)}</h3>
          <div class="meta-row">${pill(`${rec.confidence} confidence`, CONF_TONE[rec.confidence])}
            ${pill(`${rec.time_horizon}-term`, "info")}
            ${rec.prerequisite ? pill("prerequisite", "warn") : ""}</div></div></div>
        ${arr(rec.projections).length ? `<div class="meta-row">${pill(
          `${nice(arr(rec.projections)[0].metric)}: ${arr(rec.projections)[0].baseline} → ${arr(rec.projections)[0].low}–${arr(rec.projections)[0].high} ${arr(rec.projections)[0].unit} in ${arr(rec.projections)[0].years}y`, "info")}</div>` : ""}
        <div class="what">${esc(rec.what_to_do)}</div>
        <div class="more">Tap for mechanism, estimates, monitoring and ${arr(rec.references).length} references →</div>`;
      card.addEventListener("click", () => sheet.show(rec.title, recommendationDetail(rec)));
      stack.append(card);
    }
    wrap.append(stack);
  }

  if (arr(r.action_plan).length) {
    wrap.append(el("h3", "", "Action plan"));
    const plan = el("div", "plan");
    for (const ph of arr(r.action_plan)) {
      const [num, name] = ph.phase.split(" · ");
      plan.append(el("div", "phase", `<div class="dot">${esc(num)}</div>
        <div><b>${esc(name || ph.phase)}</b><div class="win">${esc(ph.window)}</div>
        <ul>${arr(ph.actions).map((a) => `<li>${esc(a)}</li>`).join("")}</ul>
        ${arr(ph.monitor).length ? `<div class="mon">📏 ${esc(arr(ph.monitor).join("; "))}</div>` : ""}
        <div class="why">${esc(ph.rationale)}</div></div>`));
    }
    wrap.append(plan);
  }

  if (arr(r.assumptions).length) {
    wrap.append(fold(`Assumptions & data notes · ${arr(r.assumptions).length}`,
      `<div class="rows">${arr(r.assumptions).map((a) => `<div class="row"><div class="t">${esc(a)}</div></div>`).join("")}</div>`));
  }
  if (arr(r.clarifying_questions).length) {
    wrap.append(el("div", "note info",
      `💡 <b>To sharpen this advice</b><ul class="qlist">${arr(r.clarifying_questions).map((q) => `<li>${md(q)}</li>`).join("")}</ul>`));
  }
  wrap.append(traceFold(r));
  wrap.append(downloads(r));
  return wrap;
}

function fold(summaryText, innerHTML) {
  const d = el("details", "fold");
  d.innerHTML = `<summary>${esc(summaryText)}</summary>${innerHTML}`;
  return d;
}

function traceFold(r) {
  const hits = arr(r.retrieval).reduce((n, t) => n + arr(t.hits).length, 0);
  const lookups = arr(r.retrieval).reduce((n, t) => n + arr(t.structured_lookups).length, 0);
  const blocks = arr(r.retrieval).map((t) => `
    <div class="row"><b>query</b><div class="t">${esc(t.query.slice(0, 200))}</div>
      <div class="meta-row">${Object.entries(t.filters).map(([k, v]) => chip(`${k}: ${JSON.stringify(v)}`.slice(0, 70))).join("")}</div>
      ${arr(t.structured_lookups).map((s) => `<div class="t">🗂 ${esc(s)}</div>`).join("")}
      ${arr(t.hits).map((h) => `<div class="t">${chip(h.chunk_id)} ${chip("score " + h.score)} ${chip("dense #" + h.dense_rank)} ${chip("bm25 #" + h.sparse_rank)}<br>${esc(h.text.slice(0, 180))}…</div>`).join("")}
    </div>`).join("");
  const notes = arr(r.grounding_notes).length
    ? `<h4>Grounding verifier</h4><div class="rows">${arr(r.grounding_notes).map((n) => `<div class="row"><div class="t">${esc(n)}</div></div>`).join("")}</div>` : "";
  return fold(`Retrieval trace · ${hits} passages · ${lookups} structured lookups`, `<div class="rows">${blocks}</div>${notes}`);
}

function downloads(r) {
  const row = el("div", "meta-row");
  const mk = (label, text, name, type) => {
    const b = el("button", "btn", label);
    b.type = "button";
    b.addEventListener("click", () => {
      const url = URL.createObjectURL(new Blob([text], { type }));
      const a = Object.assign(document.createElement("a"), { href: url, download: name });
      a.click();
      URL.revokeObjectURL(url);
    });
    return b;
  };
  row.append(mk("⬇ Markdown report", r.message, "darukaa-assessment.md", "text/markdown"));
  row.append(mk("⬇ Structured JSON", JSON.stringify(r, null, 2), "darukaa-assessment.json", "application/json"));
  return row;
}

function renderClarification(r) {
  const wrap = el("div", "assistant");
  const intro = r.message.split("\n\n1.")[0];
  wrap.append(el("div", "card summary", md(intro)));
  if (arr(r.known_variables).length) {
    wrap.append(el("div", "meta-row", `<span class="small">Known so far:</span>` + arr(r.known_variables).map((v) => pill(nice(v), "good")).join("")));
  }
  const stack = el("div", "stack");
  arr(r.clarifying_questions).forEach((q, i) => stack.append(el("div", "q", `<div class="n">${i + 1}</div><p>${md(q)}</p>`)));
  wrap.append(stack);
  wrap.append(el("p", "small", "Answer what you know — or say “not sure, just recommend” and I will proceed with lower confidence."));
  return wrap;
}

function renderAnswer(r) {
  const wrap = el("div", "assistant");
  wrap.append(el("div", "card summary", md(r.message.split("\n\n**Sources:**")[0])));
  if (arr(r.references).length) {
    wrap.append(fold(`Sources · ${arr(r.references).length}`,
      arr(r.references).map((ref) => `<div class="ref"><b>${esc(ref.citation)}</b> ${chip(ref.evidence_id || "")}</div>`).join("")));
  }
  wrap.append(traceFold(r));
  return wrap;
}

const renderResponse = (r) =>
  r.type === "clarification" ? renderClarification(r) : r.type === "answer" ? renderAnswer(r) : renderAssessment(r);

/* ──────────────────────────── conversation ──────────────────────────── */

const thread = $("#thread");
let busy = false;

function appendNode(node) {
  thread.append(node);
  node.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "nearest" });
}

function thinking(on) {
  busy = on;
  $("#composer").classList.toggle("busy", on);
  $("#btn-send").disabled = on;
  let node = $("#thinking");
  if (on && !node) {
    node = el("div", "card thinking", '<i></i> Diagnosing, retrieving evidence and reasoning…');
    node.id = "thinking";
    appendNode(node);
    pulse(node.querySelector("i"));
  } else if (!on && node) {
    node.remove();
  }
}

/** A calm, slow spring pulse — no CSS keyframes, so it obeys reduced motion for free. */
function pulse(dot) {
  if (reduced()) return;
  const s = new Spring({ damping: 0.45, response: 0.55, value: 0.4, onUpdate: (v) => { dot.style.opacity = String(v); } });
  const bounce = () => {
    if (!dot.isConnected) return;
    s.to(s.target > 0.7 ? 0.35 : 1);
    setTimeout(bounce, 520);
  };
  bounce();
}

async function send(message, site) {
  if (busy) return;
  const shown = site ? `${message}\n\`\`\`json\n${JSON.stringify(site, null, 2)}\n\`\`\`` : message;
  appendNode(renderUser(shown.trim()));
  if (!$("#thread-title").textContent) setThreadTitle(message.trim() || "Site data");
  $("#examples").hidden = true;
  thinking(true);
  try {
    const out = await api.post("/chat", { message, site, session_id: store.session });
    store.session = out.session_id;
    thinking(false);
    appendNode(renderResponse(out.response));
    updateProfileStrip(out.response.profile, out.response.known_variables);
    tap(10);
  } catch (err) {
    thinking(false);
    toast(`Could not reach the engine: ${err.message}`);
  }
}

/** Show which conversation is open, so the history and the current thread stay connected. */
function setThreadTitle(text) {
  const node = $("#thread-title");
  if (!text) { node.hidden = true; return; }
  node.hidden = false;
  node.textContent = text.length > 54 ? text.slice(0, 54) + "…" : text;
  node.title = text;
}

function updateProfileStrip(profile, known) {
  const strip = $("#profile-strip");
  const entries = Object.entries(profile || {}).filter(([k]) => !["latitude", "longitude", "goal"].includes(k));
  if (!entries.length) { strip.hidden = true; return; }
  strip.hidden = false;
  strip.innerHTML = entries.map(([k, v]) =>
    pill(`${nice(k).replace(" pct", "")}: ${Array.isArray(v) ? v.join(", ") : v}`, (known || []).some((n) => k.startsWith(n)) ? "good" : "")).join("");
  strip.title = "Site profile built from this conversation";
}

/* ──────────────────────────── input sheets ──────────────────────────── */

function siteDataSheet() {
  const wrap = el("div");
  wrap.innerHTML = `
    <p class="small">Structured input. Exact field names or loose keys both work — the parser normalises them.</p>
    <label class="field">Site data (JSON)
      <textarea id="site-json" rows="9">${esc(JSON.stringify(
    { soil_organic_carbon: "0.3%", rainfall: "low", crop: "monoculture wheat", region: "semi-arid", species_richness_trend: "declining" }, null, 2))}</textarea>
    </label>`;
  const go = el("button", "btn primary", "Send site data");
  go.type = "button";
  go.addEventListener("click", () => {
    try {
      const site = JSON.parse($("#site-json").value);
      sheet.close();
      send("", site);
    } catch (e) { toast(`Invalid JSON: ${e.message}`); }
  });
  wrap.append(go);
  return wrap;
}

function locationSheet() {
  const wrap = el("div");
  wrap.innerHTML = `
    <p class="small">Coordinates are enriched from ISRIC SoilGrids (pH, soil carbon), Open-Meteo ERA5
      (rainfall, temperature, aridity → climate zone) and GBIF (recorded species). Looked-up values are
      labelled as such and never overwrite yours.</p>
    <label class="field">Latitude<input id="lat" type="number" step="0.0001" value="26.2400"></label>
    <label class="field">Longitude<input id="lon" type="number" step="0.0001" value="73.0200"></label>`;
  const row = el("div", "meta-row");
  const go = el("button", "btn primary", "Fetch site conditions");
  go.type = "button";
  go.addEventListener("click", () => {
    const lat = Number($("#lat").value), lon = Number($("#lon").value);
    sheet.close();
    send(`My land is at coordinates ${lat}, ${lon}`);
  });
  const here = el("button", "btn", "Use my location");
  here.type = "button";
  here.addEventListener("click", () => {
    if (!navigator.geolocation) return toast("This browser has no geolocation.");
    navigator.geolocation.getCurrentPosition(
      (p) => { $("#lat").value = p.coords.latitude.toFixed(4); $("#lon").value = p.coords.longitude.toFixed(4); },
      () => toast("Location permission denied."));
  });
  row.append(go, here);
  wrap.append(row);
  return wrap;
}

function profileSheet() {
  const wrap = el("div");
  const id = store.session;
  wrap.innerHTML = `<p class="small">This conversation: <code>${esc(id || "not started")}</code>. The site profile and
    every message are stored server-side in SQLite, so any conversation can be reopened later.</p>`;
  const row = el("div", "meta-row");
  const fresh = el("button", "btn", "＋ New conversation");
  fresh.type = "button";
  fresh.addEventListener("click", startNew);
  row.append(fresh);
  wrap.append(row);

  wrap.append(el("h4", "", "History"));
  const list = el("div", "stack");
  list.append(el("p", "small", "Loading…"));
  wrap.append(list);

  api.get("/sessions?limit=25").then((items) => {
    list.replaceChildren();
    if (!items.length) { list.append(el("p", "small", "No earlier conversations yet.")); return; }
    for (const item of items) {
      const card = el("div", "history" + (item.session_id === id ? " current" : ""));
      const vars = Object.entries(item.profile || {})
        .filter(([k]) => !["latitude", "longitude", "provenance", "goal", "region"].includes(k))
        .slice(0, 4).map(([k, v]) => pill(`${nice(k).replace(" pct", "")}: ${v}`)).join("");
      card.innerHTML = `<div class="h-main"><b>${esc(item.title)}</b>
        <div class="small">${esc(ago(item.updated_at))} · ${item.message_count} messages${item.session_id === id ? " · open" : ""}</div>
        <div class="meta-row">${vars}</div></div>`;
      const open = el("button", "btn", item.session_id === id ? "Reopen" : "Open");
      open.type = "button";
      open.addEventListener("click", () => openSession(item.session_id));
      const del = el("button", "icon-btn", "");
      del.type = "button";
      del.title = "Delete this conversation";
      del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 7h12M9 7V5h6v2M8 7l1 12h6l1-12"/></svg>';
      del.addEventListener("click", async () => {
        // Deleting a conversation is permanent and server-side: ask first.
        if (!confirm(`Delete this conversation permanently?

"${item.title}"
${item.message_count} messages, last active ${ago(item.updated_at)}.`)) return;
        try {
          await api.del(`/sessions/${item.session_id}`);
          card.remove();
          if (item.session_id === id) { store.clear(); location.href = location.pathname; }
        } catch (err) { toast(`Could not delete: ${err.message}`); }
      });
      const actions = el("div", "h-actions");
      actions.append(open, del);
      card.append(actions);
      list.append(card);
    }
  }).catch((err) => { list.replaceChildren(el("p", "small", `Could not load history: ${esc(err.message)}`)); });

  return wrap;
}

/* ──────────────────────────── views ──────────────────────────── */

const METHOD = [
  "<b>Parse</b> free text, JSON or coordinates into a typed site profile (rule parser first, LLM only for what the rules miss).",
  "<b>Remember</b> — merge into the session profile in SQLite, so values accumulate across turns.",
  "<b>Enrich</b> coordinates from SoilGrids, Open-Meteo ERA5 and GBIF, with provenance recorded.",
  "<b>Decide</b> — too few variables (or no land use) → targeted questions; a follow-up question → grounded answer; otherwise recommend.",
  "<b>Diagnose</b> against cited thresholds → issue codes such as very low soil carbon or water-limited.",
  "<b>Trace the knowledge graph</b> to show how those issues propagate to biodiversity.",
  "<b>Score practices</b> — each must address at least two diagnosed issues; water-consuming and contraindicated practices are excluded.",
  "<b>Retrieve</b> supporting passages with hybrid dense + BM25 search, boosted by domain metadata and evidence tier.",
  "<b>Synthesise</b> the site-specific explanation from retrieved evidence only, then <b>verify</b>: any sentence citing unknown evidence or an unsupported number is deleted.",
  "<b>Plan</b> — sequence into baseline → unblock → build → sustain, each phase with monitoring indicators.",
];

function switchView(name) {
  for (const b of document.querySelectorAll(".segmented button")) {
    b.setAttribute("aria-selected", String(b.dataset.view === name));
  }
  segIndicator.move(document.querySelector(`.segmented [data-view="${name}"]`));
  for (const v of ["consult", "knowledge", "method"]) $(`#view-${v}`).hidden = v !== name;
  $("#composer").style.display = name === "consult" ? "" : "none";
  $("#scroll").scrollTo?.({ top: 0 });
  scrollTo({ top: 0, behavior: reduced() ? "auto" : "smooth" });
  if (name === "knowledge" && !$("#kb-practices").childElementCount) loadPractices();
}

async function loadPractices() {
  try {
    const practices = await api.get("/knowledge/practices");
    const stack = $("#kb-practices");
    stack.replaceChildren();
    for (const p of practices) {
      const card = el("button", `rec${p.kind === "avoid" ? " avoid" : ""}`);
      card.type = "button";
      card.innerHTML = `<div class="rec-top"><div><h3>${esc(p.name)}</h3>
        <div class="meta-row">${pill(`${p.effects.length} effects`, "info")}${pill(`${arr(p.monitoring).length} indicators`)}
        ${Object.keys(p.addresses || {}).slice(0, 3).map(chip).join("")}</div></div></div>
        <div class="what">${esc(p.mechanism)}</div>`;
      card.addEventListener("click", () => {
        const detail = el("div");
        detail.innerHTML = `<h4>What to do</h4><p>${esc(p.action)}</p><h4>Mechanism</h4><p>${esc(p.mechanism)}</p>
          <h4>Effects</h4>${p.effects.map((e) => `<div class="mx"><div class="dir ${DIR[e.direction][0]}">${DIR[e.direction][1]}</div>
            <div><b>${esc(nice(e.metric))}</b><div class="est">${esc(e.estimate)}</div>${pill(e.horizon + "-term", "info")}${chip(e.evidence_id)}</div></div>`).join("")}
          <h4>Monitoring</h4><div class="rows">${arr(p.monitoring).map((m) => `<div class="row"><b>${esc(m.indicator)}</b><div class="t">${esc(m.method)}</div>${pill(m.frequency)}</div>`).join("")}</div>`;
        sheet.show(p.name, detail);
      });
      stack.append(card);
    }
  } catch (err) { toast(`Could not load practices: ${err.message}`); }
}

async function searchKnowledge() {
  const q = $("#kb-q").value.trim();
  if (!q) return;
  const out = $("#kb-results");
  out.replaceChildren(el("div", "card thinking", "<i></i> Searching…"));
  try {
    const hits = await api.get(`/knowledge/search?q=${encodeURIComponent(q)}&k=6`);
    out.replaceChildren();
    for (const h of hits) {
      out.append(el("div", "card plain", `<div class="meta-row">${chip(h.chunk_id)}${chip(h.source_id)}
        ${pill("score " + h.score, "info")}${pill("dense #" + h.dense_rank)}${pill("bm25 #" + h.sparse_rank)}</div>
        <p class="small" style="margin-top:.4rem">${esc(h.text)}</p>`));
    }
  } catch (err) { out.replaceChildren(); toast(`Search failed: ${err.message}`); }
}

/* ──────────────────────────── boot ──────────────────────────── */

const EXAMPLES = [
  ["Vague start", "Biodiversity is declining on my land"],
  ["Semi-arid wheat", "My 5 ha farm near Jodhpur grows only wheat, rainfall is about 350 mm, soil organic carbon is 0.3%"],
  ["Cleared forest", "We cleared part of a forest patch for maize; the remaining woodland is fragmented and we spray pesticides. Bees are fewer."],
  ["Acidic cotton", "Acidic soil, pH 4.8, humid climate, cotton monoculture with heavy fertilizer use"],
];

/** Tab indicator: separate springs for x and width, so a fast switch cannot desync the two axes,
 *  and both re-target from the live on-screen value. */
const segIndicator = {
  init() {
    const bar = $("#seg-indicator");
    this.x = new Spring({ damping: 1, response: 0.32, onUpdate: (v) => { bar.style.transform = `translate3d(${v}px,0,0)`; } });
    this.w = new Spring({ damping: 1, response: 0.32, onUpdate: (v) => { bar.style.width = `${v}px`; } });
    this.move(document.querySelector('.segmented [aria-selected="true"]'), true);
    addEventListener("resize", () => this.move(document.querySelector('.segmented [aria-selected="true"]'), true));
  },
  move(button, instant = false) {
    if (!button) return;
    const nav = button.parentElement.getBoundingClientRect();
    const box = button.getBoundingClientRect();
    const x = box.left - nav.left;
    const w = box.width;
    if (instant || reduced()) {
      this.x.set(x); this.x.target = x;
      this.w.set(w); this.w.target = w;
      return;
    }
    this.x.to(x);
    this.w.to(w);
  },
};

/** The header sheds its status line once content scrolls under it. Spring-driven, so reversing
 *  scroll direction mid-motion stays continuous instead of restarting a transition. */
function compactHeader() {
  const spring = new Spring({
    damping: 1, response: 0.35,
    onUpdate: (v) => document.documentElement.style.setProperty("--compact", String(v)),
  });
  let compact = false;
  addEventListener("scroll", () => {
    const want = scrollY > 40;
    if (want === compact) return;
    compact = want;
    spring.to(want ? 1 : 0);
    requestAnimationFrame(() => segIndicator.move(document.querySelector('.segmented [aria-selected="true"]'), true));
  }, { passive: true });
}

/** The chrome grows when the profile strip appears — keep content clear of it. */
function trackChromeHeight() {
  const chrome = $("#chrome");
  const apply = () => document.documentElement.style.setProperty("--chrome-h", `${chrome.offsetHeight}px`);
  apply();
  new ResizeObserver(apply).observe(chrome);
}

function boot() {
  sheet.init();
  trackChromeHeight();

  const list = $("#examples");
  for (const [label, text] of EXAMPLES) {
    const b = el("button", "example", `<b>${esc(label)}</b><span>${esc(text)}</span>`);
    b.type = "button";
    b.addEventListener("click", () => send(text));
    list.append(b);
  }

  $("#method-list").innerHTML = METHOD.map((m) => `<li>${m}</li>`).join("");

  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#prompt");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    send(text);
  });
  $("#btn-site-data").addEventListener("click", () => sheet.show("Site data", siteDataSheet()));
  $("#btn-attach").addEventListener("click", () => sheet.show("Site data", siteDataSheet()));
  $("#btn-location").addEventListener("click", () => sheet.show("Location", locationSheet()));
  $("#btn-profile").addEventListener("click", () => sheet.show("History", profileSheet()));
  for (const b of document.querySelectorAll(".segmented button")) {
    b.addEventListener("click", () => switchView(b.dataset.view));
  }
  segIndicator.init();
  compactHeader();
  $("#kb-stats").addEventListener("click", () => switchView("knowledge"));
  $("#kb-go").addEventListener("click", searchKnowledge);
  $("#kb-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); searchKnowledge(); } });

  $("#btn-new").addEventListener("click", startNew);

  // A plain page load starts a new conversation; the previous one is parked and offered as a link.
  // Only an explicit ?resume=1 (the resume link) reopens it.
  const params = new URLSearchParams(location.search);
  const wanted = params.get("session");
  if (wanted) localStorage.setItem("darukaa.session", wanted);
  else if (!params.has("resume")) store.park();

  api.get("/health").then((h) => {
    const k = h.knowledge_base;
    $("#kb-stats").textContent = `${k.sources} sources · ${k.chunks} passages · ${k.practices} practices`;
    $("#llm-label").textContent = h.llm || "deterministic mode";
    $("#llm-dot").classList.toggle("offline", !h.llm);
    $("#llm-label").title = h.llm
      ? "The reasoning is deterministic; this model only writes the explanation, and every sentence is verified against the evidence."
      : "No LLM configured — the engine still diagnoses and recommends, and writes the explanation from templates.";
  }).catch(() => {
    $("#llm-label").textContent = "engine unreachable";
    $("#llm-dot").classList.add("offline");
  });

  restore();
}

/** Offer the previous conversation instead of silently reopening it. */
function offerResume() {
  const id = store.previous;
  if (!id || store.session) return;
  const box = el("div", "resume");
  const btn = el("button", "", "↩ Resume your previous conversation");
  btn.type = "button";
  btn.addEventListener("click", () => openSession(id));
  box.append(btn);
  $("#examples").after(box);
}

/** Re-render an earlier session from the server (memory outlives the page). */
async function restore() {
  const id = store.session;
  if (!id) { offerResume(); return; }
  try {
    const data = await api.get(`/sessions/${id}`);
    if (!data.messages?.length) return;
    $("#examples").hidden = true;
    $("#hero").hidden = true;
    for (const m of data.messages) {
      try {
        if (m.role === "user") { appendNode(renderUser(m.content)); if (!$("#thread-title").textContent) setThreadTitle(m.content); }
        else if (m.payload) appendNode(renderResponse(m.payload));
        else if (m.content) appendNode(el("div", "card summary", md(m.content.slice(0, 1200))));
      } catch (err) {
        // A turn saved by an older version may lack newer fields: show its text rather than losing it.
        console.warn("could not re-render a stored turn", err);
        appendNode(el("div", "card summary", md(String(m.content || "").slice(0, 1200))));
      }
    }
    updateProfileStrip(data.profile, Object.keys(data.profile || {}));
  } catch (err) {
    if (String(err.message).startsWith("404")) store.clear();   // session really is gone
    else toast(`Could not restore the previous conversation: ${err.message}`);
  }
}

boot();
