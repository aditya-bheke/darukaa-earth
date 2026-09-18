"""Spatial enrichment (bonus requirement): coordinates -> soil and climate variables.

- ISRIC SoilGrids v2.0 REST API: topsoil (0–5 cm) pH (H2O) and soil organic carbon.
- Open-Meteo historical archive (ERA5-based): 5-year mean annual rainfall, temperature and
  FAO-56 reference evapotranspiration -> aridity index -> UNCCD climate zone.
- GBIF occurrence API: number of species with records in a ~20 km box (a sampling-biased proxy for
  species richness) and the number of records of IUCN-threatened species.
User-supplied values always take precedence; looked-up values are marked in provenance."""

from datetime import date

import requests

from darukaa.schemas import SiteProfile

TIMEOUT = 20


def soilgrids(lat: float, lon: float) -> dict:
    r = requests.get(
        "https://rest.isric.org/soilgrids/v2.0/properties/query",
        params={"lat": lat, "lon": lon, "property": ["phh2o", "soc"], "depth": "0-5cm", "value": "mean"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    out = {}
    for layer in r.json()["properties"]["layers"]:
        value = layer["depths"][0]["values"].get("mean")
        if value is None:
            continue
        if layer["name"] == "phh2o":  # pH x10
            out["soil_ph"] = round(value / 10, 1)
        elif layer["name"] == "soc":  # dg/kg -> %
            out["soil_organic_carbon_pct"] = round(value / 100, 2)
    return out


def aridity_zone(ai: float) -> str:
    if ai < 0.05:
        return "hyper-arid"
    if ai < 0.20:
        return "arid"
    if ai < 0.50:
        return "semi-arid"
    if ai < 0.65:
        return "dry sub-humid"
    return "humid"


def climate(lat: float, lon: float) -> dict:
    end_year = date.today().year - 1
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": lat, "longitude": lon,
            "start_date": f"{end_year - 4}-01-01", "end_date": f"{end_year}-12-31",
            "daily": "precipitation_sum,temperature_2m_mean,et0_fao_evapotranspiration",
            "timezone": "UTC",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    daily = r.json()["daily"]
    years = 5
    rain = sum(v for v in daily["precipitation_sum"] if v is not None) / years
    et0 = sum(v for v in daily["et0_fao_evapotranspiration"] if v is not None) / years
    temps = [v for v in daily["temperature_2m_mean"] if v is not None]
    out = {"rainfall_mm": round(rain), "temperature_c": round(sum(temps) / len(temps), 1)}
    if et0 > 0:
        ai = rain / et0
        out["aridity_index"] = round(ai, 2)
        out["climate_zone"] = aridity_zone(ai)
    return out


GBIF_BOX_DEG = 0.1  # ± degrees around the point (~22 km north-south)
THREATENED = {"CR", "EN", "VU"}


def gbif(lat: float, lon: float) -> dict:
    r = requests.get(
        "https://api.gbif.org/v1/occurrence/search",
        params={
            "decimalLatitude": f"{lat - GBIF_BOX_DEG},{lat + GBIF_BOX_DEG}",
            "decimalLongitude": f"{lon - GBIF_BOX_DEG},{lon + GBIF_BOX_DEG}",
            "hasCoordinate": "true", "limit": 0,
            "facet": ["speciesKey", "iucnRedListCategory"], "speciesKey.facetLimit": 5000,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    facets = {f["field"]: f["counts"] for f in data.get("facets", [])}
    species = len(facets.get("SPECIES_KEY", []))
    threatened = sum(c["count"] for c in facets.get("IUCN_RED_LIST_CATEGORY", []) if c["name"] in THREATENED)
    out = {"_records": data.get("count", 0), "_threatened_records": threatened}
    if species:
        out["species_richness"] = float(species)
    return out


def enrich(profile: SiteProfile) -> tuple[SiteProfile, list[str]]:
    """Returns a profile of looked-up values (only for fields the user has not set) and log notes."""
    notes, values, provenance = [], {}, {}
    lat, lon = profile.latitude, profile.longitude
    sources = (
        ("SoilGrids", soilgrids, "geo:ISRIC SoilGrids 0–5 cm"),
        ("Open-Meteo", climate, "geo:Open-Meteo ERA5 5-yr mean"),
        ("GBIF", gbif, "geo:GBIF recorded species in ~20 km box (sampling-biased proxy)"),
    )
    for name, fn, label in sources:
        try:
            data = fn(lat, lon)
        except Exception as exc:
            notes.append(f"{name} lookup failed ({type(exc).__name__}); continuing without it")
            continue
        ai = data.pop("aridity_index", None)
        extras = {k.lstrip("_"): data.pop(k) for k in list(data) if k.startswith("_")}
        for k, v in data.items():
            if getattr(profile, k) is None:
                values[k] = v
                provenance[k] = label
        found = ", ".join(f"{k}={v}" for k, v in data.items())
        extra = "".join(f", {k.replace('_', ' ')}={v}" for k, v in extras.items())
        notes.append(f"{name} at ({lat}, {lon}): {found}" + (f", aridity index={ai}" if ai is not None else "") + extra)
    new = SiteProfile.model_validate(values)
    new.provenance = provenance
    return new, notes
