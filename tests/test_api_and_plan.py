from fastapi.testclient import TestClient

from api import app
from darukaa.kb.store import get_store
from darukaa.reasoning.diagnosis import diagnose
from darukaa.reasoning.planner import build_plan
from darukaa.reasoning.recommender import recommend
from darukaa.schemas import SiteProfile

client = TestClient(app)
EXAMPLE = {"soil_organic_carbon": "0.3%", "rainfall": "low", "crop": "monoculture wheat", "region": "semi-arid"}


def test_health():
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["knowledge_base"]["practices"] >= 16


def test_chat_structured_then_follow_up_in_same_session():
    first = client.post("/chat", json={"site": EXAMPLE}).json()
    assert first["response"]["type"] == "recommendations"
    assert first["response"]["action_plan"]
    sid = first["session_id"]
    second = client.post("/chat", json={"message": "why not cover crops?", "session_id": sid}).json()
    assert second["response"]["type"] == "answer"
    history = client.get(f"/sessions/{sid}").json()
    assert history["profile"]["soil_organic_carbon_pct"] == 0.3
    assert len(history["messages"]) == 4


def test_chat_validation_and_unknown_session():
    assert client.post("/chat", json={}).status_code == 422
    assert client.post("/chat", json={"message": "hi", "session_id": "nope"}).status_code == 404


def test_knowledge_endpoints():
    hits = client.get("/knowledge/search", params={"q": "pond biodiversity", "k": 3}).json()
    assert len(hits) == 3
    assert all(p["monitoring"] for p in client.get("/knowledge/practices").json())


def test_plan_sequences_water_first_and_has_baseline():
    p = SiteProfile(soil_organic_carbon_pct=0.3, rainfall_level="low", crop="wheat", cropping_system="monoculture",
                    land_use="cropland", climate_zone="semi-arid")
    findings = diagnose(p)
    recs = recommend(get_store(), p, findings)
    plan = build_plan(recs, findings)
    assert plan[0].phase.startswith("0") and any("organic carbon" in a for a in plan[0].actions)
    assert "Residue mulch + reduced tillage + rotation (conservation agriculture package)" in plan[1].actions
    assert all(r.monitoring for r in recs)
    assert any("Keep avoiding" in a for a in plan[-1].actions)


def test_water_consuming_practice_excluded_in_drylands():
    p = SiteProfile(soil_organic_carbon_pct=0.6, climate_zone="semi-arid", crop="wheat", cropping_system="monoculture",
                    land_use="cropland", erosion=True)
    assert "cover_crops" not in [r.practice_id for r in recommend(get_store(), p, diagnose(p))]


def test_frontend_is_served():
    root = client.get("/", follow_redirects=False)
    assert root.status_code in (302, 307) and root.headers["location"] == "/app/"
    page = client.get("/app/")
    assert page.status_code == 200 and "Darukaa.Earth" in page.text
    for asset in ("/app/styles.css", "/app/app.js"):
        assert client.get(asset).status_code == 200


def test_session_history_carries_structured_payload():
    """The front end re-renders past turns after a reload, so payloads must round-trip."""
    first = client.post("/chat", json={"site": EXAMPLE}).json()
    history = client.get(f"/sessions/{first['session_id']}").json()
    assistant = [m for m in history["messages"] if m["role"] == "assistant"]
    assert assistant and assistant[-1]["payload"]["type"] == "recommendations"
    assert assistant[-1]["payload"]["action_plan"]


def test_old_payloads_still_validate_without_newer_fields():
    """Sessions saved before `projections` / `monitoring` existed must still load: the front end
    re-renders stored payloads, and a hard failure there used to wipe the conversation."""
    from darukaa.schemas import AssistantResponse

    legacy = {
        "type": "recommendations", "message": "### Assessment\nolder answer", "profile": {"soil_ph": 6.5},
        "known_variables": ["soil_ph"],
        "recommendations": [{
            "practice_id": "legacy", "title": "Old practice", "what_to_do": "do", "why_it_works": "because",
            "impacted_metrics": [], "time_horizon": "short", "confidence": "medium", "confidence_score": 0.6,
            "confidence_reason": "reason", "addresses": ["SOC_LOW"], "variables_linked": ["soil_organic_carbon"],
            "references": [], "score": 1.0,
        }],
    }
    resp = AssistantResponse.model_validate(legacy)
    assert resp.recommendations[0].projections == [] and resp.recommendations[0].monitoring == []
    assert resp.action_plan == [] and resp.question_value == []


def test_history_lists_titles_and_deletes():
    first = client.post("/chat", json={"message": "Biodiversity is declining on my land"}).json()
    sid = first["session_id"]
    items = client.get("/sessions?limit=50").json()
    mine = next(i for i in items if i["session_id"] == sid)
    assert mine["title"].startswith("Biodiversity is declining")
    assert mine["message_count"] == 2 and mine["updated_at"]

    json_started = client.post("/chat", json={"site": EXAMPLE}).json()["session_id"]
    titled = next(i for i in client.get("/sessions").json() if i["session_id"] == json_started)
    assert "wheat" in titled["title"]        # JSON-only start is named from the site, not "```json"

    assert client.delete(f"/sessions/{sid}").json() == {"deleted": sid}
    assert sid not in [i["session_id"] for i in client.get("/sessions?limit=50").json()]
    assert client.delete(f"/sessions/{sid}").status_code == 404


def test_rebuilding_the_knowledge_base_keeps_conversations():
    """The build drops and recreates knowledge tables; conversation history must survive it."""
    from darukaa.kb.build import build
    from darukaa.kb.store import connect
    from darukaa.memory import SessionMemory, list_sessions

    mem = SessionMemory("persist_check")
    mem.add_message("user", "Biodiversity is declining on my land")
    mem.add_message("assistant", "answer", {"type": "clarification"})
    mem.save()
    before = len(list_sessions(100))

    build(verbose=False)

    assert len(list_sessions(100)) == before
    conn = connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", ("persist_check",)).fetchone()[0] == 2
    finally:
        conn.close()
