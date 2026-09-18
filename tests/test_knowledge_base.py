import pytest
import yaml

from darukaa import config
from darukaa.kb.build import validate
from darukaa.kb.store import get_store
from darukaa.kb.vector import get_retriever


def _load(name):
    return yaml.safe_load((config.KNOWLEDGE_DIR / name).read_text(encoding="utf-8"))


def test_curated_knowledge_is_internally_consistent():
    validate(_load("sources.yaml"), _load("evidence.yaml"), _load("practices.yaml"), _load("relationships.yaml"))


def test_validation_rejects_dangling_citation():
    evidence = [{"id": "ev_x", "source": "missing_source", "text": "t"}]
    with pytest.raises(ValueError, match="unknown source"):
        validate([], evidence, [], [])


def test_every_domain_from_the_brief_is_covered():
    store = get_store()
    domains = {d for c in store.chunks.values() for d in c["domains"]}
    assert {"soil", "land_use", "biodiversity", "climate", "human_impact"} <= domains


def test_every_practice_effect_is_evidence_backed():
    store = get_store()
    for p in store.practices.values():
        assert p["effects"], p["id"]
        for e in p["effects"]:
            assert e["evidence_id"] in store.chunks
            assert e["source_id"] in store.sources


def test_hybrid_retrieval_finds_the_relevant_passage():
    hits = get_retriever().search("do cover crops use soil water in dry semi-arid farms", k=3)
    assert "ev_unger_cover_water" in [h["chunk_id"] for h in hits]
    assert all(h["dense_rank"] and h["sparse_rank"] for h in hits)


def test_retrieval_exclusion_filter():
    hits = get_retriever().search("cover crops soil water", k=5, exclude={"ev_unger_cover_water"})
    assert "ev_unger_cover_water" not in [h["chunk_id"] for h in hits]


def test_indexed_pdfs_are_cited_and_searchable():
    """PDFs in data/raw (fetched by scripts/fetch_sources.py) are optional, but if present they must
    carry a real citation, not a filename."""
    store = get_store()
    pdf_chunks = [c for c in store.chunks.values() if c["origin"] == "pdf"]
    if not pdf_chunks:
        pytest.skip("no PDFs indexed (run scripts/fetch_sources.py)")
    for chunk in pdf_chunks[:20]:
        src = store.sources[chunk["source_id"]]
        assert src["publisher"] != "Indexed PDF" and src["year"]


def test_retrieval_returns_diverse_passages():
    hits = get_retriever().search("soil organic carbon sequestration in croplands", k=5)
    assert len({h["source_id"] for h in hits}) >= 3   # MMR should avoid k near-duplicates
