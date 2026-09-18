"""Turns literature effect sizes into numbers for *this* site.

A recommendation that says "+26% soil organic carbon" is a literature result. What a land manager
needs is: my soil is at 0.3% (about 13 t C/ha in the top 30 cm); after ten years of this practice it
would be roughly 0.35% (about 15 t C/ha), i.e. +2.0 t C/ha, ±the spread of the evidence.

Everything here is arithmetic on values that are already in the knowledge base:
  stock (t C/ha) = SOC% x bulk density (g/cm3) x depth (cm)
Bulk density is estimated from texture when it is not measured (ev_bulk_density_ranges).
Projections are explicitly labelled as evidence-based estimates, not predictions: sequestration
saturates and is reversible (ev_ar6_afolu).
"""

from darukaa.schemas import Projection, SiteProfile

DEPTH_CM = 30
# Typical cultivated topsoil bulk density by texture (g/cm3) — mid-range of ev_bulk_density_ranges.
BULK_DENSITY = {"sandy": 1.6, "loamy": 1.4, "clayey": 1.2}
DEFAULT_BULK_DENSITY = 1.4


def bulk_density(p: SiteProfile) -> tuple[float, str]:
    if p.soil_texture:
        return BULK_DENSITY[p.soil_texture], f"bulk density {BULK_DENSITY[p.soil_texture]} g/cm³ assumed for {p.soil_texture} topsoil"
    return DEFAULT_BULK_DENSITY, f"bulk density {DEFAULT_BULK_DENSITY} g/cm³ assumed (texture unknown; a soil test would refine this)"


def soc_stock(soc_pct: float, bd: float, depth_cm: int = DEPTH_CM) -> float:
    """SOC concentration (%) -> stock in t C/ha for the given depth."""
    return soc_pct * bd * depth_cm


def project_practice(practice: dict, p: SiteProfile) -> list[Projection]:
    """Apply a practice's structured projection block to the site's own baseline."""
    spec = practice.get("projection")
    if not spec or p.soil_organic_carbon_pct is None or spec["metric"] != "soil_organic_carbon":
        return []

    bd, bd_note = bulk_density(p)
    baseline_pct = p.soil_organic_carbon_pct
    baseline_stock = soc_stock(baseline_pct, bd)
    years = spec["years"]

    if spec["kind"] == "relative_pct":                     # e.g. +26% of the existing stock
        low_stock = baseline_stock * (1 + spec["low"] / 100)
        high_stock = baseline_stock * (1 + spec["high"] / 100)
        method = f"{spec['low']}–{spec['high']}% relative gain applied to the measured baseline"
    elif spec["kind"] == "rate_t_ha_yr":                   # e.g. 0.32 t C/ha/yr
        low_stock = baseline_stock + spec["low"] * years
        high_stock = baseline_stock + spec["high"] * years
        method = f"{spec['low']}–{spec['high']} t C/ha/yr sustained for {years} years"
    else:
        return []

    assumptions = [
        bd_note,
        f"0–{DEPTH_CM} cm depth",
        "gains saturate over decades and reverse if management reverts (IPCC AR6)",
    ]
    if spec.get("caveat"):
        assumptions.append(spec["caveat"])

    out = [Projection(
        metric="soil_organic_carbon_stock", unit="t C/ha", years=years,
        baseline=round(baseline_stock, 1), low=round(low_stock, 1), high=round(high_stock, 1),
        change_low=round(low_stock - baseline_stock, 1), change_high=round(high_stock - baseline_stock, 1),
        method=method, evidence_id=spec["evidence"], assumptions=assumptions)]
    out.append(Projection(
        metric="soil_organic_carbon", unit="%", years=years,
        baseline=round(baseline_pct, 2), low=round(low_stock / (bd * DEPTH_CM), 2), high=round(high_stock / (bd * DEPTH_CM), 2),
        change_low=round(low_stock / (bd * DEPTH_CM) - baseline_pct, 2), change_high=round(high_stock / (bd * DEPTH_CM) - baseline_pct, 2),
        method=method, evidence_id=spec["evidence"], assumptions=assumptions))
    if p.area_ha:
        out.append(Projection(
            metric="soil_carbon_on_your_land", unit=f"t C over {p.area_ha:g} ha", years=years,
            baseline=round(baseline_stock * p.area_ha, 1),
            low=round(low_stock * p.area_ha, 1), high=round(high_stock * p.area_ha, 1),
            change_low=round((low_stock - baseline_stock) * p.area_ha, 1),
            change_high=round((high_stock - baseline_stock) * p.area_ha, 1),
            method=method + f", across {p.area_ha:g} ha", evidence_id=spec["evidence"], assumptions=assumptions))
    return out


def baseline_summary(p: SiteProfile) -> str | None:
    """One line of context shown with the diagnosis when soil carbon is known."""
    if p.soil_organic_carbon_pct is None:
        return None
    bd, bd_note = bulk_density(p)
    stock = soc_stock(p.soil_organic_carbon_pct, bd)
    return (f"Soil carbon baseline: {p.soil_organic_carbon_pct}% ≈ {stock:.0f} t C/ha in the top {DEPTH_CM} cm "
            f"({bd_note}).")
