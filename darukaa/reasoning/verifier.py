"""Grounding verifier for LLM-written text.

Rules applied sentence by sentence:
1. Every [citation] must be an evidence id the model was actually given.
2. Every number in a sentence must appear in the supplied evidence or in the user's profile.
Sentences that break a rule are removed and the removal is logged."""

import re

CITE = re.compile(r"[\[(]((?:ev|pdf)_[a-z0-9_]+(?:\s*[,;]\s*(?:ev|pdf)_[a-z0-9_]+)*)[\])]")
EVIDENCE_ID = re.compile(r"\b(?:ev|pdf)_[a-z0-9_]+")
NUMBER = re.compile(r"(?<![a-z_])\d+(?:\.\d+)?")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _numbers(text: str) -> set[str]:
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in NUMBER.findall(EVIDENCE_ID.sub("", text))}


def verify(text: str, allowed_ids: set[str], evidence_texts: list[str], profile_values: list) -> tuple[str, list[str]]:
    if not text:
        return "", []
    allowed_numbers = set()
    for t in evidence_texts:
        allowed_numbers |= _numbers(t)
    for v in profile_values:
        allowed_numbers |= _numbers(str(v))
    allowed_numbers |= {"1", "2", "3"}  # ordinal / list words rendered as digits

    kept, notes = [], []
    for sentence in SENTENCE.split(text.strip()):
        cited = set(_ids(sentence))
        bad_ids = cited - allowed_ids
        bad_nums = _numbers(sentence) - allowed_numbers
        if bad_ids:
            notes.append(f"removed sentence citing unknown evidence {sorted(bad_ids)}: \"{sentence[:90]}\"")
        elif bad_nums:
            notes.append(f"removed sentence with unsupported number(s) {sorted(bad_nums)}: \"{sentence[:90]}\"")
        else:
            kept.append(sentence)
    return normalise_citations(" ".join(kept)), notes


def _ids(text: str) -> list[str]:
    # any evidence-id-looking token counts, however the model bracketed it
    return EVIDENCE_ID.findall(text or "")


def normalise_citations(text: str) -> str:
    """Render citations consistently as [id, id]."""
    return CITE.sub(lambda m: "[" + m.group(1) + "]", text or "")


def cited_ids(text: str) -> list[str]:
    return list(dict.fromkeys(_ids(text)))
