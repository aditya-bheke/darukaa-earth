"""Behavioural evaluation of the whole engine.

    python eval/run_eval.py            # uses the configured LLM (if any)
    python eval/run_eval.py --no-llm   # deterministic mode (what CI runs)

Besides scenario expectations, every recommendation response is checked against the
challenge's mandatory output contract (see GLOBAL CHECKS below)."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GENERIC_PHRASES = ["sustainable practices", "be more sustainable", "protect the environment"]


def global_checks(resp, store) -> list[str]:
    """Contract from the brief: what/why/metric/reference, horizon, ≥3 variables, grounded citations."""
    errors = []
    if resp.type != "recommendations":
        return errors
    if len(resp.known_variables) < 3 and not any("confidence is reduced" in a for a in resp.assumptions):
        errors.append("reasoned with <3 variables without saying so")
    if not resp.recommendations:
        errors.append("no recommendations")
    for r in resp.recommendations:
        if not (r.what_to_do and r.why_it_works and r.impacted_metrics and r.references):
            errors.append(f"{r.practice_id}: missing what/why/metric/reference")
        prerequisite = bool(store.practices[r.practice_id]["requires"])
        if r.kind == "do" and len(r.addresses) < 2 and not (r.screening or prerequisite):
            errors.append(f"{r.practice_id}: single-issue recommendation")
        if len(r.variables_linked) < 2:
            errors.append(f"{r.practice_id}: links <2 variables")
        for ref in r.references:
            if ref.source_id not in store.sources or ref.evidence_id not in store.chunks:
                errors.append(f"{r.practice_id}: dangling reference {ref.source_id}/{ref.evidence_id}")
        for m in r.impacted_metrics:
            if m.evidence_id not in store.chunks:
                errors.append(f"{r.practice_id}: metric without evidence")
        text = (r.what_to_do + r.why_it_works + (r.site_specific_reasoning or "")).lower()
        errors += [f"{r.practice_id}: generic phrase '{g}'" for g in GENERIC_PHRASES if g in text]
    all_vars = {v for r in resp.recommendations for v in r.variables_linked}
    if len(all_vars) < 3:
        errors.append(f"response links only {len(all_vars)} variables overall")
    return errors


def check(resp, exp: dict) -> list[str]:
    errors = []
    ids = [r.practice_id for r in resp.recommendations]
    codes = {f.code for f in resp.diagnosis}
    if "type" in exp and resp.type != exp["type"]:
        errors.append(f"type {resp.type} != {exp['type']}")
    for c in exp.get("codes", []):
        if c not in codes:
            errors.append(f"missing diagnosis {c} (got {sorted(codes)})")
    for c in exp.get("not_codes", []):
        if c in codes:
            errors.append(f"unexpected diagnosis {c}")
    if exp.get("include_any") and not set(exp["include_any"]) & set(ids):
        errors.append(f"none of {exp['include_any']} in {ids}")
    for pid in exp.get("include_all", []):
        if pid not in ids:
            errors.append(f"{pid} not recommended (got {ids})")
    for pid in exp.get("exclude", []):
        if pid in ids:
            errors.append(f"{pid} should not be recommended")
    if exp.get("first") and (not ids or ids[0] not in exp["first"]):
        errors.append(f"first recommendation {ids[:1]} not in {exp['first']}")
    qs = " ".join(resp.clarifying_questions).lower()
    for word in exp.get("questions_mention", []):
        if word.lower() not in qs:
            errors.append(f"questions do not ask about '{word}'")
    for word in exp.get("message_mentions", []):
        if word.lower() not in resp.message.lower():
            errors.append(f"message does not mention '{word}'")
    for word in exp.get("assumption_mentions", []):
        if not any(word.lower() in a.lower() for a in resp.assumptions):
            errors.append(f"assumptions do not mention '{word}'")
    for field in exp.get("profile_has", []):
        if field not in resp.profile:
            errors.append(f"memory lost '{field}'")
    return errors


def run(no_llm: bool) -> int:
    if no_llm:
        os.environ["LLM_PROVIDER"] = "none"
    os.environ["GEO_ENABLED"] = "false"
    os.environ.setdefault("DARUKAA_DB_PATH", str(Path(tempfile.mkdtemp()) / "eval.db"))
    import yaml

    from darukaa.engine import Engine
    from darukaa.kb.store import get_store

    store = get_store()
    scenarios = yaml.safe_load((ROOT / "eval" / "scenarios.yaml").read_text(encoding="utf-8"))
    failed, n_recs, n_links, n_cites, grounding_removed = 0, 0, 0, 0, 0
    for sc in scenarios:
        engine = Engine()
        errors = []
        resp = None
        for turn in sc["turns"]:
            resp = engine.handle(turn.get("text", ""), turn.get("json"))
            errors += global_checks(resp, store)
            if "expect" in turn:
                errors += [f"(turn '{turn.get('text', 'json')[:30]}') {e}" for e in check(resp, turn["expect"])]
            grounding_removed += sum("removed" in n for n in resp.grounding_notes)
        errors += check(resp, sc["expect"])
        if resp.type == "recommendations":
            n_recs += len(resp.recommendations)
            n_links += sum(len(r.variables_linked) for r in resp.recommendations)
            n_cites += sum(len(r.references) for r in resp.recommendations)
        status = "PASS" if not errors else "FAIL"
        failed += bool(errors)
        print(f"[{status}] {sc['name']}")
        for e in errors:
            print(f"        - {e}")
    total = len(scenarios)
    print(f"\n{total - failed}/{total} scenarios passed")
    if n_recs:
        print(f"avg variables linked per recommendation: {n_links / n_recs:.1f}")
        print(f"avg references per recommendation:       {n_cites / n_recs:.1f}")
    print(f"LLM sentences removed by grounding verifier: {grounding_removed}")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(run(parser.parse_args().no_llm))
