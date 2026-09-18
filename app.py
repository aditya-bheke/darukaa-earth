"""Streamlit front end. Deliberately thin: all reasoning lives in the `darukaa` package."""

import json
from html import escape

import streamlit as st

from darukaa import config, llm
from darukaa.engine import Engine
from darukaa.kb.store import get_store
from darukaa.kb.vector import get_retriever
from darukaa.memory import delete_session, list_sessions
from darukaa.schemas import HORIZON_DEFINITIONS, AssistantResponse

st.set_page_config(page_title="Darukaa.Earth — AI Environmental Scientist", page_icon="🌱", layout="wide")

EXAMPLE_JSON = {
    "soil_organic_carbon": "0.3%",
    "rainfall": "low",
    "crop": "monoculture wheat",
    "region": "semi-arid",
    "species_richness_trend": "declining",
}
EXAMPLES = [
    ("🌾", "Vague start", "Biodiversity is declining on my land"),
    ("🏜️", "Semi-arid wheat", "My 5 ha farm near Jodhpur grows only wheat, rainfall is about 350 mm, soil organic carbon is 0.3%"),
    ("🌳", "Cleared forest", "We cleared part of a forest patch for maize; the remaining woodland is fragmented and we spray pesticides. Bees are fewer."),
    ("🧪", "Acidic cotton", "Acidic soil, pH 4.8, humid climate, cotton monoculture with heavy fertilizer use"),
]
CONF_TONE = {"high": "good", "medium": "warn", "low": "bad"}
SEV_TONE = {3: "bad", 2: "warn", 1: "info"}
ARROW = {"increase": "▲", "decrease": "▼", "protect": "◆"}
PROV_LABEL = {"user": "you", "user:json": "json", "geo": "lookup"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,650&family=Inter:wght@400;500;600&display=swap');

:root {
  --ink: #1d2a24; --muted: #5d6b63; --line: #e2ddd0; --paper: #fffdf8; --sand: #f6f4ee;
  --forest: #2f6b4f; --forest-2: #3f8a66; --moss-bg: #e7f1ea;
  --clay: #b4432f; --clay-bg: #f8e5e0; --amber: #a86d0c; --amber-bg: #fbefd6;
  --sky: #2d6386; --sky-bg: #e3eef5; --gray-bg: #eeece5;
}
html, body, .stApp, .stMarkdown, button, input, textarea { font-family: 'Inter', system-ui, sans-serif; }
[data-testid="stIconMaterial"], .material-symbols-rounded { font-family: 'Material Symbols Rounded' !important; }
h1, h2, h3, h4, .serif { font-family: 'Fraunces', Georgia, serif !important; letter-spacing: -0.01em; }
.block-container { padding-top: 1.6rem; max-width: 1180px; }

/* ---------- hero ---------- */
.hero { background: linear-gradient(120deg, #234f3b 0%, #2f6b4f 55%, #5c8a4a 100%); color: #f4f1e8;
        border-radius: 18px; padding: 1.5rem 1.7rem; margin-bottom: 1.1rem; position: relative; overflow: hidden; }
.hero:after { content: ""; position: absolute; right: -60px; top: -60px; width: 240px; height: 240px;
              border-radius: 50%; background: rgba(255,255,255,.06); }
.hero .eyebrow { text-transform: uppercase; letter-spacing: .14em; font-size: .72rem; opacity: .8; font-weight: 600; }
.hero h1 { color: #fffdf6; font-size: 2.05rem; margin: .2rem 0 .35rem 0; padding: 0; font-weight: 650; }
.hero p { margin: 0; max-width: 640px; opacity: .9; font-size: .98rem; line-height: 1.5; }
.stats { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 1.1rem; }
.stat { background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.18); border-radius: 12px;
        padding: .45rem .8rem; min-width: 104px; }
.stat b { display: block; font-family: 'Fraunces', serif; font-size: 1.3rem; color: #fff; line-height: 1.2; }
.stat span { font-size: .72rem; opacity: .85; }

/* ---------- pills & chips ---------- */
.pill { display: inline-block; padding: .14rem .6rem; border-radius: 999px; font-size: .74rem; font-weight: 600;
        margin: 0 .3rem .3rem 0; border: 1px solid transparent; white-space: nowrap; }
.pill.good { background: var(--moss-bg); color: var(--forest); border-color: #cfe3d6; }
.pill.warn { background: var(--amber-bg); color: var(--amber); border-color: #f1ddb2; }
.pill.bad  { background: var(--clay-bg); color: var(--clay); border-color: #efcdc4; }
.pill.info { background: var(--sky-bg); color: var(--sky); border-color: #cfe0ec; }
.pill.neutral { background: var(--gray-bg); color: var(--muted); border-color: var(--line); }
.chip { display: inline-block; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .72rem;
        background: #fff; border: 1px solid var(--line); color: var(--ink); border-radius: 6px; padding: .08rem .4rem; margin: .1rem .15rem; }

/* ---------- section headings ---------- */
.section { display: flex; align-items: baseline; gap: .6rem; margin: 1.3rem 0 .55rem 0; }
.section h3 { margin: 0 !important; padding: 0 !important; font-size: 1.25rem !important; font-weight: 650 !important; color: var(--ink) !important; }
.section span { color: var(--muted); font-size: .82rem; }

/* ---------- summary / callouts ---------- */
.callout { background: var(--paper); border: 1px solid var(--line); border-left: 4px solid var(--forest);
           border-radius: 12px; padding: .9rem 1.1rem; line-height: 1.6; color: var(--ink); }

div[class*="st-key-summary_"], div[class*="st-key-answer_"] {
  background: var(--paper); border: 1px solid var(--line); border-left: 4px solid var(--forest);
  border-radius: 12px; padding: .8rem 1.1rem .2rem 1.1rem; line-height: 1.6; }

/* ---------- diagnosis ---------- */
.dx { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: .6rem .8rem;
      margin-bottom: .5rem; border-left-width: 4px; }
.dx.bad { border-left-color: var(--clay); } .dx.warn { border-left-color: #d49a2a; } .dx.info { border-left-color: var(--sky); }
.dx .t { font-weight: 600; color: var(--ink); font-size: .92rem; }
.dx .d { color: var(--muted); font-size: .83rem; margin-top: .15rem; line-height: 1.45; }

/* ---------- causal chains ---------- */
.chain { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: .55rem .7rem; margin-bottom: .5rem;
         display: flex; flex-wrap: wrap; align-items: center; gap: .25rem; }
.node { background: var(--sky-bg); color: var(--sky); border-radius: 8px; padding: .15rem .5rem; font-size: .8rem; font-weight: 500; }
.node.end { background: var(--moss-bg); color: var(--forest); }
.arrow { color: #9aa59f; font-size: .85rem; }

/* ---------- recommendation cards ---------- */
div[class*="st-key-rec_"] { background: var(--paper); border: 1px solid var(--line) !important; border-left: 5px solid var(--forest) !important;
                            border-radius: 14px !important; padding: 1rem 1.1rem .4rem 1.1rem; box-shadow: 0 1px 2px rgba(30,40,30,.04); }
div[class*="st-key-rec_avoid"] { border-left-color: var(--clay) !important; background: #fffaf7; }
.rec-head { display: flex; gap: .8rem; align-items: flex-start; }
.num { flex: none; width: 2.1rem; height: 2.1rem; border-radius: 50%; background: var(--forest); color: #fff;
       display: flex; align-items: center; justify-content: center; font-family: 'Fraunces', serif; font-weight: 650; }
.num.avoid { background: var(--clay); font-size: .9rem; }
.rec-title { font-family: 'Fraunces', serif; font-size: 1.12rem; font-weight: 650; color: var(--ink); line-height: 1.3; margin-bottom: .35rem; }
.metric-table { width: 100%; border-collapse: collapse; font-size: .84rem; }
.metric-table td, .metric-table th { padding: .45rem .5rem; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }
.metric-table th { color: var(--muted); font-weight: 600; font-size: .74rem; text-transform: uppercase; letter-spacing: .05em; }
.up { color: var(--forest); font-weight: 700; } .down { color: var(--clay); font-weight: 700; } .keep { color: var(--sky); font-weight: 700; }
.ref { border-left: 3px solid var(--line); padding: .2rem .7rem; margin: .45rem 0; font-size: .84rem; }
.ref .c { font-weight: 600; } .ref .x { color: var(--muted); margin-top: .2rem; }

/* ---------- action plan timeline ---------- */
.plan { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: .7rem; }
.phase { background: var(--paper); border: 1px solid var(--line); border-radius: 14px; padding: .85rem .95rem; position: relative; }
.phase .top { display: flex; align-items: center; gap: .5rem; margin-bottom: .35rem; }
.phase .dot { width: 1.7rem; height: 1.7rem; border-radius: 50%; background: var(--moss-bg); color: var(--forest);
              display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: .85rem; flex: none; }
.phase h4 { margin: 0; padding: 0; font-size: .98rem; color: var(--ink); }
.phase .win { font-size: .74rem; color: var(--muted); }
.phase ul { margin: .35rem 0 .45rem 1rem; padding: 0; font-size: .84rem; }
.phase li { margin-bottom: .2rem; }
.phase .why { font-size: .76rem; color: var(--muted); border-top: 1px dashed var(--line); padding-top: .4rem; line-height: 1.4; }
.phase .mon { font-size: .74rem; color: var(--sky); margin-bottom: .35rem; line-height: 1.4; }

/* ---------- clarification ---------- */
.q { display: flex; gap: .7rem; background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: .65rem .8rem; margin: .45rem 0; }
.q .n { flex: none; width: 1.6rem; height: 1.6rem; border-radius: 50%; background: var(--amber-bg); color: var(--amber);
        display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: .8rem; }

/* ---------- empty state ---------- */
.steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: .7rem; margin: .3rem 0 1rem 0; }
.step { background: var(--paper); border: 1px solid var(--line); border-radius: 14px; padding: .8rem .95rem; }
.step b { font-family: 'Fraunces', serif; font-size: 1rem; display: block; margin-bottom: .2rem; }
.step span { color: var(--muted); font-size: .84rem; line-height: 1.45; }
div[class*="st-key-ex_"] button { text-align: left; justify-content: flex-start; min-height: 4.2rem; border-radius: 14px;
                                  background: var(--paper); border: 1px solid var(--line); white-space: normal; }
div[class*="st-key-ex_"] button:hover { border-color: var(--forest); background: #fbfaf5; }

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] { background: #eef0e8; border-right: 1px solid var(--line); }
.brand { font-family: 'Fraunces', serif; font-size: 1.35rem; font-weight: 650; color: var(--forest); }
.side-h { text-transform: uppercase; letter-spacing: .1em; font-size: .7rem; color: var(--muted); font-weight: 600; margin: 1rem 0 .35rem 0; }
.kv { display: flex; justify-content: space-between; gap: .5rem; padding: .28rem 0; border-bottom: 1px dashed var(--line); font-size: .8rem; }
.kv .k { color: var(--muted); } .kv .v { font-weight: 600; color: var(--ink); text-align: right; }
.src { font-size: .62rem; padding: 0 .3rem; border-radius: 4px; margin-left: .25rem; font-weight: 600; background: var(--gray-bg); color: var(--muted); }
.src.lookup { background: var(--sky-bg); color: var(--sky); }

/* ---------- chat ---------- */
[data-testid="stChatMessage"] { background: transparent; }
div[data-testid="stExpander"] details { border-radius: 12px; border-color: var(--line); background: var(--paper); }
</style>
"""


def pill(text: str, tone: str = "neutral") -> str:
    return f'<span class="pill {tone}">{escape(str(text))}</span>'


def section(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="section"><h3>{escape(title)}</h3><span>{escape(sub)}</span></div>', unsafe_allow_html=True)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@st.cache_resource(show_spinner="Loading knowledge base and embedding model…")
def warm_up():
    store = get_store()
    get_retriever()
    return store.stats()


def engine() -> Engine:
    if "engine" not in st.session_state:
        st.session_state.engine = Engine()
        st.session_state.turns = []
    return st.session_state.engine


def load_session(session_id: str) -> None:
    """Reopen an earlier conversation: rebuild the transcript from the stored payloads."""
    eng = Engine(session_id)
    st.session_state.engine = eng
    st.session_state.turns = [
        (m["role"], m["content"], m["payload"]) for m in eng.memory.history(100)
    ]


def send(text: str, structured: dict | None = None):
    with st.spinner("Diagnosing, retrieving evidence and reasoning…"):
        resp = engine().handle(text, structured)
    shown = text if not structured else (text + "\n\n" if text else "") + f"```json\n{json.dumps(structured, indent=2)}\n```"
    st.session_state.turns.append(("user", shown, None))
    st.session_state.turns.append(("assistant", resp.message, resp.model_dump(mode="json")))


# ---------------------------------------------------------------- rendering helpers
def site_graph(r: AssistantResponse) -> str:
    """Graphviz map of this site's reasoning: problems -> variables -> outcomes, and practices -> problems."""
    def q(x):
        return '"' + x.replace('"', "'") + '"'

    lines = ["digraph {", 'rankdir=LR; bgcolor="transparent"; node [fontname="Helvetica", fontsize=10, style=filled, color="#d9d3c4"];',
             'edge [fontname="Helvetica", fontsize=8, color="#9aa59f"];']
    for f in r.diagnosis:
        lines.append(f'{q(f.code)} [label={q(f.label)}, shape=box, style="rounded,filled", fillcolor="#f8e5e0", fontcolor="#7a2c1e"];')
    variables = {v for c in r.causal_chains for v in c.path}
    for v in variables:
        lines.append(f'{q(v)} [label={q(v.replace("_", " "))}, shape=ellipse, fillcolor="#e3eef5", fontcolor="#1f4a66"];')
    for c in r.causal_chains:
        for a, b in zip(c.path, c.path[1:]):
            lines.append(f"{q(a)} -> {q(b)};")
    for f in r.diagnosis:
        for v in f.variables:
            if v in variables:
                lines.append(f'{q(f.code)} -> {q(v)} [style=dashed];')
    for rec in r.recommendations:
        pid = "P_" + rec.practice_id
        color, font = ("#fbefd6", "#7a4d06") if rec.kind == "avoid" else ("#e7f1ea", "#1f4d38")
        label = ("AVOID: " if rec.kind == "avoid" else "") + rec.title.split("(")[0].strip()[:40]
        lines.append(f'{q(pid)} [label={q(label)}, shape=box, style="rounded,filled", fillcolor="{color}", fontcolor="{font}"];')
        for code in rec.addresses:
            lines.append(f'{q(pid)} -> {q(code)} [color="#2f6b4f", label="treats"];')
    lines.append("}")
    return "\n".join(lines)


def render_trace(r: AssistantResponse):
    n_hits = sum(len(t.hits) for t in r.retrieval)
    n_lookups = sum(len(t.structured_lookups) for t in r.retrieval)
    with st.expander(f"🔎 Retrieval trace · {n_hits} passages · {n_lookups} structured lookups"):
        st.caption("Hybrid retrieval = dense embeddings (bge-small) + BM25, fused by reciprocal rank, boosted by "
                   "domain/variable metadata and evidence tier. Structured lookups come from SQLite tables.")
        for t in r.retrieval:
            html(f'<div class="callout" style="margin:.4rem 0;padding:.55rem .8rem"><b>Query</b> '
                 f'<span style="color:var(--muted)">{escape(t.query[:220])}</span><br>'
                 + "".join(f'<span class="chip">{escape(k)}: {escape(json.dumps(v))[:80]}</span>' for k, v in t.filters.items())
                 + "</div>")
            for s in t.structured_lookups:
                st.markdown(f"- 🗂 {s}")
            if t.hits:
                st.dataframe(
                    [{"chunk": h.chunk_id, "source": h.source_id, "score": h.score, "dense rank": h.dense_rank,
                      "BM25 rank": h.sparse_rank, "used by": ", ".join(h.used_by), "text": h.text[:160] + "…"} for h in t.hits],
                    width="stretch", hide_index=True)
    if r.grounding_notes:
        with st.expander(f"🛡 Grounding verifier · {len(r.grounding_notes)} note(s)"):
            for n in r.grounding_notes:
                st.markdown(f"- {n}")


def render_clarification(r: AssistantResponse):
    intro = r.message.split("\n\n1.")[0] if "\n\n1." in r.message else r.message
    html(f'<div class="callout" style="border-left-color:#d49a2a">{escape(intro)}</div>')
    if r.known_variables:
        html('<div style="margin:.55rem 0 .1rem 0;font-size:.8rem;color:var(--muted)">Known so far: '
             + "".join(pill(v.replace("_", " "), "good") for v in r.known_variables) + "</div>")
    for i, q in enumerate(r.clarifying_questions, 1):
        # questions contain **bold** markdown; convert to <b> after escaping
        text = escape(q)
        while "**" in text:
            text = text.replace("**", "<b>", 1).replace("**", "</b>", 1)
        html(f'<div class="q"><div class="n">{i}</div><div>{text}</div></div>')
    st.caption("Tip: answer what you know — or say “not sure, just recommend” and I will proceed with lower confidence.")


def render_recommendation(rec, i: int, idx: int):
    avoid = rec.kind == "avoid"
    with st.container(border=False, key=f"rec_{'avoid' if avoid else 'do'}_{idx}_{i}"):
        badge = '<div class="num avoid">✕</div>' if avoid else f'<div class="num">{i}</div>'
        pills = [pill(f"{rec.confidence} confidence · {rec.confidence_score}", CONF_TONE[rec.confidence]),
                 pill(f"{rec.time_horizon}-term · {HORIZON_DEFINITIONS[rec.time_horizon]}", "info")]
        if avoid:
            pills.insert(0, pill("avoid", "bad"))
        if rec.prerequisite:
            pills.append(pill("prerequisite", "warn"))
        if rec.screening:
            pills.append(pill("screening-level", "warn"))
        chips = "".join(f'<span class="chip">{escape(a)}</span>' for a in rec.addresses)
        html(f'<div class="rec-head">{badge}<div><div class="rec-title">{escape(rec.title)}</div>'
             f'{"".join(pills)}<div style="margin-top:.1rem;font-size:.75rem;color:var(--muted)">treats {chips}</div></div></div>')

        t_over, t_impact, t_verify, t_evid = st.tabs(["Overview", f"Impact ({len(rec.impacted_metrics)})",
                                                       f"Verify ({len(rec.monitoring)})", f"Evidence ({len(rec.references)})"])
        with t_over:
            st.markdown(f"**What to do** — {rec.what_to_do}")
            st.markdown(f"**Why it works** — {rec.why_it_works}")
            if rec.site_specific_reasoning:
                st.markdown(f"**Why for your site** — {rec.site_specific_reasoning}")
            for a in rec.adaptations:
                st.info(a, icon="🧭")
            if rec.tradeoffs:
                st.warning(" ".join(rec.tradeoffs), icon="⚖️")
            st.caption(f"Variables linked: {', '.join(v.replace('_', ' ') for v in rec.variables_linked)} · "
                       f"Confidence basis: {rec.confidence_reason}")
        with t_impact:
            if rec.projections:
                st.markdown("**Projected for your site** — the evidence applied to your baseline, not a prediction")
                st.dataframe([{"metric": pr.metric.replace("_", " "), "now": pr.baseline,
                               f"in {pr.years}y": f"{pr.low}–{pr.high}", "unit": pr.unit,
                               "change": f"{pr.change_low:+g} to {pr.change_high:+g}", "basis": pr.method}
                              for pr in rec.projections], width="stretch", hide_index=True)
                st.caption("Assumes: " + "; ".join(rec.projections[0].assumptions))
                st.markdown("**Literature effects**")
            rows = "".join(
                f'<tr><td class="{ {"increase": "up", "decrease": "down", "protect": "keep"}[m.direction]}">{ARROW[m.direction]}</td>'
                f'<td><b>{escape(m.metric.replace("_", " "))}</b></td><td>{escape(m.estimate)}</td>'
                f'<td>{pill(m.horizon, "info")}</td><td><span class="chip">{escape(m.source_id)}</span></td></tr>'
                for m in rec.impacted_metrics)
            html(f'<table class="metric-table"><tr><th></th><th>Metric</th><th>Estimate</th><th>Horizon</th><th>Source</th></tr>{rows}</table>')
        with t_verify:
            if rec.monitoring:
                rows = "".join(f"<tr><td><b>{escape(m.indicator)}</b></td><td>{escape(m.method)}</td><td>{pill(m.frequency, 'neutral')}</td></tr>"
                               for m in rec.monitoring)
                html(f'<table class="metric-table"><tr><th>Indicator</th><th>Method</th><th>Frequency</th></tr>{rows}</table>')
        with t_evid:
            for ref in rec.references:
                link = f' · <a href="{escape(ref.url)}" target="_blank">link</a>' if ref.url else ""
                html(f'<div class="ref"><div class="c">{escape(ref.citation)}{link} {pill("tier " + str(ref.tier), "neutral")}</div>'
                     f'<div class="x">{escape(ref.excerpt or "")}</div></div>')


def render_plan(r: AssistantResponse):
    cards = []
    for ph in r.action_plan:
        num, _, name = ph.phase.partition(" · ")
        items = "".join(f"<li>{escape(a)}</li>" for a in ph.actions)
        mon = f'<div class="mon">📏 {escape("; ".join(ph.monitor))}</div>' if ph.monitor else ""
        cards.append(f'<div class="phase"><div class="top"><div class="dot">{escape(num)}</div>'
                     f'<div><h4>{escape(name)}</h4><div class="win">{escape(ph.window)}</div></div></div>'
                     f'<ul>{items}</ul>{mon}<div class="why">{escape(ph.rationale)}</div></div>')
    html(f'<div class="plan">{"".join(cards)}</div>')


def render_assessment(r: AssistantResponse, data: dict, idx: int):
    mode = pill("LLM-synthesised · verified", "good") if r.llm_used else pill("deterministic reasoning", "neutral")
    html(f'<div class="section" style="margin-top:.2rem"><h3>Site assessment</h3></div>'
         f'{mode}{pill(str(len(r.known_variables)) + " variables", "info")}'
         f'{pill(str(len(r.diagnosis)) + " problems diagnosed", "bad")}'
         f'{pill(str(sum(x.kind == "do" for x in r.recommendations)) + " recommendations", "good")}')
    summary = r.message.split("\n\n**Diagnosis**")[0].replace("### Assessment\n", "").strip()
    with st.container(key=f"summary_{idx}"):
        st.markdown(summary)

    c1, c2 = st.columns([1.15, 1], gap="medium")
    with c1:
        section("Diagnosis", "cited thresholds")
        for f in r.diagnosis:
            html(f'<div class="dx {SEV_TONE[f.severity]}"><div class="t">{escape(f.label)}</div>'
                 f'<div class="d">{escape(f.explanation)} <span class="chip">{escape(f.evidence_id or "")}</span></div></div>')
    with c2:
        section("How the variables interact", "knowledge-graph paths")
        for c in r.causal_chains:
            nodes = []
            for j, v in enumerate(c.path):
                end = " end" if j == len(c.path) - 1 else ""
                nodes.append(f'<span class="node{end}">{escape(v.replace("_", " "))}</span>')
            html(f'<div class="chain">{"<span class=arrow>→</span>".join(nodes)}</div>')

    section("Recommendations", "ranked and sequenced by the reasoning engine")
    n = 0
    for rec in r.recommendations:
        if rec.kind == "do":
            n += 1
        render_recommendation(rec, n, idx)
        html('<div style="height:.6rem"></div>')

    if r.action_plan:
        section("Action plan", "baseline → unblock → build → sustain")
        render_plan(r)

    html('<div style="height:.8rem"></div>')
    if r.diagnosis:
        with st.expander("🕸 Reasoning map for this site"):
            st.caption("Red = diagnosed problems · blue = variables (knowledge-graph paths) · green = recommended practices")
            st.graphviz_chart(site_graph(r))
    if r.assumptions:
        with st.expander(f"📝 Assumptions & data notes · {len(r.assumptions)}"):
            for a in r.assumptions:
                st.markdown(f"- {a}")
    if r.clarifying_questions:
        st.info("**To sharpen this advice:** " + " ".join(r.clarifying_questions), icon="💡")
    render_trace(r)
    with st.expander("{ } Raw structured response (JSON)"):
        st.json(data, expanded=False)
    d1, d2 = st.columns(2)
    d1.download_button("⬇ Download report (Markdown)", r.message, file_name=f"darukaa_assessment_{idx}.md",
                       mime="text/markdown", key=f"md{idx}", width="stretch")
    d2.download_button("⬇ Download structured JSON", json.dumps(data, indent=2), file_name=f"darukaa_assessment_{idx}.json",
                       mime="application/json", key=f"js{idx}", width="stretch")


def render_answer(r: AssistantResponse, idx: int):
    body = r.message.split("\n\n**Sources:**")[0]
    with st.container(key=f"answer_{idx}"):
        st.markdown(body)
    if r.references:
        html("".join(f'<div class="ref"><div class="c">{escape(ref.citation)} <span class="chip">{escape(ref.evidence_id or "")}</span></div></div>'
                     for ref in r.references))
    render_trace(r)


def render_response(data: dict, idx: int = 0):
    r = AssistantResponse.model_validate(data)
    if r.type == "clarification":
        render_clarification(r)
    elif r.type == "answer":
        render_answer(r, idx)
    else:
        render_assessment(r, data, idx)


# ---------------------------------------------------------------- layout
html(CSS)
stats = warm_up()
eng = engine()

with st.sidebar:
    html('<div class="brand">🌱 Darukaa.Earth</div>'
         '<div style="color:var(--muted);font-size:.8rem;margin-bottom:.6rem">Knowledge-grounded biodiversity intelligence</div>')
    llm_state = pill(config.LLM_MODEL, "good") if llm.available() else pill("no LLM · deterministic", "warn")
    html(f'{llm_state}{pill("session " + eng.session_id, "neutral")}')
    if st.button("🔄 New session", width="stretch"):
        st.session_state.pop("engine", None)
        st.rerun()

    html('<div class="side-h">Structured input</div>')
    raw = st.text_area("JSON site data", json.dumps(EXAMPLE_JSON, indent=2), height=160, label_visibility="collapsed")
    if st.button("Send JSON", width="stretch", type="primary"):
        try:
            send("", json.loads(raw))
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")

    html('<div class="side-h">Location lookup</div>')
    lc1, lc2 = st.columns(2)
    lat = lc1.number_input("Latitude", value=26.24, format="%.4f")
    lon = lc2.number_input("Longitude", value=73.02, format="%.4f")
    if st.button("📍 Fetch soil, climate & species", width="stretch"):
        send(f"My land is at coordinates {lat}, {lon}")
    st.caption("SoilGrids · Open-Meteo ERA5 · GBIF")

    html('<div class="side-h">History</div>')
    for item in list_sessions(8):
        current = item["session_id"] == eng.session_id
        c1, c2 = st.columns([5, 1])
        label = ("▶ " if current else "") + item["title"][:38] + f" · {item['message_count']}"
        if c1.button(label, key=f"h{item['session_id']}", width="stretch",
                     help=f"{item['updated_at']} · {item['session_id']}"):
            load_session(item["session_id"])
            st.rerun()
        if c2.button("🗑", key=f"d{item['session_id']}", help="Delete this conversation"):
            delete_session(item["session_id"])
            if current:
                st.session_state.pop("engine", None)
            st.rerun()

    html('<div class="side-h">Current site profile</div>')
    prof = eng.memory.profile
    if prof.summary():
        rows = []
        for k, v in prof.summary().items():
            src = prof.provenance.get(k, "user")
            label = PROV_LABEL.get(src, "lookup" if src.startswith("geo") else src)
            value = ", ".join(v) if isinstance(v, list) else v
            rows.append(f'<div class="kv"><span class="k">{escape(k.replace("_", " "))}</span>'
                        f'<span class="v">{escape(str(value))}<span class="src {label}">{escape(label)}</span></span></div>')
        html("".join(rows))
    else:
        st.caption("Empty — tell me about your land.")

html(f"""
<div class="hero">
  <div class="eyebrow">Darukaa.Earth · AI environmental scientist</div>
  <h1>Evidence-backed advice for living land</h1>
  <p>Describe a site in words, JSON or coordinates. The system diagnoses soil, water, land-use and biodiversity
     problems together, then recommends sequenced, cited interventions — with a plan to verify they work.</p>
  <div class="stats">
    <div class="stat"><b>{stats['sources']}</b><span>cited sources</span></div>
    <div class="stat"><b>{stats['chunks']}</b><span>evidence passages</span></div>
    <div class="stat"><b>{stats['practices']}</b><span>practices</span></div>
    <div class="stat"><b>{stats['effects']}</b><span>quantified effects</span></div>
    <div class="stat"><b>{stats['relationships']}</b><span>causal links</span></div>
  </div>
</div>
""")

tab_chat, tab_kb, tab_how = st.tabs(["💬 Consult", "📚 Knowledge base", "⚙️ How it works"])

with tab_chat:
    if not st.session_state.turns:
        html("""
        <div class="steps">
          <div class="step"><b>1 · Describe</b><span>Text, JSON or a location. I will ask for what is missing — at least three variables.</span></div>
          <div class="step"><b>2 · Diagnose</b><span>Cited thresholds and a knowledge graph show how soil, water and land use drive biodiversity.</span></div>
          <div class="step"><b>3 · Act & verify</b><span>Ranked practices with estimates, confidence, references and a phased monitoring plan.</span></div>
        </div>""")
        section("Try an example")
        cols = st.columns(2, gap="small")
        for i, (icon, label, text) in enumerate(EXAMPLES):
            with cols[i % 2]:
                if st.button(f"{icon}  **{label}**  \n{text}", key=f"ex_{i}", width="stretch"):
                    send(text)
                    st.rerun()
    for i, (role, content, payload) in enumerate(st.session_state.turns):
        with st.chat_message(role, avatar="🧑‍🌾" if role == "user" else "🌱"):
            if payload:
                render_response(payload, i)
            else:
                st.markdown(content)
    if prompt := st.chat_input("Describe your land — e.g. 'Soil carbon is 0.3%, rainfall is low, wheat monoculture, semi-arid'"):
        send(prompt)
        st.rerun()

with tab_kb:
    store = get_store()
    section("Sources", f"{len(store.sources)} entries · tier 1 = assessment or meta-analysis")
    st.dataframe([{"id": s["id"], "citation": store.citation(s["id"]), "type": s["type"], "tier": s["tier"], "url": s["url"]}
                  for s in store.sources.values()], hide_index=True, width="stretch",
                 column_config={"url": st.column_config.LinkColumn("url")})
    section("Practice → metric effects", "structured, each row linked to an evidence passage")
    st.dataframe([{"practice": p["id"], "metric": e["metric"], "direction": e["direction"], "estimate": e["estimate"],
                   "horizon": e["horizon"], "evidence": e["evidence_id"]}
                  for p in store.practices.values() for e in p["effects"]], hide_index=True, width="stretch")
    section("Try the retriever", "dense + BM25 hybrid")
    q = st.text_input("Search query", "cover crops soil water in semi-arid regions")
    if q:
        hits = get_retriever().search(q, k=6)
        st.dataframe([{k: h[k] for k in ("chunk_id", "source_id", "score", "dense_rank", "sparse_rank", "text")} for h in hits],
                     hide_index=True, width="stretch")

with tab_how:
    section("Pipeline for every message")
    st.markdown("""
1. **Parse** free text / JSON / coordinates into a typed `SiteProfile` (rule parser + optional LLM extractor).
2. **Remember**: merge into the session profile stored in SQLite (multi-turn memory).
3. **Enrich** (if coordinates): ISRIC SoilGrids (pH, SOC), Open-Meteo ERA5 (rainfall, temperature, aridity → climate zone) and GBIF (recorded species, threatened-species records).
4. **Decide**: fewer than 3 variables across 2 domains (or no land use) → targeted clarifying questions; a question about earlier advice → grounded answer; otherwise → recommend.
5. **Diagnose** with cited thresholds → issue codes (e.g. `SOC_VERY_LOW`, `WATER_LIMITED`).
6. **Reason over the knowledge graph** to show how issues propagate to biodiversity.
7. **Score structured practices** — each must address ≥2 diagnosed issues (prerequisites like liming excepted); water-consuming practices and contraindicated ones are excluded.
8. **Retrieve** supporting passages (dense + BM25 hybrid, metadata-boosted).
9. **Synthesise** site-specific reasoning with the LLM using only retrieved evidence, then **verify**: sentences citing unknown evidence or unsupported numbers are removed.
10. **Plan**: sequence the practices into baseline → unblock → build → sustain phases, each with monitoring indicators.
11. **Respond** with a validated JSON schema: recommendation, impacted metrics, time horizon, confidence, references, action plan.
""")
    st.graphviz_chart("""
digraph {
  rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", fillcolor="#fffdf8", color="#d9d3c4", fontname="Helvetica", fontsize=10];
  edge [color="#9aa59f"];
  in [label="Text / JSON / lat-lon", fillcolor="#e3eef5"]; parse [label="Profile parser\\n(rules + LLM)"]; mem [label="Session memory\\n(SQLite)"];
  geo [label="SoilGrids · Open-Meteo\\n· GBIF"]; dec [label="Dialogue policy", shape=diamond]; clar [label="Clarifying\\nquestions", fillcolor="#fbefd6"];
  diag [label="Diagnosis\\n(thresholds)"]; vgraph [label="Variable graph\\n(causal chains)"]; rec [label="Practice scorer\\n(structured effects)"];
  ret [label="Hybrid retriever\\n(bge + BM25)"]; llm [label="LLM synthesis"]; ver [label="Grounding\\nverifier", fillcolor="#f8e5e0"];
  plan [label="Planner\\n(phases + monitoring)"]; out [label="Structured response", fillcolor="#e7f1ea"];
  kb [label="Knowledge base\\nsources · passages · practices · edges", shape=cylinder, fillcolor="#e7f1ea"];
  in -> parse -> mem -> dec; parse -> geo -> mem; dec -> clar; dec -> diag -> vgraph -> rec -> ret -> llm -> ver -> plan -> out;
  kb -> diag; kb -> vgraph; kb -> rec; kb -> ret;
}""")
