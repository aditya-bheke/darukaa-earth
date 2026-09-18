"""Persistent conversation memory (SQLite): per-session site profile, dialogue state and messages."""

import json
import uuid

from darukaa.kb.store import connect
from darukaa.schemas import SiteProfile


def list_sessions(limit: int = 30, conn=None) -> list[dict]:
    """Recent conversations, newest first, with a title taken from the first thing the user said."""
    conn = conn or connect()
    rows = conn.execute(
        """
        SELECT s.id, s.created_at, s.updated_at, s.profile,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,
               (SELECT m.content FROM messages m WHERE m.session_id = s.id AND m.role = 'user'
                ORDER BY m.id LIMIT 1) AS first_message
        FROM sessions s
        WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
        ORDER BY s.updated_at DESC LIMIT ?
        """,
        (limit,)).fetchall()
    out = []
    for r in rows:
        profile = json.loads(r["profile"]) if r["profile"] else {}
        out.append({
            "session_id": r["id"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "message_count": r["message_count"],
            "title": _title(r["first_message"], profile),
            "profile": {k: v for k, v in profile.items() if v not in (None, [], {}) and k != "provenance"},
        })
    return out


def _title(first_message: str | None, profile: dict) -> str:
    """A short label: the opening message, or the site itself if the user started with JSON."""
    text = " ".join((first_message or "").split())
    if text.startswith("```json") or not text:
        bits = [profile.get("crop"), profile.get("land_use"), profile.get("climate_zone")]
        label = ", ".join(str(b) for b in bits if b)
        return label or "Site data"
    return text[:70] + ("…" if len(text) > 70 else "")


def delete_session(session_id: str, conn=None) -> bool:
    conn = conn or connect()
    with conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        changed = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,)).rowcount
    return bool(changed)


class SessionMemory:
    def __init__(self, session_id: str | None = None, conn=None):
        self.conn = conn or connect()
        self.session_id = session_id or uuid.uuid4().hex[:12]
        row = self.conn.execute("SELECT profile, state FROM sessions WHERE id = ?", (self.session_id,)).fetchone()
        if row is None:
            with self.conn:
                self.conn.execute("INSERT INTO sessions (id) VALUES (?)", (self.session_id,))
            self.profile, self.state = SiteProfile(), {}
        else:
            self.profile = SiteProfile.model_validate_json(row["profile"]) if row["profile"] != "{}" else SiteProfile()
            self.state = json.loads(row["state"])

    def save(self) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET profile = ?, state = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (self.profile.model_dump_json(), json.dumps(self.state), self.session_id))

    def add_message(self, role: str, content: str, payload: dict | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO messages (session_id, role, content, payload) VALUES (?, ?, ?, ?)",
                (self.session_id, role, content, json.dumps(payload) if payload else None))

    def history(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content, payload FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (self.session_id, limit)).fetchall()
        return [{"role": r["role"], "content": r["content"], "payload": json.loads(r["payload"]) if r["payload"] else None}
                for r in reversed(rows)]

    def reset(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
        self.profile, self.state = SiteProfile(), {}
        self.save()
