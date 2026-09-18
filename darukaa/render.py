"""Markdown rendering of a structured response (used by the CLI, the API `markdown` field and memory)."""

from darukaa.schemas import HORIZON_DEFINITIONS, AssistantResponse

ARROW = {"increase": "↑", "decrease": "↓", "protect": "⛨"}


def to_markdown(r: AssistantResponse) -> str:
    out = []
    if r.type == "clarification":
        out.append(r.message)
        if r.clarifying_questions:
            out.append("")
            out += [f"{i}. {q}" for i, q in enumerate(r.clarifying_questions, 1)]
        return "\n".join(out)

    if r.type == "answer":
        out.append(r.message)
        if r.references:
            out.append("\n**Sources:** " + "; ".join(f"{ref.citation} [{ref.evidence_id}]" for ref in r.references))
        return "\n".join(out)

    out.append("### Assessment")
    out.append(r.message)
    if r.diagnosis:
        out.append("\n**Diagnosis**")
        out += [f"- **{f.label}** — {f.explanation} [{f.evidence_id}]" for f in r.diagnosis]
    if r.causal_chains:
        out.append("\n**How the variables interact**")
        out += [f"- {' → '.join(c.path)}" for c in r.causal_chains]
    for i, rec in enumerate(r.recommendations, 1):
        tag = "AVOID" if rec.kind == "avoid" else f"{i}" + (" (screening-level)" if rec.screening else "")
        out.append(f"\n### {tag}. {rec.title}")
        out.append(f"**What to do:** {rec.what_to_do}")
        out.append(f"**Why it works:** {rec.why_it_works}")
        if rec.site_specific_reasoning:
            out.append(f"**Why for your site:** {rec.site_specific_reasoning}")
        for a in rec.adaptations:
            out.append(f"**Adapt for your conditions:** {a}")
        out.append("**Impacted metrics:**")
        out += [f"- {ARROW[m.direction]} `{m.metric}` — {m.estimate} *({m.horizon}-term; {m.source_id})*" for m in rec.impacted_metrics]
        out.append(f"**Time horizon:** {rec.time_horizon} ({HORIZON_DEFINITIONS[rec.time_horizon]}) · "
                   f"**Confidence:** {rec.confidence} ({rec.confidence_score}) — {rec.confidence_reason}")
        out.append(f"**Addresses:** {', '.join(rec.addresses)} · **Variables linked:** {', '.join(rec.variables_linked)}")
        if rec.tradeoffs:
            out.append("**Trade-offs:** " + " ".join(rec.tradeoffs))
        if rec.projections:
            out.append("**Projected for your site** (evidence applied to your baseline, not a prediction):")
            for pr in rec.projections:
                out.append(f"- `{pr.metric}`: {pr.baseline} → {pr.low}–{pr.high} {pr.unit} over {pr.years} years "
                           f"({pr.change_low:+g} to {pr.change_high:+g} {pr.unit}) — {pr.method} [{pr.evidence_id}]")
            out.append("  - *Assumes:* " + "; ".join(rec.projections[0].assumptions))
        if rec.monitoring:
            out.append("**How to verify it is working:** " + "; ".join(
                f"{m.indicator} ({m.method}; {m.frequency})" for m in rec.monitoring))
        out.append("**References:** " + "; ".join(f"{ref.citation}" for ref in rec.references))
    if r.action_plan:
        out.append("\n### Action plan")
        for ph in r.action_plan:
            out.append(f"**{ph.phase}** ({ph.window}) — {ph.rationale}")
            out += [f"- {a}" for a in ph.actions]
            if ph.monitor:
                out.append("  - *Monitor:* " + "; ".join(ph.monitor))
    if r.assumptions:
        out.append("\n**Assumptions & data notes**")
        out += [f"- {a}" for a in r.assumptions]
    if r.clarifying_questions:
        out.append("\n**To sharpen this advice:**")
        out += [f"- {q}" for q in r.clarifying_questions]
    return "\n".join(out)
