"""Scores structured practices against the diagnosis and assembles evidence-backed recommendations."""

from darukaa.reasoning.diagnosis import is_water_limited
from darukaa.reasoning.projections import project_practice
from darukaa.schemas import Finding, ImpactedMetric, MonitoringItem, Recommendation, Reference, SiteProfile

TIER_CONFIDENCE = {1: 0.85, 2: 0.7, 3: 0.55}
HORIZON_ORDER = {"short": 0, "medium": 1, "long": 2}
# A "decrease" in these metrics is a side effect, not a benefit (e.g. cover crops drawing down soil water).
HARMFUL_IF_DECREASED = {"soil_moisture", "soil_organic_carbon", "species_richness", "water_availability", "crop_yield_stability"}
# In water-limited systems, water-securing practices should come first.
WATER_FIRST = {"conservation_ag_mulch", "in_situ_water_harvesting"}


def _profile_variables(p: SiteProfile, findings: list[Finding]) -> set[str]:
    names = {
        "soil_organic_carbon_pct": "soil_organic_carbon", "soil_ph": "soil_ph", "soil_moisture": "soil_moisture",
        "rainfall_mm": "rainfall", "rainfall_level": "rainfall", "temperature_c": "temperature",
        "temperature_level": "temperature", "climate_zone": "rainfall", "land_use": "land_use",
        "cropping_system": "crop_diversity", "species_richness_trend": "species_richness",
        "habitat_diversity": "habitat_diversity", "natural_habitat_pct": "habitat_diversity",
        "fragmentation": "habitat_fragmentation", "pollution": "pollution", "deforestation": "deforestation",
        "pollinator_trend": "pollinators", "erosion": "erosion",
    }
    out = {v for k, v in names.items() if getattr(p, k) not in (None, [], False)}
    for f in findings:
        out.update(f.variables)
    return out


GATEKEEPER_BOOST = 8  # soil-chemistry constraints block other practices, so fix them first


def score_practice(practice: dict, codes: dict[str, int], p: SiteProfile, min_addressed: int = 2) -> tuple[float, list[str]]:
    """Return (score, addressed issue codes). Score 0 means not applicable."""
    if any(code in codes for code in practice["avoid_when"]):
        return 0.0, []
    if practice["requires"] and not all(code in codes for code in practice["requires"]):
        return 0.0, []
    land_uses = practice["suits"].get("land_uses")
    if land_uses and p.land_use and p.land_use not in land_uses:
        return 0.0, []
    addressed = [c for c in practice["addresses"] if c in codes]
    score = sum(practice["addresses"][c] * codes[c] for c in addressed)
    if practice["requires"]:
        score += GATEKEEPER_BOOST
    if "WATER_LIMITED" in codes and practice["water_penalty"]:
        return 0.0, []  # water-consuming practices are screened out where water is the first limit
    if "WATER_LIMITED" in codes:
        if practice["id"] in WATER_FIRST:
            score += 2
    if practice["kind"] == "avoid" and not ({"WATER_LIMITED", "OPEN_ECOSYSTEM"} & set(codes)):
        return 0.0, []
    # a recommendation must connect ≥2 diagnosed issues — no single-variable answers
    # Prerequisite practices (e.g. liming) unblock others, so they may target a single diagnosed constraint.
    needed = 1 if practice["requires"] else min_addressed
    if practice["kind"] == "do" and len(addressed) < needed:
        return 0.0, addressed
    return max(score, 0.0), addressed


def _confidence(practice: dict, store, codes: dict, p: SiteProfile, adaptations: list[str], screening: bool = False) -> tuple[float, str]:
    tiers = [store.sources[e["source_id"]]["tier"] for e in practice["effects"]]
    base = sum(TIER_CONFIDENCE.get(t, 0.5) for t in tiers) / len(tiers)
    reasons = [f"evidence from {sum(t == 1 for t in tiers)}/{len(tiers)} assessment/meta-analysis sources"]
    if practice["water_penalty"] and "WATER_LIMITED" in codes:
        base -= 0.2
        reasons.append("main evidence comes from wetter systems than this site")
    if adaptations:
        base -= 0.05
        reasons.append("requires site-specific adaptation")
    n_known = len(p.known_variables())
    if n_known < 5:
        base -= 0.1
        reasons.append(f"only {n_known} site variables known")
    if any(e["direction"] == "increase" and "qualitative" in e["estimate"].lower() for e in practice["effects"]):
        base -= 0.05
        reasons.append("some effects are qualitative")
    if screening:
        base -= 0.2
        reasons.append("screening-level: too few site problems identified to target precisely")
    base = round(max(0.1, min(base, 0.95)), 2)
    level = "high" if base >= 0.75 else "medium" if base >= 0.55 else "low"
    return base, level + ": " + "; ".join(reasons)


def recommend(store, p: SiteProfile, findings: list[Finding], max_do: int = 4, max_avoid: int = 1) -> list[Recommendation]:
    codes = {f.code: f.severity for f in findings}
    site_vars = _profile_variables(p, findings)
    screening = False
    scored = []
    for practice in store.practices.values():
        score, addressed = score_practice(practice, codes, p)
        if score > 0:
            scored.append((score, practice, addressed))
    if not any(pr["kind"] == "do" for _, pr, _ in scored) and codes:
        # Too little is known for multi-issue targeting: fall back to screening-level, low-regret options.
        screening = True
        scored = [(s, pr, a) for pr in store.practices.values()
                  for s, a in [score_practice(pr, codes, p, min_addressed=1)] if s > 0]
    scored.sort(key=lambda x: -x[0])

    recs, n_do, n_avoid = [], 0, 0
    for score, practice, addressed in scored:
        if practice["kind"] == "avoid":
            if n_avoid >= max_avoid:
                continue
            n_avoid += 1
        else:
            if n_do >= max_do:
                continue
            n_do += 1
        adaptations = [text for code, text in practice["adaptations"].items() if code in codes]
        metrics = [ImpactedMetric(metric=e["metric"], direction=e["direction"], estimate=e["estimate"],
                                  horizon=e["horizon"], source_id=e["source_id"], evidence_id=e["evidence_id"])
                   for e in practice["effects"]]
        refs, seen = [], set()
        for e in practice["effects"]:
            if e["evidence_id"] in seen:
                continue
            seen.add(e["evidence_id"])
            src = store.sources[e["source_id"]]
            refs.append(Reference(source_id=src["id"], citation=store.citation(src["id"]), url=src["url"], tier=src["tier"],
                                  evidence_id=e["evidence_id"], excerpt=store.chunks[e["evidence_id"]]["text"]))
        conf, reason = _confidence(practice, store, codes, p, adaptations, screening)
        horizons = [HORIZON_ORDER[m.horizon] for m in metrics
                    if not (m.direction == "decrease" and m.metric in HARMFUL_IF_DECREASED)]
        horizon = min(horizons) if horizons else 1
        linked = [v for v in practice["variables_linked"] if v in site_vars]
        if len(linked) < 2:  # show the variables the mechanism connects, even if not yet measured on site
            linked += [v for v in practice["variables_linked"] if v not in linked][:3 - len(linked)]
        recs.append(Recommendation(
            practice_id=practice["id"], kind=practice["kind"], title=practice["name"],
            what_to_do=practice["action"], why_it_works=practice["mechanism"],
            impacted_metrics=metrics, time_horizon=["short", "medium", "long"][horizon],
            confidence=reason.split(":")[0], confidence_score=conf, confidence_reason=reason.split(": ", 1)[1],
            addresses=addressed, variables_linked=linked, adaptations=adaptations,
            tradeoffs=practice["tradeoffs"], references=refs, score=round(score, 2), screening=screening,
            prerequisite=bool(practice["requires"]), projections=project_practice(practice, p),
            monitoring=[MonitoringItem(**m) for m in practice["monitoring"]]))

    if is_water_limited(p):  # sequence: secure water first
        recs.sort(key=lambda r: (r.kind == "avoid", r.practice_id not in WATER_FIRST, -r.score))
    return recs
