"""Value of information: which unknown variable would most change the advice?

The clarifier knows which variables are missing. This module decides which one is worth asking about
*first*, by actually testing it: fill the gap with each plausible value, re-run the deterministic
diagnosis and recommender, and measure how much the output moves. A variable that never changes the
recommendations is not worth the user's time; one that flips half of them is the next question.

Everything here is cheap and deterministic (no LLM, no retrieval), so it runs on every turn.
"""

from darukaa.reasoning.diagnosis import diagnose
from darukaa.reasoning.recommender import recommend
from darukaa.schemas import SiteProfile

# Plausible values probed for each unknown variable (kept small: this is a sensitivity test, not a search).
PROBES: dict[str, list] = {
    "soil_organic_carbon_pct": [0.3, 0.9],
    "soil_ph": [4.8, 6.5, 9.0],
    "rainfall_level": ["low", "high"],
    "land_use": ["cropland", "grassland", "forest"],
    "cropping_system": ["monoculture", "rotation"],
    "habitat_diversity": ["low", "high"],
    "pollution": [["pesticide", "fertilizer"], []],
    "deforestation": [True, False],
    "soil_texture": ["sandy", "clayey"],
    "species_richness_trend": ["declining", "stable"],
}

# Which profile field each clarifier question is really asking about.
QUESTION_FIELD = {
    "soil organic carbon": "soil_organic_carbon_pct",
    "rainfall": "rainfall_level",
    "land use": "land_use",
    "climate zone / location": "rainfall_level",
    "cropping system": "cropping_system",
    "habitat": "habitat_diversity",
    "soil pH": "soil_ph",
    "chemical inputs": "pollution",
}


def _outcome(store, profile: SiteProfile) -> tuple[set[str], set[str]]:
    findings = diagnose(profile)
    recs = recommend(store, profile, findings)
    return {r.practice_id for r in recs}, {f.code for f in findings}


def rank_missing(store, profile: SiteProfile, missing: list[tuple[str, str]], limit: int = 3) -> list[dict]:
    """Rank the missing variables by how much knowing them would change the answer."""
    base_recs, base_codes = _outcome(store, profile)
    scored = []
    for label, question in missing:
        field = QUESTION_FIELD.get(label)
        if field is None or field not in PROBES:
            continue
        changed_recs, changed_codes = 0, 0
        for value in PROBES[field]:
            trial = profile.model_copy(deep=True)
            try:
                setattr(trial, field, value)
            except Exception:
                continue
            recs, codes = _outcome(store, trial)
            changed_recs = max(changed_recs, len(recs ^ base_recs))
            changed_codes = max(changed_codes, len(codes ^ base_codes))
        scored.append({
            "label": label,
            "question": question,
            "field": field,
            "changed_recommendations": changed_recs,
            "changed_findings": changed_codes,
            "score": changed_recs * 2 + changed_codes,
        })
    scored.sort(key=lambda d: (-d["score"], missing.index((d["label"], d["question"]))))
    return scored[:limit]


def phrase(item: dict, n_recs: int) -> str:
    """Explain to the user why this question is being asked now."""
    if item["changed_recommendations"]:
        n = item["changed_recommendations"]
        return f"{item['question']} *(could change {min(n, max(n_recs, 1))} of the recommendations)*"
    if item["changed_findings"]:
        return f"{item['question']} *(would refine the diagnosis)*"
    return item["question"]
