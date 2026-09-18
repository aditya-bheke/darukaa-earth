"""SQLite knowledge store: sources, evidence chunks, structured practice effects,
the variable-relationship graph, and conversation memory."""

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from darukaa import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT,
    publisher TEXT,
    year INTEGER,
    type TEXT,
    tier INTEGER NOT NULL,
    url TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    origin TEXT NOT NULL,              -- 'curated' | 'pdf'
    domains TEXT NOT NULL,             -- JSON list
    variables TEXT NOT NULL,           -- JSON list
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS practices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'do',
    action TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    addresses TEXT NOT NULL,           -- JSON {issue_code: weight}
    suits TEXT NOT NULL,               -- JSON {land_uses: [...]}
    requires TEXT NOT NULL,            -- JSON list of issue codes
    avoid_when TEXT NOT NULL,          -- JSON list of issue codes
    adaptations TEXT NOT NULL,         -- JSON {issue_code: text}
    tradeoffs TEXT NOT NULL,           -- JSON list
    variables_linked TEXT NOT NULL,    -- JSON list
    monitoring TEXT NOT NULL DEFAULT '[]', -- JSON [{indicator, method, frequency}]
    projection TEXT,                   -- JSON {metric, kind, low, high, years, evidence} or NULL
    water_penalty INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS practice_effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id TEXT NOT NULL REFERENCES practices(id),
    metric TEXT NOT NULL,
    direction TEXT NOT NULL,
    estimate TEXT NOT NULL,
    horizon TEXT NOT NULL,
    evidence_id TEXT NOT NULL REFERENCES chunks(id),
    source_id TEXT NOT NULL REFERENCES sources(id)
);
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_var TEXT NOT NULL,
    to_var TEXT NOT NULL,
    sign TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    evidence_id TEXT NOT NULL REFERENCES chunks(id)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    profile TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_effects_practice ON practice_effects(practice_id);
"""

KNOWLEDGE_TABLES = ["practice_effects", "relationships", "practices", "chunks", "sources"]


def reset_knowledge_tables(conn: sqlite3.Connection) -> None:
    """Drop and recreate knowledge tables (schema may have changed). Conversation tables are kept."""
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in KNOWLEDGE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA foreign_keys = ON")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


class KnowledgeStore:
    """Read access to the structured knowledge, cached in memory after first load."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.sources = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM sources")}
        self.chunks = {}
        for r in conn.execute("SELECT * FROM chunks"):
            row = dict(r)
            row["domains"] = json.loads(row["domains"])
            row["variables"] = json.loads(row["variables"])
            self.chunks[row["id"]] = row
        self.practices = {}
        for r in conn.execute("SELECT * FROM practices"):
            row = dict(r)
            for key in ("addresses", "suits", "requires", "avoid_when", "adaptations", "tradeoffs", "variables_linked", "monitoring"):
                row[key] = json.loads(row[key])
            row["projection"] = json.loads(row["projection"]) if row["projection"] else None
            row["effects"] = []
            self.practices[row["id"]] = row
        for r in conn.execute("SELECT * FROM practice_effects ORDER BY id"):
            self.practices[r["practice_id"]]["effects"].append(dict(r))
        self.relationships = [dict(r) for r in conn.execute("SELECT * FROM relationships")]

    def citation(self, source_id: str) -> str:
        s = self.sources[source_id]
        return f"{s['authors']} ({s['year']}). {s['title']}. {s['publisher']}."

    def stats(self) -> dict:
        return {
            "sources": len(self.sources),
            "chunks": len(self.chunks),
            "pdf_chunks": sum(1 for c in self.chunks.values() if c["origin"] == "pdf"),
            "practices": len(self.practices),
            "effects": sum(len(p["effects"]) for p in self.practices.values()),
            "relationships": len(self.relationships),
        }


@lru_cache(maxsize=1)
def get_store() -> KnowledgeStore:
    from darukaa.kb.build import ensure_built

    ensure_built()
    return KnowledgeStore(connect())
