"""Threshold-based diagnosis: turns a site profile into issue codes with evidence.

Thresholds and their provenance:
- SOC bands (<0.5 low, 0.5–0.75 medium): Indian Soil Health Card ratings (ev_soc_bands_india).
- pH bands (<5.5 strongly acid, >8.5 strongly alkaline): soil science textbook (ev_ph_nutrients).
- Climate zones by aridity index: UNCCD/UNEP (ev_aridity).
- Rainfall mm bands (<300 very low, <600 low, <1000 moderate) and mean temperature >27 °C for heat
  stress are HEURISTIC app thresholds (flagged as such in the output), used only when the user gives
  numbers but no climate zone.
"""

from darukaa.schemas import Finding, SiteProfile

DRY_ZONES = {"hyper-arid", "arid", "semi-arid"}
OPEN_LAND_USES = {"grassland", "pasture"}


def rainfall_level(p: SiteProfile) -> str | None:
    if p.rainfall_level:
        return p.rainfall_level
    if p.rainfall_mm is not None:
        return "low" if p.rainfall_mm < 600 else "moderate" if p.rainfall_mm < 1000 else "high"
    return None


def is_water_limited(p: SiteProfile) -> bool:
    level = rainfall_level(p)
    # A site-specific rainfall figure/level of "high" is more specific than a regional climate label.
    zone_dry = p.climate_zone in DRY_ZONES and level != "high"
    return level == "low" or zone_dry or p.soil_moisture == "low"


def diagnose(p: SiteProfile) -> list[Finding]:
    f: list[Finding] = []

    soc = p.soil_organic_carbon_pct
    if soc is not None:
        if soc < 0.5:
            f.append(Finding(code="SOC_VERY_LOW", label=f"Very low soil organic carbon ({soc}%)", severity=3,
                             variables=["soil_organic_carbon", "soil_biodiversity"],
                             explanation="Below the 0.5% 'low' rating: weak aggregation, low water retention and little food for soil organisms.",
                             evidence_id="ev_soc_bands_india"))
        elif soc < 0.75:
            f.append(Finding(code="SOC_LOW", label=f"Medium-low soil organic carbon ({soc}%)", severity=2,
                             variables=["soil_organic_carbon"],
                             explanation="Within the 0.5–0.75% 'medium' band; there is headroom to build carbon.",
                             evidence_id="ev_soc_bands_india"))

    ph = p.soil_ph
    if ph is not None:
        if ph < 5.5:
            f.append(Finding(code="PH_ACIDIC", label=f"Strongly acidic soil (pH {ph})", severity=3 if ph < 5 else 2,
                             variables=["soil_ph", "soil_biodiversity"],
                             explanation="Aluminium/manganese toxicity risk and poor legume nodulation.",
                             evidence_id="ev_ph_nutrients"))
        elif ph > 8.5:
            f.append(Finding(code="PH_ALKALINE", label=f"Strongly alkaline soil (pH {ph})", severity=2,
                             variables=["soil_ph", "soil_moisture"],
                             explanation="Likely sodicity: poor structure and infiltration, low P and micronutrient availability.",
                             evidence_id="ev_ph_nutrients"))

    if is_water_limited(p):
        why = []
        if p.climate_zone in DRY_ZONES:
            why.append(f"{p.climate_zone} climate")
        if rainfall_level(p) == "low":
            why.append(f"low rainfall{f' ({p.rainfall_mm:.0f} mm/yr)' if p.rainfall_mm else ''}")
        if p.soil_moisture == "low":
            why.append("low soil moisture")
        f.append(Finding(code="WATER_LIMITED", label="Water-limited system (" + ", ".join(why) + ")", severity=3,
                         variables=["rainfall", "soil_moisture", "water_availability"],
                         explanation="Water, not nutrients, is likely the first limit on plant growth, carbon inputs and species survival. Practices that consume water must be screened.",
                         evidence_id="ev_aridity"))

    if p.temperature_level == "high" or (p.temperature_c is not None and p.temperature_c > 27):
        f.append(Finding(code="HEAT_STRESS", label="High temperature", severity=2,
                         variables=["temperature", "soil_organic_carbon", "species_richness"],
                         explanation="Heat speeds SOC decomposition and pushes species beyond climatic tolerance (heuristic threshold: mean > 27 °C).",
                         evidence_id="ev_soc_temperature"))

    if p.cropping_system == "monoculture":
        f.append(Finding(code="MONOCULTURE", label=f"Monoculture{f' ({p.crop})' if p.crop else ''}", severity=3,
                         variables=["crop_diversity", "soil_biodiversity", "habitat_diversity"],
                         explanation="A single crop narrows residue and root inputs and simplifies habitat, reducing soil and above-ground biodiversity.",
                         evidence_id="ev_mcdaniel_rotation"))

    low_habitat = p.habitat_diversity == "low" or (p.natural_habitat_pct is not None and p.natural_habitat_pct < 20)
    if low_habitat:
        f.append(Finding(code="LOW_HABITAT", label="Low semi-natural habitat" + (f" ({p.natural_habitat_pct:.0f}%)" if p.natural_habitat_pct is not None else ""),
                         severity=3 if (p.natural_habitat_pct or 100) < 10 else 2,
                         variables=["habitat_diversity", "pollinators", "species_richness"],
                         explanation="Below the ~20% native-habitat level proposed for working landscapes; pollinators and natural enemies decline with distance to habitat.",
                         evidence_id="ev_garibaldi_20pct"))

    if p.fragmentation in ("moderate", "high"):
        f.append(Finding(code="FRAGMENTED", label=f"{p.fragmentation.capitalize()} habitat fragmentation", severity=3 if p.fragmentation == "high" else 2,
                         variables=["habitat_fragmentation", "species_richness"],
                         explanation="Isolated patches lose species over time through edge effects and blocked movement.",
                         evidence_id="ev_haddad_fragmentation"))

    if p.species_richness_trend == "declining":
        f.append(Finding(code="BIODIVERSITY_DECLINE", label="Declining species richness", severity=2,
                         variables=["species_richness"],
                         explanation="Reported decline — the diagnosis above identifies which drivers are most likely responsible.",
                         evidence_id="ev_ipbes_drivers"))
    if p.pollinator_trend == "declining":
        f.append(Finding(code="POLLINATOR_DECLINE", label="Declining pollinators", severity=2,
                         variables=["pollinators"],
                         explanation="Pollinator loss is driven by habitat loss, intensive management and pesticides.",
                         evidence_id="ev_ipbes_pollinators"))

    if "pesticide" in p.pollution:
        f.append(Finding(code="PESTICIDE", label="Pesticide pressure", severity=2,
                         variables=["pollution", "pollinators"],
                         explanation="Pesticide exposure harms pollinators and natural enemies.",
                         evidence_id="ev_ipbes_pollinators"))
    if {"fertilizer", "sewage"} & set(p.pollution):
        f.append(Finding(code="NUTRIENT_POLLUTION", label="Nutrient (nitrogen) pollution", severity=2,
                         variables=["pollution", "water_quality", "species_richness"],
                         explanation="Nitrogen enrichment reduces plant diversity and degrades water quality.",
                         evidence_id="ev_stevens_nitrogen"))
    if p.deforestation:
        f.append(Finding(code="DEFORESTATION", label="Recent deforestation / clearing", severity=3,
                         variables=["deforestation", "habitat_fragmentation", "species_richness"],
                         explanation="Habitat loss is the dominant driver of local species loss.",
                         evidence_id="ev_newbold_landuse"))
    if p.erosion or (soc is not None and soc < 0.5 and is_water_limited(p) and p.land_use in ("cropland", "degraded", "fallow")):
        f.append(Finding(code="EROSION", label="Erosion risk" + ("" if p.erosion else " (inferred: low SOC + dry cropland)"), severity=2,
                         variables=["erosion", "soil_organic_carbon"],
                         explanation="Bare, low-carbon soils lose topsoil to wind and water, removing the most carbon-rich layer.",
                         evidence_id="ev_soil_degradation_global"))
    if p.land_use in OPEN_LAND_USES and not p.deforestation:
        f.append(Finding(code="OPEN_ECOSYSTEM", label=f"Open ecosystem ({p.land_use})", severity=1,
                         variables=["land_use", "habitat_diversity"],
                         explanation="Grasslands and savannas have distinctive biodiversity; afforesting them is harmful.",
                         evidence_id="ev_veldman_grassland"))
    return f
