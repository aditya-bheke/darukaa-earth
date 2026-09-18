"""REST API for programmatic / structured access.

    uvicorn api:app --reload        # docs at http://localhost:8000/docs
"""

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from darukaa import __version__, config, llm
from darukaa.config import ROOT
from darukaa.engine import Engine
from darukaa.kb.store import connect, get_store
from darukaa.kb.vector import get_retriever
from darukaa.memory import SessionMemory, delete_session, list_sessions
from darukaa.schemas import AssistantResponse

app = FastAPI(
    title="Darukaa.Earth AI Environmental Scientist",
    version=__version__,
    description="Knowledge-grounded, multi-variable biodiversity recommendations. "
                "Send free text, structured site data, or both; reuse `session_id` for multi-turn memory.",
)


class ChatRequest(BaseModel):
    message: str = Field("", description="Free-text user message")
    site: dict[str, Any] | None = Field(None, description="Structured site data (exact SiteProfile fields or loose keys)",
                                        examples=[{"soil_organic_carbon": "0.3%", "rainfall": "low",
                                                   "crop": "monoculture wheat", "region": "semi-arid"}])
    session_id: str | None = Field(None, description="Omit to start a new session")


class ChatResponse(BaseModel):
    session_id: str
    response: AssistantResponse


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "llm": config.LLM_MODEL if llm.available() else None,
            "knowledge_base": get_store().stats()}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip() and not req.site:
        raise HTTPException(422, "Provide `message`, `site`, or both.")
    if req.session_id and not _session_exists(req.session_id):
        raise HTTPException(404, f"Unknown session {req.session_id}")
    engine = Engine(req.session_id)
    resp = engine.handle(req.message, req.site)
    return ChatResponse(session_id=engine.session_id, response=resp)


@app.get("/sessions")
def sessions(limit: int = 30):
    """Conversation history: recent sessions, newest first."""
    return list_sessions(min(max(limit, 1), 100))


@app.delete("/sessions/{session_id}")
def forget(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(404, f"Unknown session {session_id}")
    return {"deleted": session_id}


@app.get("/sessions/{session_id}")
def session(session_id: str):
    if not _session_exists(session_id):
        raise HTTPException(404, f"Unknown session {session_id}")
    mem = SessionMemory(session_id)
    conn = connect()
    try:
        row = conn.execute("SELECT created_at, updated_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    # `payload` carries the full structured response so a client can re-render past turns.
    return {"session_id": session_id, "profile": mem.profile.summary(), "provenance": mem.profile.provenance,
            "created_at": row["created_at"] if row else None, "updated_at": row["updated_at"] if row else None,
            "messages": mem.history(100)}


@app.get("/knowledge/search")
def search(q: str, k: int = 5):
    return get_retriever().search(q, k=min(max(k, 1), 20))


@app.get("/knowledge/practices")
def practices():
    return [{k: p[k] for k in ("id", "name", "kind", "action", "mechanism", "addresses", "requires", "avoid_when",
                               "effects", "monitoring")} for p in get_store().practices.values()]


def _session_exists(session_id: str) -> bool:
    conn = connect()
    try:
        return conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is not None
    finally:
        conn.close()


@app.middleware("http")
async def revalidate_frontend(request, call_next):
    """Front-end assets must revalidate: a cached app.js/styles.css after a deploy (or during a demo)
    silently serves the old UI. ETags keep the cost to a 304."""
    response = await call_next(request)
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# The single-page front end (Apple-style fluid UI) is served from /app; "/" redirects to it.
FRONTEND = ROOT / "frontend"
if FRONTEND.is_dir():
    app.mount("/app", StaticFiles(directory=FRONTEND, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    def index():
        return RedirectResponse("/app/")
