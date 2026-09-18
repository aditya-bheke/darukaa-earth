"""Turns ranked recommendations into a phased, measurable action plan.

Sequencing logic (from the reasoning engine, not the LLM):
  0. Baseline  — measure the diagnosed variables before acting, so change can be verified.
  1. Unblock   — prerequisites (pH correction) and, in drylands, water-securing practices.
  2. Build     — diversification, habitat and carbon-building practices.
  3. Sustain   — long-horizon effects, re-measurement, and standing "avoid" rules.
"""

from darukaa.reasoning.recommender import WATER_FIRST
from darukaa.schemas import Finding, PlanPhase, Recommendation

# Diagnosed issue -> baseline measurement to take before acting.
BASELINE_TESTS = {
    "SOC_VERY_LOW": "soil organic carbon lab test (0–30 cm)",
    "SOC_LOW": "soil organic carbon lab test (0–30 cm)",
    "PH_ACIDIC": "soil pH and exchangeable acidity",
    "PH_ALKALINE": "soil pH, ESP/SAR and irrigation-water quality",
    "WATER_LIMITED": "soil moisture at 10/30 cm and a rain gauge record",
    "MONOCULTURE": "yield and input records per plot (for later comparison)",
    "LOW_HABITAT": "map of semi-natural habitat share per km²",
    "FRAGMENTED": "map of habitat patches and gaps between them",
    "BIODIVERSITY_DECLINE": "bird and butterfly transect counts",
    "POLLINATOR_DECLINE": "timed flower-visitor counts during flowering",
    "PESTICIDE": "log of pesticide active ingredients and spray dates",
    "NUTRIENT_POLLUTION": "nitrate test of nearby drains, ponds or wells",
    "DEFORESTATION": "count of remnant trees and natural seedlings",
    "EROSION": "erosion pins or photo points on slopes",
    "HEAT_STRESS": "local temperature record (min/max thermometer)",
    "OPEN_ECOSYSTEM": "native grass and forb species list in fixed quadrats",
}


def _monitor(recs: list[Recommendation]) -> list[str]:
    seen, out = set(), []
    for r in recs:
        for m in r.monitoring:
            if m.indicator not in seen:
                seen.add(m.indicator)
                out.append(f"{m.indicator} — {m.frequency}")
    return out


def build_plan(recs: list[Recommendation], findings: list[Finding]) -> list[PlanPhase]:
    if not recs:
        return []
    codes = {f.code for f in findings}
    do = [r for r in recs if r.kind == "do"]
    avoid = [r for r in recs if r.kind == "avoid"]

    baseline = list(dict.fromkeys(BASELINE_TESTS[c] for c in (f.code for f in findings) if c in BASELINE_TESTS))
    first = [r for r in do if r.prerequisite or ("WATER_LIMITED" in codes and r.practice_id in WATER_FIRST)]
    if not first:
        first = [r for r in do if r.time_horizon == "short"][:2] or do[:1]
    rest = [r for r in do if r not in first]

    plan = [PlanPhase(
        phase="0 · Baseline", window="first 1–2 months",
        actions=[f"Measure: {b}" for b in baseline] or ["Record current yields, inputs and a species list"],
        rationale="Measure the diagnosed variables before acting so that improvement can be verified, "
                  "not assumed; looked-up (satellite/model) values are not field measurements.")]
    why_first = []
    if any(r.prerequisite for r in first):
        why_first.append("soil-chemistry constraints block the other practices")
    if "WATER_LIMITED" in codes and any(r.practice_id in WATER_FIRST for r in first):
        why_first.append("water is the first limiting factor, and later practices need the conserved moisture")
    plan.append(PlanPhase(
        phase="1 · Unblock & secure", window="0–12 months",
        actions=[r.title for r in first], monitor=_monitor(first),
        rationale=("Done first because " + " and ".join(why_first) + ".") if why_first
        else "Fastest-acting practices, giving early, measurable results."))
    if rest:
        plan.append(PlanPhase(
            phase="2 · Diversify & build", window="years 1–3",
            actions=[r.title for r in rest], monitor=_monitor(rest),
            rationale="Builds soil carbon, crop diversity and habitat once the site constraints are addressed."))
    long_metrics = sorted({m.metric for r in do for m in r.impacted_metrics if m.horizon == "long"})
    sustain = ["Keep the practices above in place — soil-carbon and habitat gains are reversible if management reverts",
               "Re-run this assessment with the new measurements and adjust"]
    sustain += [f"Keep avoiding: {r.title.removeprefix('Avoid: ')}" for r in avoid]
    plan.append(PlanPhase(
        phase="3 · Sustain & review", window="year 3 onwards",
        actions=sustain,
        monitor=[f"{m.replace('_', ' ')} — compare with baseline" for m in long_metrics] or ["all baseline indicators — compare with year 0"],
        rationale="Long-horizon effects (" + (", ".join(m.replace("_", " ") for m in long_metrics) or "carbon, habitat")
                  + ") take several years to show and must be confirmed against the baseline."))
    return plan
