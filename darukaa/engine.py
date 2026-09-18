"""Orchestrator: one call per user turn.

    parse -> merge into memory -> (geo enrich) -> decide: clarify | recommend | answer
    recommend = diagnose -> causal chains -> score structured practices -> hybrid retrieval
                -> LLM site-specific synthesis -> grounding verification -> structured response
"""

import json

from darukaa import config, llm
from darukaa.kb.store import get_store
from darukaa.kb.vector import get_retriever
from darukaa.memory import SessionMemory
from darukaa.reasoning import clarifier, verifier, voi
from darukaa.reasoning.diagnosis import diagnose
from darukaa.reasoning.graph import causal_chains
from darukaa.reasoning.planner import build_plan
from darukaa.reasoning.profile_parser import extract, looks_like_a_question, parse_json, wants_to_skip
from darukaa.reasoning.projections import baseline_summary
from darukaa.reasoning.recommender import recommend
from darukaa.render import to_markdown
from darukaa.schemas import SAME_VARIABLE, AssistantResponse, Reference, RetrievalHit, RetrievalTrace, SiteProfile

SYNTH_SYSTEM = """You are an environmental scientist. You receive a site profile, a diagnosis and a set of
recommendations that were selected by a rule engine from a curated knowledge base, each with evidence passages
labelled by id. Write:
- "summary": 3-4 sentences explaining how the site's variables interact (soil, water, land use, biodiversity)
  and why the recommendations are sequenced this way.
- "reasoning": for each practice_id, 2-3 sentences explaining why THIS practice fits THIS site, connecting at
  least three of the site's variables.
Rules: use only facts from the evidence passages and the profile; cite passages inline as [evidence_id];
do not introduce any number that is not in the passages or profile; do not invent sources.
Return JSON: {"summary": "...", "reasoning": {"<practice_id>": "..."}}"""

ANSWER_SYSTEM = """You are an environmental scientist answering a follow-up question about a specific site.
Use ONLY the evidence passages provided (cite them inline as [evidence_id], using only ids that start with "ev_" or "pdf_") plus the site profile and the
earlier recommendations. If the passages do not support an answer, say what is unknown instead of guessing.
Do not introduce numbers that are not in the passages or profile. Keep it under 180 words."""


def _profile_text(p: SiteProfile) -> str:
    return "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in p.summary().items() if k not in ("latitude", "longitude"))


class Engine:
    def __init__(self, session_id: str | None = None):
        self.store = get_store()
        self.retriever = get_retriever()
        self.memory = SessionMemory(session_id)

    @property
    def session_id(self) -> str:
        return self.memory.session_id

    # ------------------------------------------------------------------ turn handling
    def handle(self, message: str, structured: dict | None = None) -> AssistantResponse:
        mem = self.memory
        shown = message if not structured else f"{message}\n```json\n{json.dumps(structured, indent=2)}\n```".strip()
        mem.add_message("user", shown)

        new = extract(message, mem.profile) if message.strip() else SiteProfile()
        if structured:
            s = SiteProfile.model_validate(parse_json(structured))
            s.provenance = {k: "user:json" for k in s.summary()}
            new.merge(s, "user:json")
        before = mem.profile.model_copy(deep=True)
        changed = mem.profile.merge(new)

        notes = []
        if config.GEO_ENABLED and {"latitude", "longitude"} & set(changed) and mem.profile.latitude is not None:
            from darukaa import geo

            geo_profile, notes = geo.enrich(mem.profile)
            changed += mem.profile.merge(geo_profile, "geo")
        mem.state["geo_notes"] = notes or mem.state.get("geo_notes", [])

        # Fields that do not change the diagnosis: they must not trigger a fresh assessment when the
        # user is simply asking a question about the advice already given.
        material = [c for c in changed if c not in ("goal", "region", "area_ha")]
        if looks_like_a_question(message) and not material and mem.state.get("last_recs"):
            changed = []

        skip = wants_to_skip(message)
        has_recs = bool(mem.state.get("last_recs"))
        n_known = len(mem.profile.known_variables())
        rounds = mem.state.get("clarify_rounds", 0)

        if not changed and has_recs and not skip:
            resp = self._answer(message)
        elif clarifier.is_sufficient(mem.profile) or (skip and n_known >= 1) or (rounds >= 2 and n_known >= 2):
            resp = self._recommend(message, changed, before, skip)
        else:
            resp = self._clarify(changed)

        resp.message = to_markdown(resp)
        mem.add_message("assistant", resp.message, resp.model_dump(mode="json"))
        mem.save()
        return resp

    # ------------------------------------------------------------------ clarify
    def _clarify(self, changed: list[str]) -> AssistantResponse:
        p, mem = self.memory.profile, self.memory
        asked = mem.state.setdefault("asked", {})
        qs = clarifier.next_questions(p, asked)
        if p.summary():   # once anything is known, order by information value, not by a fixed list
            ranked = voi.rank_missing(self.store, p, [(lbl, q) for lbl, q in qs], limit=len(qs))
            by_label = {item["label"]: item for item in ranked}
            qs = sorted(qs, key=lambda lq: -by_label.get(lq[0], {}).get("score", 0))
        for label, _ in qs:
            asked[label] = asked.get(label, 0) + 1
        mem.state["clarify_rounds"] = mem.state.get("clarify_rounds", 0) + 1
        known = p.known_variables()
        intro = []
        if changed:
            intro.append("Noted: " + ", ".join(f"{k.replace('_', ' ')} = {getattr(p, k)}" for k in changed if k != "provenance") + ".")
        for note in mem.state.get("geo_notes", []) if "latitude" in changed else []:
            intro.append(f"Looked up — {note}.")
        if len(known) >= clarifier.MIN_VARIABLES and p.land_use is None:
            intro.append(f"I now have {len(known)} variables ({', '.join(known)}), but the right interventions "
                         "depend on how the land is used, so I need that before recommending anything.")
        else:
            intro.append(
                f"To reason about this properly I need at least {clarifier.MIN_VARIABLES} environmental variables across soil, "
                f"climate/water and land use (I have {len(known)}: {', '.join(known) or 'none yet'}). "
                "Soil carbon, water and land use interact, so a recommendation based on one of them alone could be wrong for your site.")
        return AssistantResponse(
            type="clarification", message=" ".join(intro), profile=p.summary(), known_variables=known,
            missing_variables=[label for label, _ in clarifier.missing(p)],
            clarifying_questions=[q for _, q in qs],
            assumptions=["You can answer 'not sure' and I will proceed with lower confidence."])

    # ------------------------------------------------------------------ recommend
    def _recommend(self, message: str, changed: list[str], before: SiteProfile, skip: bool) -> AssistantResponse:
        p, mem, store = self.memory.profile, self.memory, self.store
        findings = diagnose(p)
        chains = causal_chains(store.relationships, findings)
        recs = recommend(store, p, findings)
        known = p.known_variables()

        # --- retrieval: one context query for the diagnosis + one per recommendation
        domains = sorted(p.known_domains())
        variables = sorted({v for f in findings for v in f.variables})
        # A short site query, then one focused query per diagnosed problem: a single long query mixing
        # everything retrieves generic passages, while per-problem queries retrieve the specific evidence.
        context_query = " ".join(x for x in [message.strip()[:120], p.climate_zone, p.land_use, p.crop] if x)
        traces = []
        hits = self.retriever.search(context_query or _profile_text(p), k=3, domains=domains, variables=variables)
        allowed: dict[str, str] = {h["chunk_id"]: h["text"] for h in hits}
        problem_hits = []
        for f in sorted(findings, key=lambda f: -f.severity)[:3]:
            q = f"{f.label} {' '.join(f.variables)} {p.climate_zone or ''} {p.land_use or ''}".strip()
            found = self.retriever.search(q, k=2, domains=domains, variables=f.variables,
                                          exclude=set(allowed))
            problem_hits += [(f.code, q, h) for h in found]
            allowed.update({h["chunk_id"]: h["text"] for h in found})
        traces.append(RetrievalTrace(
            query=context_query.strip(), filters={"domains": domains, "variables": variables, "per_problem_queries": [q for _, q, _ in problem_hits]},
            hits=[RetrievalHit(**{k: h[k] for k in ("chunk_id", "source_id", "score", "dense_rank", "sparse_rank", "text")}, used_by=["site context"]) for h in hits]
            + [RetrievalHit(**{k: h[k] for k in ("chunk_id", "source_id", "score", "dense_rank", "sparse_rank", "text")}, used_by=[code]) for code, _, h in problem_hits],
            structured_lookups=[f"thresholds -> {f.code} ({f.evidence_id})" for f in findings]
            + [f"graph path: {' → '.join(c.path)}" for c in chains]
            + [f"projection: {pr.metric} {pr.baseline}{pr.unit} → {pr.low}–{pr.high} over {pr.years}y ({r.practice_id})"
               for r in recs for pr in r.projections]))
        for f in findings:
            if f.evidence_id:
                allowed[f.evidence_id] = store.chunks[f.evidence_id]["text"]
        for c in chains:
            for e in c.evidence_ids:
                allowed[e] = store.chunks[e]["text"]
        per_rec_allowed = {}
        for r in recs:
            own = {ref.evidence_id for ref in r.references}
            q = f"{r.title} {' '.join(r.addresses)} {p.climate_zone or ''} {p.crop or ''}"
            extra = self.retriever.search(q, k=2, domains=domains, variables=r.variables_linked, exclude=own)
            traces.append(RetrievalTrace(
                query=q.strip(), filters={"exclude": sorted(own), "variables": r.variables_linked},
                hits=[RetrievalHit(**{k: h[k] for k in ("chunk_id", "source_id", "score", "dense_rank", "sparse_rank", "text")}, used_by=[r.practice_id]) for h in extra],
                structured_lookups=[f"practice_effects[{r.practice_id}] -> {len(r.impacted_metrics)} quantified effects", f"score={r.score} addresses={r.addresses}"]))
            ids = {ref.evidence_id: store.chunks[ref.evidence_id]["text"] for ref in r.references}
            ids.update({h["chunk_id"]: h["text"] for h in extra})
            per_rec_allowed[r.practice_id] = ids
            allowed.update(ids)

        # --- LLM synthesis (optional) + grounding verification
        summary, grounding, llm_used = "", [], False
        if recs and llm.available():
            payload = {
                "site_profile": p.summary(),
                "diagnosis": [f.label for f in findings],
                "causal_chains": [" → ".join(c.path) for c in chains],
                "recommendations": [{"practice_id": r.practice_id, "title": r.title, "action": r.what_to_do,
                                     "mechanism": r.why_it_works, "adaptations": r.adaptations,
                                     "evidence_ids": list(per_rec_allowed[r.practice_id])} for r in recs],
                "evidence": allowed,
            }
            out = llm.chat_json(SYNTH_SYSTEM, json.dumps(payload), max_tokens=1300)
            if isinstance(out, dict):
                llm_used = True
                profile_vals = list(p.summary().values())
                summary, n1 = verifier.verify(str(out.get("summary", "")), set(allowed), list(allowed.values()), profile_vals)
                grounding += n1
                reasoning = out.get("reasoning") or {}
                for r in recs:
                    text = reasoning.get(r.practice_id)
                    if not text:
                        continue
                    ok_ids = per_rec_allowed[r.practice_id]
                    clean, n2 = verifier.verify(str(text), set(ok_ids) | set(allowed), list(allowed.values()), profile_vals)
                    grounding += n2
                    r.site_specific_reasoning = clean or None
                    for eid in verifier.cited_ids(clean):
                        if eid in store.chunks and eid not in {ref.evidence_id for ref in r.references}:
                            src = store.sources[store.chunks[eid]["source_id"]]
                            r.references.append(Reference(source_id=src["id"], citation=store.citation(src["id"]), url=src["url"],
                                                          tier=src["tier"], evidence_id=eid, excerpt=store.chunks[eid]["text"]))
        if not summary:
            summary = self._fallback_summary(findings, chains, recs)
        if llm.available() and not llm_used and recs:
            grounding.append("LLM unavailable for this turn; used deterministic reasoning text only.")

        # --- assumptions & transparency
        assumptions = []
        baseline = baseline_summary(p)
        if baseline:
            assumptions.append(baseline)
        missing = [label for label, _ in clarifier.missing(p)]
        if skip or len(known) < clarifier.MIN_VARIABLES:
            assumptions.append(f"Proceeding with {len(known)} known variable(s) at your request; confidence is reduced.")
        if missing:
            assumptions.append("Unknown: " + ", ".join(missing) + ". Providing these would sharpen the advice.")
        if p.rainfall_mm is not None and not p.climate_zone:
            assumptions.append("Rainfall bands (<600 mm low, 600–1000 moderate) are heuristic app thresholds, not a cited standard.")
        for field, prov in p.provenance.items():
            if prov.startswith("geo"):
                assumptions.append(f"{field} = {getattr(p, field)} was looked up ({prov[4:]}), not measured on site.")
        assumptions += mem.state.get("geo_notes", [])
        if changed and before.summary():
            diffs = [f"{k}: {getattr(before, k)} → {getattr(p, k)}" for k in changed
                     if getattr(before, k) not in (None, []) or any(k in pair and getattr(before, o) is not None
                                                                   for pair in SAME_VARIABLE for o in pair)]
            if diffs:
                assumptions.insert(0, "Updated from your last message — " + "; ".join(diffs) + ". Recommendations recalculated.")

        refs, seen = [], set()
        for r in recs:
            for ref in r.references:
                if ref.source_id not in seen:
                    seen.add(ref.source_id)
                    refs.append(ref)
        for f in findings:
            sid = store.chunks[f.evidence_id]["source_id"]
            if sid not in seen:
                seen.add(sid)
                refs.append(Reference(source_id=sid, citation=store.citation(sid), url=store.sources[sid]["url"],
                                      tier=store.sources[sid]["tier"], evidence_id=f.evidence_id))

        # Rank the remaining unknowns by how much they would actually change this advice.
        ranked = voi.rank_missing(store, p, clarifier.missing(p))
        mem.state["last_recs"] = [r.practice_id for r in recs]
        mem.state["last_findings"] = [f.code for f in findings]
        mem.state["clarify_rounds"] = 0
        return AssistantResponse(
            type="recommendations", message=summary, profile=p.summary(), known_variables=known,
            missing_variables=missing, diagnosis=findings, causal_chains=chains, recommendations=recs,
            assumptions=assumptions, retrieval=traces, references=refs, llm_used=llm_used,
            action_plan=build_plan(recs, findings),
            grounding_notes=grounding,
            question_value=ranked,
            clarifying_questions=[voi.phrase(item, len(recs)) for item in ranked[:2]] if missing else [])

    def _fallback_summary(self, findings, chains, recs) -> str:
        if not findings:
            return ("No threshold-level stressor was detected from the variables provided, so I can't justify a targeted "
                    "intervention yet. Share more site data (see questions below).")
        parts = ["Diagnosis: " + "; ".join(f.label for f in findings[:5]) + "."]
        if chains:
            parts.append("These interact: " + " | ".join(" → ".join(c.path) for c in chains[:3]) + ".")
        if recs:
            if any(f.code == "WATER_LIMITED" for f in findings):
                parts.append("Because water is the first limiting factor here, water-securing practices come first; "
                             "carbon- and habitat-building practices follow once soil moisture is protected.")
            parts.append("Each recommendation below targets at least two of these problems at once.")
        return " ".join(parts)

    # ------------------------------------------------------------------ follow-up answers
    PRACTICE_KEYWORDS = {
        "dryland_agroforestry": ["agroforestry", "tree", "khejri", "prosopis", "faidherbia"],
        "legume_intercrop_rotation": ["intercrop", "rotation", "legume", "chickpea", "pulse"],
        "conservation_ag_mulch": ["mulch", "no-till", "no till", "zero till", "tillage", "residue", "conservation agriculture"],
        "in_situ_water_harvesting": ["pond", "water harvest", "bund", "trench", "irrigat"],
        "organic_amendments": ["compost", "manure", "fym", "organic amendment"],
        "cover_crops": ["cover crop", "green manure"],
        "native_flower_margins": ["flower", "hedgerow", "hedge", "margin", "pollinator strip"],
        "habitat_share_20pct": ["20%", "semi-natural habitat", "habitat share"],
        "habitat_corridors": ["corridor", "connect"],
        "assisted_natural_regeneration": ["regeneration", "reforest", "natural regrowth"],
        "restore_open_ecosystem": ["grassland", "savanna"],
        "avoid_thirsty_plantations": ["eucalyptus", "plantation", "plant trees", "afforest"],
        "ipm_pesticide_reduction": ["pesticide", "ipm", "spray"],
        "nutrient_buffers": ["fertiliser", "fertilizer", "nitrogen", "buffer"],
        "lime_or_biochar_acidic": ["lime", "liming", "biochar"],
        "gypsum_sodic": ["gypsum", "sodic"],
    }

    def _mentioned_practices(self, lower: str) -> list[dict]:
        """Practices the user refers to, matched on curated keywords."""
        return [self.store.practices[pid] for pid, kws in self.PRACTICE_KEYWORDS.items()
                if pid in self.store.practices and any(k in lower for k in kws)]

    def _exclusion_reasons(self, practices: list[dict]) -> dict[str, str]:
        from darukaa.reasoning.recommender import score_practice

        p = self.memory.profile
        findings = diagnose(p)
        codes = {f.code: f.severity for f in findings}
        chosen = self.memory.state.get("last_recs", [])
        out = {}
        for pr in practices:
            score, _ = score_practice(pr, codes, p)
            addressed = [c for c in pr["addresses"] if c in codes]
            land_uses = pr["suits"].get("land_uses")
            reasons = []
            if any(c in codes for c in pr["avoid_when"]):
                reasons.append(f"it is contraindicated when {', '.join(c for c in pr['avoid_when'] if c in codes)}")
            if pr["water_penalty"] and "WATER_LIMITED" in codes:
                reasons.append("it consumes stored soil water, which is the first limiting factor on this site")
            if pr["requires"] and not all(c in codes for c in pr["requires"]):
                reasons.append(f"it is only needed when {', '.join(pr['requires'])} is diagnosed")
            if land_uses and p.land_use and p.land_use not in land_uses:
                reasons.append(f"it does not suit {p.land_use} (suits {', '.join(land_uses)})")
            if not reasons and pr["kind"] == "do" and len(addressed) < 2:
                reasons.append(f"it addresses only {len(addressed)} of the diagnosed problems (the engine requires ≥2)")
            if score > 0 and not reasons:
                reasons.append(f"it scored {score}, below the {len(chosen)} practices selected")
            out[pr["name"]] = "; ".join(reasons) + "."
        return out

    def _answer(self, message: str) -> AssistantResponse:
        p, mem, store = self.memory.profile, self.memory, self.store
        last = [store.practices[i] for i in mem.state.get("last_recs", []) if i in store.practices]
        lower = message.lower()
        focus = self._mentioned_practices(lower)
        exclusions = self._exclusion_reasons([pr for pr in focus if pr["id"] not in mem.state.get("last_recs", [])])
        query = f"{message} {_profile_text(p)} " + " ".join(pr["name"] for pr in (focus or last[:2]))
        domains = sorted(p.known_domains())
        hits = self.retriever.search(query, k=5, domains=domains)
        allowed = {h["chunk_id"]: h["text"] for h in hits}
        for pr in focus:
            for e in pr["effects"]:
                allowed[e["evidence_id"]] = store.chunks[e["evidence_id"]]["text"]
        trace = RetrievalTrace(query=query, filters={"domains": domains, "focus": [pr["id"] for pr in focus]},
                               hits=[RetrievalHit(**{k: h[k] for k in ("chunk_id", "source_id", "score", "dense_rank", "sparse_rank", "text")}, used_by=["answer"]) for h in hits])
        history = [m["content"][:400] for m in mem.history(6) if m["role"] == "user"]
        text, notes, used = "", [], False
        if llm.available():
            user = json.dumps({
                "question": message, "recent_user_messages": history, "site_profile": p.summary(),
                "diagnosis": mem.state.get("last_findings", []),
                "earlier_recommendations": [{"id": pr["id"], "name": pr["name"], "mechanism": pr["mechanism"], "tradeoffs": pr["tradeoffs"]} for pr in last],
                "practices_asked_about": [{"id": pr["id"], "name": pr["name"], "mechanism": pr["mechanism"],
                                           "adaptations": pr["adaptations"], "tradeoffs": pr["tradeoffs"]} for pr in focus],
                "why_not_recommended_by_rule_engine": exclusions,
                "evidence": allowed})
            raw = llm.chat(ANSWER_SYSTEM, user, max_tokens=500)
            if raw:
                used = True
                text, notes = verifier.verify(raw, set(allowed), list(allowed.values()), list(p.summary().values()))
        if not text:
            lines = [f"**Why {name} was not recommended:** {why}" for name, why in exclusions.items()]
            for pr in focus:
                lines.append(f"**{pr['name']}** — {pr['mechanism']}")
                codes = set(mem.state.get("last_findings", []))
                lines += [f"*Caution for your site:* {t}" for c, t in pr["adaptations"].items() if c in codes]
                if pr["tradeoffs"]:
                    lines.append("Trade-offs: " + " ".join(pr["tradeoffs"]))
            lines.append("Most relevant evidence from the knowledge base:")
            for h in hits[:3]:
                lines.append(f"- {h['text']} [{h['chunk_id']}]")
            text = "\n".join(lines)
        refs, seen = [], set()
        for eid in verifier.cited_ids(text) or list(allowed)[:3]:
            if eid in store.chunks:
                sid = store.chunks[eid]["source_id"]
                if sid not in seen:
                    seen.add(sid)
                    refs.append(Reference(source_id=sid, citation=store.citation(sid), url=store.sources[sid]["url"],
                                          tier=store.sources[sid]["tier"], evidence_id=eid, excerpt=store.chunks[eid]["text"]))
        return AssistantResponse(type="answer", message=text, profile=p.summary(), known_variables=p.known_variables(),
                                 retrieval=[trace], references=refs, llm_used=used, grounding_notes=notes)
