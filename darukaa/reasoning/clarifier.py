"""Decides whether enough is known to reason, and which questions add the most information."""

from darukaa.schemas import SiteProfile

MIN_VARIABLES = 3  # challenge constraint: reason over at least 3 environmental variables
MIN_DOMAINS = 2

# (check, variable label, question). Order = information value for a biodiversity diagnosis:
# soil carbon, water and land use first (matches the challenge's example follow-up).
QUESTIONS = [
    (lambda p: p.soil_organic_carbon_pct is None, "soil organic carbon",
     "What is the **soil organic carbon (%)**? A soil test or Soil Health Card value is ideal; 'low/medium/high' also helps."),
    (lambda p: p.rainfall_mm is None and p.rainfall_level is None and p.climate_zone is None, "rainfall",
     "What is the **rainfall pattern** — roughly how many mm per year (or low / moderate / high), and is the land rainfed or irrigated?"),
    (lambda p: p.land_use is None, "land use",
     "What is the **current land use** — cropland, pasture, forest, orchard, fallow? If cropland, which crops, and is it a monoculture or a rotation?"),
    (lambda p: p.climate_zone is None and p.region is None and p.latitude is None, "climate zone / location",
     "Where is the land — **region or climate zone** (e.g. semi-arid Rajasthan)? Coordinates work too, and let me look up soil and climate data."),
    (lambda p: p.land_use == "cropland" and p.cropping_system is None, "cropping system",
     "Is the field a **monoculture**, a rotation, or intercropped?"),
    (lambda p: p.habitat_diversity is None and p.natural_habitat_pct is None, "habitat",
     "Roughly what share of the land and its surroundings is **natural or semi-natural vegetation** (hedges, trees, grassland, ponds)?"),
    (lambda p: p.soil_ph is None, "soil pH", "Do you know the **soil pH**?"),
    (lambda p: not p.pollution, "chemical inputs",
     "Are **pesticides or synthetic fertilisers** used regularly?"),
]


def missing(p: SiteProfile) -> list[tuple[str, str]]:
    return [(label, q) for check, label, q in QUESTIONS if check(p)]


def is_sufficient(p: SiteProfile) -> bool:
    # Land use decides which practices are even applicable, so it is required (coordinates can't supply it).
    return (len(p.known_variables()) >= MIN_VARIABLES and len(p.known_domains()) >= MIN_DOMAINS
            and p.land_use is not None)


def next_questions(p: SiteProfile, asked: dict[str, int], limit: int = 3) -> list[tuple[str, str]]:
    """Top missing variables, skipping ones already asked twice (don't nag)."""
    return [(label, q) for label, q in missing(p) if asked.get(label, 0) < 2][:limit]
