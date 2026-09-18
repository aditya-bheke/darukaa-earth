import pytest

from darukaa.kb.store import get_store
from darukaa.reasoning.clarifier import is_sufficient
from darukaa.reasoning.diagnosis import diagnose
from darukaa.reasoning.graph import causal_chains
from darukaa.reasoning.profile_parser import parse_json, parse_text
from darukaa.reasoning.recommender import recommend
from darukaa.reasoning.verifier import verify
from darukaa.schemas import SiteProfile

EXAMPLE = SiteProfile(soil_organic_carbon_pct=0.3, rainfall_level="low", crop="wheat", cropping_system="monoculture",
                      land_use="cropland", climate_zone="semi-arid")


def test_parse_challenge_example_text():
    out = parse_text("Soil organic carbon: 0.3%, Rainfall: low, Crop: monoculture wheat, Region: semi-arid")
    assert out["soil_organic_carbon_pct"] == 0.3
    assert out["rainfall_level"] == "low"
    assert out["cropping_system"] == "monoculture" and out["crop"] == "wheat"
    assert out["climate_zone"] == "semi-arid"


def test_parse_loose_json():
    out = parse_json({"soil_organic_carbon": "0.3%", "rainfall": "low", "crop": "monoculture wheat", "region": "semi-arid"})
    profile = SiteProfile.model_validate(out)
    assert profile.soil_organic_carbon_pct == 0.3 and profile.cropping_system == "monoculture"


def test_parse_numbers_and_coordinates():
    out = parse_text("about 450 mm rain, pH 8.9, farm near 26.9, 75.8, 10 acres")
    assert out["rainfall_mm"] == 450 and out["soil_ph"] == 8.9
    assert (out["latitude"], out["longitude"]) == (26.9, 75.8)
    assert out["area_ha"] == 4.05


def test_sufficiency_needs_three_variables_across_domains():
    assert not is_sufficient(SiteProfile(species_richness_trend="declining"))
    assert is_sufficient(EXAMPLE)


def test_diagnosis_of_challenge_example():
    codes = {f.code for f in diagnose(EXAMPLE)}
    assert {"SOC_VERY_LOW", "WATER_LIMITED", "MONOCULTURE"} <= codes


def test_causal_chains_link_multiple_variables():
    chains = causal_chains(get_store().relationships, diagnose(EXAMPLE))
    assert chains and max(len(c.path) for c in chains) >= 3


def test_recommendations_are_multi_issue_and_water_aware():
    recs = recommend(get_store(), EXAMPLE, diagnose(EXAMPLE))
    ids = [r.practice_id for r in recs]
    assert "cover_crops" not in ids  # water-consuming practice screened out in drylands
    assert ids[0] in {"conservation_ag_mulch", "in_situ_water_harvesting"}  # water first
    assert "dryland_agroforestry" in ids and "legume_intercrop_rotation" in ids
    for r in recs:
        assert r.time_horizon in {"short", "medium", "long"}
        assert r.confidence in {"high", "medium", "low"}
        assert r.references and r.impacted_metrics
        if r.kind == "do":
            assert len(r.addresses) >= 2


def test_cover_crops_allowed_when_water_is_not_limiting():
    wet = SiteProfile(soil_organic_carbon_pct=0.6, rainfall_mm=900, crop="maize", cropping_system="monoculture",
                      land_use="cropland", climate_zone="temperate", erosion=True)
    assert "cover_crops" in [r.practice_id for r in recommend(get_store(), wet, diagnose(wet))]


def test_contraindicated_practice_excluded():
    grass = SiteProfile(land_use="grassland", climate_zone="semi-arid", species_richness_trend="declining", habitat_diversity="low")
    ids = [r.practice_id for r in recommend(get_store(), grass, diagnose(grass))]
    assert "dryland_agroforestry" not in ids and "restore_open_ecosystem" in ids


def test_profile_update_clears_stale_sibling_value():
    p = SiteProfile(rainfall_level="low")
    changed = p.merge(SiteProfile(rainfall_mm=1200))
    assert p.rainfall_level is None and p.rainfall_mm == 1200
    assert "rainfall_level" in changed


def test_verifier_removes_unsupported_claims():
    text = "Mulch helps [ev_a, ev_b]. Trees add 40% carbon [ev_a]. Fake claim [ev_zzz]."
    clean, notes = verify(text, {"ev_a", "ev_b"}, ["a gain of 25%"], [0.3])
    assert clean == "Mulch helps [ev_a, ev_b]."
    assert len(notes) == 2


def test_verifier_checks_parenthesised_citations():
    clean, notes = verify("Buffers remove nitrogen (ev_a). Made up (ev_fake).", {"ev_a"}, [], [])
    assert clean == "Buffers remove nitrogen [ev_a]."
    assert "ev_fake" in notes[0]


def test_prerequisite_practice_allowed_without_second_issue():
    acid = SiteProfile(soil_ph=4.8, climate_zone="humid", land_use="cropland", crop="cotton",
                       cropping_system="monoculture", pollution=["fertilizer"])
    recs = recommend(get_store(), acid, diagnose(acid))
    ids = [r.practice_id for r in recs]
    assert "lime_or_biochar_acidic" in ids
    buffers = next(r for r in recs if r.practice_id == "nutrient_buffers")
    assert buffers.time_horizon == "short"  # reduced N runoff is a benefit, not a side effect


def test_organic_matter_is_converted_to_organic_carbon():
    """Reporting organic matter as carbon would overstate it ~2x (Pribyl 2010)."""
    assert parse_text("soil organic matter is 1.6%")["soil_organic_carbon_pct"] == 0.8
    assert parse_text("soil organic carbon is 1.6%")["soil_organic_carbon_pct"] == 1.6


def test_projection_scales_evidence_to_the_site():
    from darukaa.reasoning.projections import project_practice, soc_stock

    site = SiteProfile(soil_organic_carbon_pct=0.3, soil_texture="sandy", area_ha=5,
                       land_use="cropland", climate_zone="semi-arid", cropping_system="monoculture")
    assert soc_stock(0.3, 1.6) == pytest.approx(14.4)  # % x bulk density x 30 cm
    projections = project_practice(get_store().practices["dryland_agroforestry"], site)
    stock = next(p for p in projections if p.metric == "soil_organic_carbon_stock")
    assert stock.baseline == 14.4 and stock.low > stock.baseline < stock.high
    assert any(p.metric == "soil_carbon_on_your_land" for p in projections)   # area known
    assert any("saturate" in a for a in stock.assumptions)


def test_no_projection_without_a_measured_baseline():
    from darukaa.reasoning.projections import project_practice

    site = SiteProfile(land_use="cropland", climate_zone="semi-arid", cropping_system="monoculture")
    assert project_practice(get_store().practices["dryland_agroforestry"], site) == []


def test_value_of_information_ranks_ph_above_habitat_for_this_site():
    from darukaa.reasoning import voi
    from darukaa.reasoning.clarifier import missing

    site = SiteProfile(soil_organic_carbon_pct=0.3, rainfall_level="low", crop="wheat",
                       cropping_system="monoculture", land_use="cropland", climate_zone="semi-arid")
    ranked = voi.rank_missing(get_store(), site, missing(site))
    assert ranked[0]["label"] == "soil pH"
    assert ranked[0]["changed_recommendations"] >= 1
    assert voi.phrase(ranked[0], 4).endswith("*")
