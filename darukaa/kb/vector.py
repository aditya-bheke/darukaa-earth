"""Hybrid retriever: dense embeddings (fastembed, ONNX) + BM25, fused with
reciprocal rank fusion, then boosted by metadata (domain/variable) matches."""

import json
import re
import zlib
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from darukaa import config

RRF_K = 60
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
STOPWORDS = set("the a an and or of to in on for by with is are be as at that this from it its into than can".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


class _HashEmbedder:
    """Dependency-free fallback used only if the ONNX model cannot be loaded."""

    name = "hashing-bow-512"

    def embed(self, texts):
        out = np.zeros((len(texts), 512), dtype=np.float32)
        for i, text in enumerate(texts):
            for tok in tokenize(text):
                out[i, zlib.crc32(tok.encode()) % 512] += 1.0
        return out


class _FastEmbedder:
    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self.name = model_name
        self.model = TextEmbedding(model_name=model_name)

    def embed(self, texts):
        return np.array(list(self.model.embed(list(texts))), dtype=np.float32)


@lru_cache(maxsize=1)
def get_embedder():
    try:
        return _FastEmbedder(config.EMBEDDING_MODEL)
    except Exception as exc:  # offline / unsupported platform
        print(f"[vector] falling back to hashing embedder: {exc}")
        return _HashEmbedder()


def _normalise(m: np.ndarray) -> np.ndarray:
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)


def build_index(items: list[tuple[str, str]]) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    embedder = get_embedder()
    ids = [i for i, _ in items]
    vectors = _normalise(embedder.embed([t for _, t in items]))
    np.save(config.INDEX_DIR / "vectors.npy", vectors)
    (config.INDEX_DIR / "meta.json").write_text(json.dumps({"ids": ids, "embedder": embedder.name}))


def index_is_current(chunk_ids: list[str], fingerprint: str) -> bool:
    """True when the stored index already covers exactly this corpus (skips re-embedding).

    The SQLite database is per-instance (tests use a temp copy) but the embedding index is shared
    and content-addressed, so a rebuild of the database alone should not re-embed 500+ passages."""
    meta_path = config.INDEX_DIR / "meta.json"
    marker = config.INDEX_DIR / "fingerprint"
    if not (meta_path.exists() and marker.exists() and (config.INDEX_DIR / "vectors.npy").exists()):
        return False
    if marker.read_text() != fingerprint:
        return False
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        return False
    return meta.get("ids") == chunk_ids and meta.get("embedder") == get_embedder().name


class HybridRetriever:
    def __init__(self, store):
        self.store = store
        meta = json.loads((config.INDEX_DIR / "meta.json").read_text())
        self.ids = meta["ids"]
        self.embedder_name = meta["embedder"]
        self.vectors = np.load(config.INDEX_DIR / "vectors.npy")
        self.bm25 = BM25Okapi([tokenize(store.chunks[i]["text"]) for i in self.ids])

    def _embedder(self):
        emb = get_embedder()
        if emb.name != self.embedder_name:  # index built with a different embedder
            raise RuntimeError(f"index embedder {self.embedder_name} != runtime {emb.name}; rebuild the index")
        return emb

    def _mmr(self, results: list[dict], k: int, lam: float = 0.72) -> list[dict]:
        """Maximal marginal relevance: keep relevance but drop near-duplicate passages."""
        index = {cid: i for i, cid in enumerate(self.ids)}
        picked: list[dict] = []
        pool = results[: max(k * 4, 12)]
        while pool and len(picked) < k:
            best, best_score = None, -1e9
            for cand in pool:
                sim = 0.0
                if picked:
                    cv = self.vectors[index[cand["chunk_id"]]]
                    sim = max(float(cv @ self.vectors[index[p["chunk_id"]]]) for p in picked)
                score = lam * cand["score"] - (1 - lam) * sim * 1000
                if score > best_score:
                    best, best_score = cand, score
            picked.append(best)
            pool.remove(best)
        return picked

    def search(self, query: str, k: int = 6, domains: list[str] | None = None,
               variables: list[str] | None = None, exclude: set[str] | None = None,
               diversify: bool = True) -> list[dict]:
        exclude = exclude or set()
        q = _normalise(self._embedder().embed([query]))[0]
        dense = self.vectors @ q
        sparse = self.bm25.get_scores(tokenize(query))
        dense_rank = {self.ids[i]: r for r, i in enumerate(np.argsort(-dense))}
        sparse_rank = {self.ids[i]: r for r, i in enumerate(np.argsort(-sparse))}

        results = []
        for idx, cid in enumerate(self.ids):
            if cid in exclude:
                continue
            chunk = self.store.chunks[cid]
            score = 1 / (RRF_K + dense_rank[cid]) + 1 / (RRF_K + sparse_rank[cid])
            # metadata boost: reward passages tagged with the user's domains / variables
            if domains and set(domains) & set(chunk["domains"]):
                score *= 1 + 0.05 * len(set(domains) & set(chunk["domains"]))
            if variables and set(variables) & set(chunk["variables"]):
                score *= 1 + 0.08 * len(set(variables) & set(chunk["variables"]))
            # evidence strength: prefer assessments / meta-analyses
            tier = self.store.sources[chunk["source_id"]]["tier"]
            score *= {1: 1.1, 2: 1.0, 3: 0.95}.get(tier, 1.0)
            results.append({
                "chunk_id": cid,
                "source_id": chunk["source_id"],
                "score": round(score * 1000, 3),
                "dense_rank": dense_rank[cid] + 1,
                "sparse_rank": sparse_rank[cid] + 1,
                "text": chunk["text"],
                "dense_sim": float(dense[idx]),
            })
        results.sort(key=lambda r: -r["score"])
        return self._mmr(results, k) if diversify and len(results) > k else results[:k]


@lru_cache(maxsize=1)
def get_retriever():
    from darukaa.kb.store import get_store

    return HybridRetriever(get_store())
