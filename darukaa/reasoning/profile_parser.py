"""Turns free text or JSON into SiteProfile values.

Two layers: a deterministic rule parser (always runs, precise for numbers) and an optional
LLM extractor (better for loose phrasing). Rule-parsed numbers win over LLM numbers."""

import json
import re

from pydantic import ValidationError

from darukaa import llm
from darukaa.schemas import SiteProfile

CLIMATE_ZONES = ["hyper-arid", "semi-arid", "dry sub-humid", "arid", "tropical humid", "humid", "temperate", "cold"]
CROPS = ["wheat", "rice", "paddy", "maize", "corn", "cotton", "sugarcane", "soybean", "soya", "pearl millet", "millet",
         "sorghum", "mustard", "groundnut", "chickpea", "barley", "potato", "tea", "coffee", "oil palm", "cocoa", "banana"]
LAND_USE_WORDS = {
    "cropland": ["cropland", "farm", "field", "crop", "agricultur", "cultivat"],
    "pasture": ["pasture", "grazing", "rangeland"],
    "grassland": ["grassland", "savanna", "meadow"],
    "forest": ["forest", "woodland"],
    "orchard": ["orchard"],
    "plantation": ["plantation"],
    "fallow": ["fallow"],
    "degraded": ["degraded", "wasteland", "barren"],
    "wetland": ["wetland", "marsh"],
    "urban": ["urban", "city"],
}
SKIP_PATTERN = re.compile(r"\b(don'?t know|do not know|not sure|no idea|skip|unknown|n/?a|just (give|recommend)|proceed|go ahead)\b", re.I)
NUM = r"(-?\d+(?:\.\d+)?)"
SOM_TO_SOC = 2.0  # organic matter -> organic carbon divisor (Pribyl 2010 recommends 2, not 1.724)


QUESTION_PATTERN = re.compile(
    r"^\s*(why|what|which|how|when|where|who|should|shall|can|could|would|will|do|does|did|is|are|am|was|were|any)\b"
    r"|\?\s*$", re.I)


def looks_like_a_question(text: str) -> bool:
    """A question is a request about the advice, not a statement of new site data."""
    return bool(QUESTION_PATTERN.search(text.strip()))


def wants_to_skip(text: str) -> bool:
    return bool(SKIP_PATTERN.search(text))


def _level(fragment: str) -> str | None:
    fragment = fragment.lower()
    if re.search(r"\b(very low|low|scarce|poor|little|erratic|deficient|dry)\b", fragment):
        return "low"
    if re.search(r"\b(moderate|medium|average|normal)\b", fragment):
        return "moderate"
    if re.search(r"\b(high|heavy|abundant|plenty|wet)\b", fragment):
        return "high"
    return None


def parse_text(text: str) -> dict:
    t = text.lower()
    out: dict = {}

    m = re.search(r"(?:soil organic carbon|organic carbon|\bsoc\b|\boc\b)[^0-9\n]{0,25}" + NUM + r"\s*%?", t)
    if m:
        out["soil_organic_carbon_pct"] = float(m.group(1))
    else:
        # Organic MATTER is roughly twice organic carbon (Pribyl 2010) — converting matters.
        m = re.search(r"(?:soil organic matter|organic matter|\bsom\b)[^0-9\n]{0,25}" + NUM + r"\s*%?", t)
        if m:
            out["soil_organic_carbon_pct"] = round(float(m.group(1)) / SOM_TO_SOC, 2)
            out["_soc_from_som"] = float(m.group(1))
    m = re.search(r"\bph\b[^0-9\n]{0,12}" + NUM, t)
    if m:
        out["soil_ph"] = float(m.group(1))
    m = re.search(r"(?:rain\w*|precipitation)[^0-9\n]{0,25}" + NUM + r"\s*mm", t) or re.search(NUM + r"\s*mm[^.\n]{0,20}(?:rain|precip)", t)
    if m:
        out["rainfall_mm"] = float(m.group(1))
    else:
        m = re.search(r"((?:very )?\w+)\s+(?:rainfall|rain)\b|(?:rainfall|rain)\s*(?:is|:|=|pattern is)?\s*((?:very )?\w+)", t)
        if m:
            lvl = _level(" ".join(g for g in m.groups() if g))
            if lvl:
                out["rainfall_level"] = lvl
        if "drought" in t and "rainfall_level" not in out:
            out["rainfall_level"] = "low"
    m = re.search(r"(?:temperature|temp)[^0-9\n]{0,20}" + NUM + r"\s*°?\s*c\b", t) or re.search(NUM + r"\s*°\s*c\b", t)
    if m:
        out["temperature_c"] = float(m.group(1))
    elif re.search(r"\b(very hot|hot climate|heat ?waves?|high temperature)", t):
        out["temperature_level"] = "high"

    for zone in CLIMATE_ZONES:
        if re.search(r"\b" + re.escape(zone).replace(r"\-", "[- ]?") + r"\b", t):
            out["climate_zone"] = zone
            break

    if re.search(r"\b(mono-?cultur\w*|mono-?crop\w*|only (grow|plant)\w*|(grows?|growing|plant|planting) only|single crop|same crop every)", t):
        out["cropping_system"] = "monoculture"
    elif "intercrop" in t:
        out["cropping_system"] = "intercropping"
    elif "rotation" in t:
        out["cropping_system"] = "rotation"
    elif "agroforestry" in t:
        out["cropping_system"] = "agroforestry"
    for crop in CROPS:
        if re.search(r"\b" + crop + r"\b", t):
            out["crop"] = crop
            break

    for use, words in LAND_USE_WORDS.items():
        if any(re.search(r"\b" + w, t) for w in words):
            out["land_use"] = use
            break
    if "crop" in out or "cropping_system" in out:
        out["land_use"] = "cropland"  # a named crop is more specific than words like 'forest' nearby

    m = re.search(r"soil moisture\s*(?:is|:|=)?\s*(\w+)|(\w+)\s+soil moisture", t)
    if m:
        lvl = _level(" ".join(g for g in m.groups() if g))
        if lvl:
            out["soil_moisture"] = lvl
    for tex in ("sandy", "loamy", "clayey"):
        if tex in t or (tex == "clayey" and re.search(r"\bclay\b", t)):
            out["soil_texture"] = tex
            break

    if re.search(r"(biodiversity|species|wildlife|birds?|insects?)\W+(?:\w+\W+){0,4}(declin|decreas|drop|los|disappear|fewer)", t) or \
            re.search(r"(declin|loss of|losing|fewer)\w*\W+(?:\w+\W+){0,3}(biodiversity|species|wildlife|birds)", t):
        out["species_richness_trend"] = "declining"
    if re.search(r"(fewer|declin\w*|no|los\w*)\W+(?:\w+\W+){0,2}(bees|pollinators?|butterflies)", t) or re.search(r"(bees|pollinators?)\W+(?:\w+\W+){0,3}(declin|disappear|fewer)", t):
        out["pollinator_trend"] = "declining"
    m = re.search(r"(?:natural|semi-natural|native)\s+(?:habitat|vegetation)[^0-9\n]{0,15}" + NUM + r"\s*%", t)
    if m:
        out["natural_habitat_pct"] = float(m.group(1))
    elif re.search(r"\b(no (trees|hedges?|hedgerows?|natural habitat)|bare land|cleared everything)\b", t):
        out["habitat_diversity"] = "low"
    else:
        m = re.search(r"habitat diversity\s*(?:is|:|=)?\s*(\w+)", t)
        if m and _level(m.group(1)):
            out["habitat_diversity"] = _level(m.group(1))
    if re.search(r"fragment", t):
        out["fragmentation"] = "moderate" if re.search(r"(moderate|some|partly) fragment", t) else "high"

    pollution = []
    if re.search(r"pesticid|insecticid|herbicid|spray", t):
        pollution.append("pesticide")
    if re.search(r"fertili[sz]er|urea|nitrogen (runoff|pollution)|nitrate", t):
        pollution.append("fertilizer")
    if re.search(r"heavy metal|lead|cadmium|arsenic", t):
        pollution.append("heavy_metals")
    if re.search(r"sewage|effluent", t):
        pollution.append("sewage")
    if re.search(r"plastic", t):
        pollution.append("plastic")
    if re.search(r"\b(no|without|stopped using) (pesticid|chemical)", t):
        pollution = [x for x in pollution if x != "pesticide"]
    if pollution:
        out["pollution"] = pollution
    if re.search(r"deforest|clear(ed|ing)\b[^.]{0,30}\b(forest|woodland|trees)|trees? (were|was|are) (cut|felled)|logging", t):
        out["deforestation"] = True
    if re.search(r"erosion|gull(y|ies)|topsoil (loss|washed)", t):
        out["erosion"] = True
    if re.search(r"\brainfed\b|rain-fed", t):
        out["irrigation"] = "rainfed"
    elif re.search(r"\birrigat", t):
        out["irrigation"] = "irrigated"

    m = re.search(r"(?:lat(?:itude)?\s*[:=]?\s*)" + NUM + r"[^0-9\-]+(?:lon(?:gitude)?\s*[:=]?\s*)" + NUM, t) or \
        re.search(r"(?:coordinates?|location|near|at|lat/?lon)\s*:?\s*\(?(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", t) or \
        re.search(r"\b(-?\d{1,2}\.\d{2,})\s*,\s*(-?\d{1,3}\.\d{2,})\b", t)
    if m:
        out["latitude"], out["longitude"] = float(m.group(1)), float(m.group(2))
    m = re.search(NUM + r"\s*(?:ha|hectares?)\b", t)
    if m:
        out["area_ha"] = float(m.group(1))
    m = re.search(NUM + r"\s*acres?\b", t)
    if m and "area_ha" not in out:
        out["area_ha"] = round(float(m.group(1)) * 0.4047, 2)
    return out


JSON_ALIASES = {
    "soc": "soil_organic_carbon_pct", "soil_organic_carbon": "soil_organic_carbon_pct", "organic_carbon": "soil_organic_carbon_pct",
    "ph": "soil_ph", "moisture": "soil_moisture", "rainfall": "rainfall", "precipitation": "rainfall",
    "temperature": "temperature", "lat": "latitude", "lon": "longitude", "lng": "longitude",
    "landuse": "land_use", "land_cover": "land_use", "habitat_share_pct": "natural_habitat_pct",
}


def parse_json(data: dict) -> dict:
    """Accepts exact SiteProfile fields or loose keys such as {"rainfall": "low", "crop": "monoculture wheat"}."""
    direct, loose = {}, []
    fields = SiteProfile.model_fields
    for key, value in data.items():
        k = JSON_ALIASES.get(key.lower().replace(" ", "_"), key.lower().replace(" ", "_"))
        if isinstance(value, str) and value.strip().endswith("%") and k in fields:
            value = value.strip().rstrip("%")
        if k in ("crop", "cropping_system") and isinstance(value, str):
            loose.append(f"crop: {value}")
            continue
        if k in fields and k != "provenance":
            try:
                SiteProfile.model_validate({k: value})
                direct[k] = value
                continue
            except ValidationError:
                pass
        label = {"soil_organic_carbon_pct": "soil organic carbon"}.get(k, k.replace("_", " "))
        if k == "region" and isinstance(value, str):
            loose.append(f"region {value}")
            direct.setdefault("region", value)
        else:
            loose.append(f"{label}: {value}{' mm' if k == 'rainfall' and isinstance(value, (int, float)) else ''}"
                         f"{' c' if k == 'temperature' and isinstance(value, (int, float)) else ''}")
    parsed = parse_text(". ".join(loose)) if loose else {}
    parsed.update(direct)
    if isinstance(parsed.get("region"), str):
        zone = parse_text(parsed["region"]).get("climate_zone")
        if zone:
            parsed.setdefault("climate_zone", zone)
    return parsed


LLM_SYSTEM = """You extract structured site data for an environmental science assistant.
Return ONLY a JSON object with any of these keys that the user's message states or clearly implies
(omit keys that are not mentioned; never guess numbers):
soil_organic_carbon_pct (number, %), soil_ph (number), soil_moisture (low|moderate|high),
soil_texture (sandy|loamy|clayey), rainfall_mm (number, annual), rainfall_level (low|moderate|high),
temperature_c (number, mean annual), temperature_level (low|moderate|high),
climate_zone (hyper-arid|arid|semi-arid|dry sub-humid|humid|temperate|tropical humid|cold),
land_use (cropland|pasture|grassland|forest|orchard|plantation|fallow|degraded|urban|wetland),
crop (string), cropping_system (monoculture|rotation|intercropping|agroforestry),
species_richness_trend (declining|stable|increasing), pollinator_trend (declining|stable|increasing),
habitat_diversity (low|moderate|high), natural_habitat_pct (number), fragmentation (low|moderate|high),
pollution (list of pesticide|fertilizer|heavy_metals|plastic|sewage|air), deforestation (bool), erosion (bool),
irrigation (rainfed|irrigated), region (string: place name), latitude, longitude, area_ha, goal (string).

If the message is a QUESTION about the advice (e.g. "why not cover crops?", "should I add lime?"),
return {} — a question states no new facts about the site. Never turn the subject of a question into
a goal, a crop or a cropping system."""


def llm_extract(text: str, profile: SiteProfile) -> dict:
    if not llm.available():
        return {}
    user = f"Already known: {json.dumps(profile.summary())}\n\nUser message: {text}"
    data = llm.chat_json(LLM_SYSTEM, user, max_tokens=300)
    if not isinstance(data, dict):
        return {}
    clean = {}
    for k, v in data.items():
        if k not in SiteProfile.model_fields or k == "provenance" or v in (None, "", []):
            continue
        try:
            SiteProfile.model_validate({k: v})
            clean[k] = v
        except ValidationError:
            continue
    return clean


def extract(text: str, profile: SiteProfile) -> SiteProfile:
    """Parse a user turn. JSON objects (anywhere in the message) are parsed structurally."""
    values: dict = {}
    stripped = text.strip()
    json_match = re.search(r"\{.*\}", stripped, re.S)
    if json_match:
        try:
            values.update(parse_json(json.loads(json_match.group(0))))
            stripped = (stripped[:json_match.start()] + stripped[json_match.end():]).strip()
        except json.JSONDecodeError:
            pass
    if stripped:
        rule = parse_text(stripped)
        # The LLM extractor only runs when the rules understood little (saves free-tier tokens).
        ai = llm_extract(stripped, profile) if len(rule) < 3 else {}
        for k, v in ai.items():
            if k not in rule:
                rule[k] = v
        for k, v in rule.items():
            values.setdefault(k, v)
    som = values.pop("_soc_from_som", None)
    new = SiteProfile.model_validate(values)
    new.provenance = {k: "user" for k in values}
    if som is not None:
        new.provenance["soil_organic_carbon_pct"] = f"user: converted from {som}% organic matter (÷2, Pribyl 2010)"
    return new
