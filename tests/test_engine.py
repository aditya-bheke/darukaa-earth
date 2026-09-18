from darukaa.engine import Engine
from darukaa.memory import SessionMemory


def test_vague_message_triggers_targeted_questions():
    resp = Engine().handle("Biodiversity is declining on my land")
    assert resp.type == "clarification"
    joined = " ".join(resp.clarifying_questions).lower()
    assert "organic carbon" in joined and "rainfall" in joined and "land use" in joined


def test_multi_turn_memory_persists_across_engine_instances():
    first = Engine()
    first.handle("Biodiversity is declining on my land")
    first.handle("Soil organic carbon is 0.3%, rainfall is low, wheat monoculture, semi-arid")

    reloaded = SessionMemory(first.session_id)
    assert reloaded.profile.species_richness_trend == "declining"
    assert reloaded.profile.soil_organic_carbon_pct == 0.3
    assert len(reloaded.history()) == 4


def test_structured_json_input_goes_straight_to_recommendations():
    resp = Engine().handle("", {"soil_organic_carbon": "0.3%", "rainfall": "low", "crop": "monoculture wheat", "region": "semi-arid"})
    assert resp.type == "recommendations"
    assert resp.retrieval and resp.retrieval[0].hits  # retrieval is exposed
    assert resp.references
    assert "Assessment" in resp.message


def test_follow_up_question_explains_exclusion():
    e = Engine()
    e.handle("", {"soil_organic_carbon": 0.3, "rainfall": "low", "crop": "monoculture wheat", "region": "semi-arid"})
    resp = e.handle("Why not cover crops?")
    assert resp.type == "answer"
    assert "water" in resp.message.lower()


def test_skip_proceeds_with_reduced_confidence():
    e = Engine()
    e.handle("Biodiversity is declining on my wheat farm")
    resp = e.handle("not sure, just recommend")
    assert resp.type == "recommendations" and resp.recommendations
    assert any("confidence is reduced" in a for a in resp.assumptions)


def test_questions_do_not_become_site_data():
    """A question is a request about the advice, not a fact about the land."""
    from darukaa.reasoning.profile_parser import looks_like_a_question

    assert looks_like_a_question("Why not cover crops?")
    assert looks_like_a_question("Should I add lime?")
    assert not looks_like_a_question("Soil carbon is 0.3%")
    assert not looks_like_a_question("not sure, just recommend")

    e = Engine()
    e.handle("Soil organic carbon 0.3%, rainfall 350 mm, monoculture wheat, semi-arid")
    for question in ("Why not cover crops?", "Should I add lime?", "what about the pond?"):
        assert e.handle(question).type == "answer", question
    assert e.memory.profile.goal is None          # the question's subject is not a goal
    assert e.handle("Actually rainfall is 1200 mm").type == "recommendations"   # real data still recomputes
