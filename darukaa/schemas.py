"""Typed contracts for inputs (site profile) and outputs (structured scientific response)."""

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["low", "moderate", "high"]
Horizon = Literal["short", "medium", "long"]

HORIZON_DEFINITIONS = {
    "short": "< 1 year",
    "medium": "1–5 years",
    "long": "> 5 years",
}

# Profile field -> environmental domain. Used to count how many variables are known.
VARIABLE_DOMAINS = {
    "soil_organic_carbon_pct": "soil",
    "soil_ph": "soil",
    "soil_moisture": "soil",
    "soil_texture": "soil",
    "rainfall_mm": "climate",
    "rainfall_level": "climate",
    "temperature_c": "climate",
    "temperature_level": "climate",
    "climate_zone": "climate",
    "land_use": "land_use",
    "cropping_system": "land_use",
    "crop": "land_use",
    "species_richness_trend": "biodiversity",
    "species_richness": "biodiversity",
    "habitat_diversity": "biodiversity",
    "natural_habitat_pct": "biodiversity",
    "fragmentation": "biodiversity",
    "pollinator_trend": "biodiversity",
    "pollution": "human_impact",
    "deforestation": "human_impact",
    "erosion": "human_impact",
}

# Fields that describe the same underlying variable; counted once.
VARIABLE_GROUPS = {
    "rainfall_mm": "rainfall",
    "rainfall_level": "rainfall",
    "temperature_c": "temperature",
    "temperature_level": "temperature",
    "crop": "land_use",
    "cropping_system": "cropping_system",
    "species_richness": "species_richness",
    "species_richness_trend": "species_richness",
}


SAME_VARIABLE = [("rainfall_mm", "rainfall_level"), ("temperature_c", "temperature_level")]


class SiteProfile(BaseModel):
    """Everything the system knows about the user's site. Filled across turns."""

    soil_organic_carbon_pct: float | None = Field(None, ge=0, le=60, description="Soil organic carbon, %")
    soil_ph: float | None = Field(None, ge=0, le=14)
    soil_moisture: Level | None = None
    soil_texture: Literal["sandy", "loamy", "clayey"] | None = None
    rainfall_mm: float | None = Field(None, ge=0, le=15000, description="Mean annual rainfall, mm")
    rainfall_level: Level | None = None
    temperature_c: float | None = Field(None, ge=-30, le=50, description="Mean annual temperature, °C")
    temperature_level: Level | None = None
    climate_zone: Literal["hyper-arid", "arid", "semi-arid", "dry sub-humid", "humid", "temperate", "tropical humid", "cold"] | None = None
    land_use: Literal["cropland", "pasture", "grassland", "forest", "orchard", "plantation", "fallow", "degraded", "urban", "wetland"] | None = None
    crop: str | None = None
    cropping_system: Literal["monoculture", "rotation", "intercropping", "agroforestry"] | None = None
    species_richness_trend: Literal["declining", "stable", "increasing"] | None = None
    species_richness: float | None = Field(None, ge=0)
    pollinator_trend: Literal["declining", "stable", "increasing"] | None = None
    habitat_diversity: Level | None = None
    natural_habitat_pct: float | None = Field(None, ge=0, le=100)
    fragmentation: Level | None = None
    pollution: list[Literal["pesticide", "fertilizer", "heavy_metals", "plastic", "sewage", "air"]] = Field(default_factory=list)
    deforestation: bool | None = None
    erosion: bool | None = None
    irrigation: Literal["rainfed", "irrigated"] | None = None
    region: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    area_ha: float | None = Field(None, ge=0)
    goal: str | None = None
    provenance: dict[str, str] = Field(default_factory=dict, description="field -> where the value came from")

    def merge(self, other: "SiteProfile", source: str = "user") -> list[str]:
        """Overlay non-empty values from `other`. Returns the fields that changed.

        Fields describing the same variable (e.g. rainfall_mm / rainfall_level) are kept consistent:
        a new value for one clears a stale value of the other."""
        changed = []
        for fields in SAME_VARIABLE:
            given = [f for f in fields if getattr(other, f) is not None]
            if given:
                for f in fields:
                    if f not in given and getattr(self, f) is not None:
                        setattr(self, f, None)
                        self.provenance.pop(f, None)
                        changed.append(f)
        for name in type(self).model_fields:
            if name == "provenance":
                continue
            new = getattr(other, name)
            if new is None or new == []:
                continue
            if name == "pollution":
                new = sorted(set(self.pollution) | set(new))
            if getattr(self, name) != new:
                setattr(self, name, new)
                self.provenance[name] = other.provenance.get(name, source)
                changed.append(name)
        return changed

    def known_variables(self) -> list[str]:
        """Distinct environmental variables with a value (for the ≥3-variable rule)."""
        seen = []
        for name in VARIABLE_DOMAINS:
            value = getattr(self, name)
            if value is None or value == []:
                continue
            group = VARIABLE_GROUPS.get(name, name)
            if group not in seen:
                seen.append(group)
        return seen

    def known_domains(self) -> set[str]:
        return {VARIABLE_DOMAINS[n] for n in VARIABLE_DOMAINS if getattr(self, n) not in (None, [])}

    def summary(self) -> dict:
        return {k: v for k, v in self.model_dump(exclude={"provenance"}).items() if v not in (None, [])}


class Reference(BaseModel):
    source_id: str
    citation: str
    url: str | None = None
    tier: int
    evidence_id: str | None = None
    excerpt: str | None = None


class Finding(BaseModel):
    code: str
    label: str
    severity: int = Field(ge=1, le=3)
    variables: list[str]
    explanation: str
    evidence_id: str | None = None


class CausalChain(BaseModel):
    path: list[str]
    mechanisms: list[str]
    evidence_ids: list[str]


class ImpactedMetric(BaseModel):
    metric: str
    direction: Literal["increase", "decrease", "protect"]
    estimate: str
    horizon: Horizon
    source_id: str
    evidence_id: str


class Projection(BaseModel):
    """An effect size applied to this site's own baseline (see reasoning/projections.py)."""

    metric: str
    unit: str
    years: int
    baseline: float
    low: float
    high: float
    change_low: float
    change_high: float
    method: str
    evidence_id: str
    assumptions: list[str] = Field(default_factory=list)


class MonitoringItem(BaseModel):
    indicator: str
    method: str
    frequency: str


class PlanPhase(BaseModel):
    phase: str
    window: str
    actions: list[str]
    monitor: list[str] = Field(default_factory=list)
    rationale: str


class Recommendation(BaseModel):
    practice_id: str
    kind: Literal["do", "avoid"] = "do"
    title: str
    what_to_do: str
    why_it_works: str
    site_specific_reasoning: str | None = None
    impacted_metrics: list[ImpactedMetric]
    time_horizon: Horizon
    confidence: Literal["high", "medium", "low"]
    confidence_score: float
    confidence_reason: str
    addresses: list[str]
    variables_linked: list[str]
    adaptations: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    references: list[Reference]
    score: float
    screening: bool = Field(False, description="True when too little was known to target ≥2 diagnosed issues")
    prerequisite: bool = Field(False, description="True for practices that unblock others (e.g. liming)")
    monitoring: list[MonitoringItem] = Field(default_factory=list)
    projections: list[Projection] = Field(default_factory=list)


class RetrievalHit(BaseModel):
    chunk_id: str
    source_id: str
    score: float
    dense_rank: int | None = None
    sparse_rank: int | None = None
    used_by: list[str] = Field(default_factory=list)
    text: str


class RetrievalTrace(BaseModel):
    query: str
    filters: dict
    hits: list[RetrievalHit]
    structured_lookups: list[str] = Field(default_factory=list)


class AssistantResponse(BaseModel):
    type: Literal["clarification", "recommendations", "answer"]
    message: str
    profile: dict
    known_variables: list[str]
    missing_variables: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    diagnosis: list[Finding] = Field(default_factory=list)
    causal_chains: list[CausalChain] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    retrieval: list[RetrievalTrace] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    action_plan: list[PlanPhase] = Field(default_factory=list)
    question_value: list[dict] = Field(default_factory=list, description="missing variables ranked by how much they would change the advice")
    llm_used: bool = False
    grounding_notes: list[str] = Field(default_factory=list)
