"""Knowledge-base build pipeline.

    python -m darukaa.kb.build            # (re)build SQLite + vector index

Steps: load curated YAML (sources, evidence, practices, relationships) -> validate every
cross-reference -> ingest optional PDFs from data/raw -> write SQLite -> embed chunks.
"""

import hashlib
import json
import re
import sys

import yaml

from darukaa import config
from darukaa.kb.store import connect, reset_knowledge_tables

CHUNK_WORDS = 180
CHUNK_OVERLAP = 40


def _load(name: str):
    with open(config.KNOWLEDGE_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _fingerprint() -> str:
    h = hashlib.sha256()
    files = sorted(config.KNOWLEDGE_DIR.glob("*.yaml")) + sorted(config.RAW_DIR.glob("*.pdf")) + sorted(config.RAW_DIR.glob("*.yaml"))
    for path in files:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def validate(sources, evidence, practices, relationships) -> None:
    """Fail loudly if any citation points at something that does not exist."""
    source_ids = {s["id"] for s in sources}
    evidence_ids = {e["id"] for e in evidence}
    errors = []
    for e in evidence:
        if e["source"] not in source_ids:
            errors.append(f"evidence {e['id']} -> unknown source {e['source']}")
    for p in practices:
        if not p.get("effects"):
            errors.append(f"practice {p['id']} has no effects")
        if not p.get("monitoring"):
            errors.append(f"practice {p['id']} has no monitoring indicators")
        proj = p.get("projection")
        if proj:
            if proj.get("evidence") not in evidence_ids:
                errors.append(f"practice {p['id']} projection -> unknown evidence {proj.get('evidence')}")
            if proj.get("kind") not in ("relative_pct", "rate_t_ha_yr"):
                errors.append(f"practice {p['id']} projection has unknown kind {proj.get('kind')}")
        for eff in p.get("effects", []):
            if eff["evidence"] not in evidence_ids:
                errors.append(f"practice {p['id']} -> unknown evidence {eff['evidence']}")
            if eff["horizon"] not in ("short", "medium", "long"):
                errors.append(f"practice {p['id']} bad horizon {eff['horizon']}")
    for r in relationships:
        if r["evidence"] not in evidence_ids:
            errors.append(f"relationship {r['from']}->{r['to']} -> unknown evidence {r['evidence']}")
    if errors:
        raise ValueError("Knowledge base validation failed:\n  " + "\n  ".join(errors))


def chunk_text(text: str, words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    tokens = text.split()
    chunks, start = [], 0
    while start < len(tokens):
        chunks.append(" ".join(tokens[start:start + words]))
        if start + words >= len(tokens):
            break
        start += words - overlap
    return chunks


DOMAIN_KEYWORDS = {
    "soil": ["soil", "organic carbon", "ph", "tillage", "compost"],
    "land_use": ["land use", "land cover", "cropland", "agroforestry", "plantation"],
    "biodiversity": ["biodiversity", "species", "habitat", "pollinator"],
    "climate": ["temperature", "rainfall", "precipitation", "drought", "climate"],
    "human_impact": ["pollution", "pesticide", "deforestation", "nitrogen"],
    "water": ["water", "irrigation", "runoff", "moisture"],
}


MIN_CHUNK_WORDS = 70


def is_useful_chunk(piece: str) -> bool:
    """Drop the debris of PDF extraction: page furniture, reference lists, figure/table dumps."""
    words = piece.split()
    if len(words) < MIN_CHUNK_WORDS:
        return False
    letters = sum(c.isalpha() or c.isspace() for c in piece)
    if letters / max(len(piece), 1) < 0.78:          # mostly digits/symbols: tables, indices
        return False
    long_words = sum(1 for w in words if len(w) > 3)
    if long_words / len(words) < 0.45:               # citation strings, axis labels
        return False
    lower = piece.lower()
    if lower.count("et al.") > 4 or lower.count("doi") > 2:
        return False                                  # reference list
    return True


def _pdf_fingerprint(pdfs: list) -> str:
    h = hashlib.sha256()
    for path in pdfs:
        h.update(path.name.encode())
        h.update(str(path.stat().st_size).encode())
        sidecar = path.with_suffix(".yaml")
        if sidecar.exists():
            h.update(sidecar.read_bytes())
    return h.hexdigest()[:16]


def ingest_pdfs() -> tuple[list[dict], list[dict]]:
    """Chunk PDFs in data/raw. A sidecar `<name>.yaml` may give citation metadata.

    Text extraction is the slow part (tens of seconds per report), so the result is cached and
    reused until the PDF set or its citation metadata changes."""
    sources, chunks = [], []
    pdfs = sorted(config.RAW_DIR.glob("*.pdf"))
    if not pdfs:
        return sources, chunks

    cache_path = config.INDEX_DIR / "pdf_chunks.json"
    fingerprint = _pdf_fingerprint(pdfs)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                print(f"  reusing extracted text for {len(pdfs)} PDFs ({len(cached['chunks'])} chunks)")
                return cached["sources"], cached["chunks"]
        except (json.JSONDecodeError, KeyError):
            pass
    import logging

    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding chatter, not our concern

    for pdf in pdfs:
        meta_path = pdf.with_suffix(".yaml")
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        source_id = meta.get("id") or re.sub(r"[^a-z0-9]+", "_", pdf.stem.lower())
        sources.append({
            "id": source_id,
            "title": meta.get("title", pdf.stem),
            "authors": meta.get("authors", "Unknown"),
            "publisher": meta.get("publisher", "Indexed PDF"),
            "year": meta.get("year"),
            "type": meta.get("type", "report"),
            "tier": meta.get("tier", 2),
            "url": meta.get("url"),
        })
        text = " ".join((page.extract_text() or "") for page in PdfReader(pdf).pages)
        text = re.sub(r"\s+", " ", text)
        kept, seen, total = 0, set(), 0
        for i, piece in enumerate(chunk_text(text)):
            total += 1
            if not is_useful_chunk(piece):
                continue
            lower = piece.lower()
            domains = [d for d, kws in DOMAIN_KEYWORDS.items() if any(k in lower for k in kws)]
            if not domains:          # off-topic pages: forewords, acknowledgements, annexes
                continue
            key = lower[:90]
            if key in seen:          # repeated headers/footers
                continue
            seen.add(key)
            chunks.append({
                "id": f"pdf_{source_id}_{i:04d}",
                "source": source_id,
                "origin": "pdf",
                "domains": domains,
                "variables": [],
                "text": piece,
            })
            kept += 1
        print(f"  ingested {pdf.name}: {kept} chunks kept of {total}")
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"fingerprint": fingerprint, "sources": sources, "chunks": chunks}), encoding="utf-8")
    return sources, chunks


def build(verbose: bool = True) -> None:
    log = print if verbose else (lambda *a, **k: None)
    sources = _load("sources.yaml")
    evidence = _load("evidence.yaml")
    practices = _load("practices.yaml")
    relationships = _load("relationships.yaml")
    validate(sources, evidence, practices, relationships)
    log(f"validated: {len(sources)} sources, {len(evidence)} passages, {len(practices)} practices, {len(relationships)} relationships")

    pdf_sources, pdf_chunks = ingest_pdfs()
    known = {s["id"] for s in sources}
    sources += [s for s in pdf_sources if s["id"] not in known]
    for e in evidence:
        e.setdefault("origin", "curated")
        e["text"] = " ".join(e["text"].split())
    all_chunks = evidence + pdf_chunks

    conn = connect()
    reset_knowledge_tables(conn)
    with conn:
        conn.executemany(
            "INSERT INTO sources VALUES (:id, :title, :authors, :publisher, :year, :type, :tier, :url)", sources)
        conn.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)",
            [(c["id"], c["source"], c["origin"], json.dumps(c["domains"]), json.dumps(c["variables"]), c["text"]) for c in all_chunks])
        evidence_source = {c["id"]: c["source"] for c in all_chunks}
        for p in practices:
            conn.execute(
                "INSERT INTO practices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p["id"], p["name"], p.get("kind", "do"), " ".join(p["action"].split()), " ".join(p["mechanism"].split()),
                 json.dumps(p.get("addresses", {})), json.dumps(p.get("suits") or {}), json.dumps(p.get("requires", [])),
                 json.dumps(p.get("avoid_when", [])),
                 json.dumps({k: " ".join(v.split()) for k, v in (p.get("adaptations") or {}).items()}),
                 json.dumps(p.get("tradeoffs", [])), json.dumps(p.get("variables_linked", [])),
                 json.dumps(p.get("monitoring", [])),
                 json.dumps(p["projection"]) if p.get("projection") else None,
                 p.get("water_penalty", 0)))
            for eff in p["effects"]:
                conn.execute(
                    "INSERT INTO practice_effects (practice_id, metric, direction, estimate, horizon, evidence_id, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (p["id"], eff["metric"], eff["direction"], eff["estimate"], eff["horizon"], eff["evidence"], evidence_source[eff["evidence"]]))
        conn.executemany(
            "INSERT INTO relationships (from_var, to_var, sign, mechanism, evidence_id) VALUES (?, ?, ?, ?, ?)",
            [(r["from"], r["to"], r["sign"], r["mechanism"], r["evidence"]) for r in relationships])
    conn.close()
    log(f"sqlite written: {config.DB_PATH}")

    from darukaa.kb.vector import build_index, index_is_current

    if index_is_current([c["id"] for c in all_chunks], _fingerprint()):
        log(f"vector index reused: {config.INDEX_DIR} ({len(all_chunks)} chunks, corpus unchanged)")
    else:
        build_index([(c["id"], c["text"]) for c in all_chunks])
        (config.INDEX_DIR / "fingerprint").write_text(_fingerprint())
        log(f"vector index written: {config.INDEX_DIR} ({len(all_chunks)} chunks)")


def ensure_built() -> None:
    marker = config.INDEX_DIR / "fingerprint"
    if not config.DB_PATH.exists() or not marker.exists() or marker.read_text() != _fingerprint():
        build(verbose=False)


if __name__ == "__main__":
    try:
        build()
    except ValueError as exc:
        print(exc)
        sys.exit(1)
