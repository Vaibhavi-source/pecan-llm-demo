"""
validate.py - Pydantic validation of extracted BETYdb data.
"""

from typing import Literal, Optional, Any
from pydantic import BaseModel, field_validator, model_validator


Status = Literal["EXTRACTED", "INFERRED", "UNRESOLVED"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]

# BETYdb-recognized yield/trait variable names (subset)
KNOWN_VARIABLES = {
    "yield", "aboveground_biomass", "leaf_area_index", "SLA", "SRL",
    "root_biomass", "stem_biomass", "leaf_biomass", "height",
    "Vcmax", "Jmax", "stomatal_conductance", "net_photosynthesis",
    "dark_respiration", "water_use_efficiency", "nitrogen_content",
}

# Valid unit strings (subset, case-insensitive check)
VALID_UNIT_PATTERNS = [
    "mg/g", "g/m2", "kg/ha", "Mg/ha", "t/ha", "m2/m2",
    "umol/m2/s", "mmol/m2/s", "mol/m2/s", "cm2/g", "m", "cm",
    "%", "g/kg", "kg/m2", "g/plant",
]


class FieldValue(BaseModel):
    value: Any
    status: Status
    confidence: Confidence
    evidence_quote: str = ""

    @field_validator("evidence_quote", mode="before")
    @classmethod
    def coerce_none_quote(cls, v):
        return v if v is not None else ""


class Site(BaseModel):
    name: FieldValue
    lat: FieldValue
    lon: FieldValue
    country: FieldValue

    @model_validator(mode="after")
    def check_coordinates(self):
        lat_val = self.lat.value
        lon_val = self.lon.value
        if lat_val is not None and lat_val != "":
            try:
                lat = float(lat_val)
                if not (-90 <= lat <= 90):
                    self.lat = FieldValue(
                        value=lat_val,
                        status="UNRESOLVED",
                        confidence="LOW",
                        evidence_quote=self.lat.evidence_quote,
                    )
            except (ValueError, TypeError):
                pass
        if lon_val is not None and lon_val != "":
            try:
                lon = float(lon_val)
                if not (-180 <= lon <= 180):
                    self.lon = FieldValue(
                        value=lon_val,
                        status="UNRESOLVED",
                        confidence="LOW",
                        evidence_quote=self.lon.evidence_quote,
                    )
            except (ValueError, TypeError):
                pass
        return self


class Species(BaseModel):
    scientific_name: FieldValue
    common_name: FieldValue


class Trait(BaseModel):
    variable_name: FieldValue
    mean: FieldValue
    SE: FieldValue
    n: FieldValue
    units: FieldValue
    date: FieldValue
    treatment: FieldValue

    @model_validator(mode="after")
    def check_mean_positive(self):
        mean_val = self.mean.value
        if mean_val is not None and mean_val != "":
            try:
                mean = float(mean_val)
                # Yields and biomass should be positive
                var = (self.variable_name.value or "").lower()
                if mean < 0 and any(k in var for k in ["yield", "biomass", "lai"]):
                    self.mean = FieldValue(
                        value=mean_val,
                        status="UNRESOLVED",
                        confidence="LOW",
                        evidence_quote=self.mean.evidence_quote,
                    )
            except (ValueError, TypeError):
                pass
        return self

    @model_validator(mode="after")
    def flag_unknown_variable(self):
        var = (self.variable_name.value or "").lower().replace(" ", "_")
        if self.variable_name.status != "UNRESOLVED":
            matched = any(known.lower() in var or var in known.lower() for known in KNOWN_VARIABLES)
            if not matched and var:
                # Downgrade confidence if variable not in known list
                self.variable_name = FieldValue(
                    value=self.variable_name.value,
                    status=self.variable_name.status,
                    confidence="LOW",
                    evidence_quote=self.variable_name.evidence_quote,
                )
        return self


def _coerce_field(raw: Any) -> dict:
    """Ensure a field is a dict with required keys."""
    if isinstance(raw, dict):
        return {
            "value": raw.get("value"),
            "status": raw.get("status", "UNRESOLVED"),
            "confidence": raw.get("confidence", "LOW"),
            "evidence_quote": raw.get("evidence_quote", ""),
        }
    return {"value": raw, "status": "UNRESOLVED", "confidence": "LOW", "evidence_quote": ""}


def _unresolved_field(name: str = "") -> dict:
    return {"value": None, "status": "UNRESOLVED", "confidence": "LOW", "evidence_quote": ""}


def validate_extraction(raw_dict: dict) -> dict:
    """
    Validate the LLM-extracted dictionary against BETYdb Pydantic schema.

    Args:
        raw_dict: Output from extract_from_markdown()

    Returns:
        Validated dict with site, species, and traits keys.
    """
    print("[validate] Running Pydantic validation...")

    # --- Site ---
    raw_site = raw_dict.get("site", {})
    site = Site(
        name=_coerce_field(raw_site.get("name", _unresolved_field())),
        lat=_coerce_field(raw_site.get("lat", _unresolved_field())),
        lon=_coerce_field(raw_site.get("lon", _unresolved_field())),
        country=_coerce_field(raw_site.get("country", _unresolved_field())),
    )

    # --- Species ---
    raw_species = raw_dict.get("species", {})
    species = Species(
        scientific_name=_coerce_field(raw_species.get("scientific_name", _unresolved_field())),
        common_name=_coerce_field(raw_species.get("common_name", _unresolved_field())),
    )

    # --- Traits ---
    raw_traits = raw_dict.get("traits", [])
    traits = []
    for rt in raw_traits:
        trait = Trait(
            variable_name=_coerce_field(rt.get("variable_name", _unresolved_field())),
            mean=_coerce_field(rt.get("mean", _unresolved_field())),
            SE=_coerce_field(rt.get("SE", _unresolved_field())),
            n=_coerce_field(rt.get("n", _unresolved_field())),
            units=_coerce_field(rt.get("units", _unresolved_field())),
            date=_coerce_field(rt.get("date", _unresolved_field())),
            treatment=_coerce_field(rt.get("treatment", _unresolved_field())),
        )
        traits.append(trait)

    validated = {
        "site": site.model_dump(),
        "species": species.model_dump(),
        "traits": [t.model_dump() for t in traits],
    }

    # Summary stats
    all_fields = []
    for section in ["site", "species"]:
        for v in validated[section].values():
            if isinstance(v, dict) and "status" in v:
                all_fields.append(v["status"])
    for trait in validated["traits"]:
        for v in trait.values():
            if isinstance(v, dict) and "status" in v:
                all_fields.append(v["status"])

    counts = {
        "EXTRACTED": all_fields.count("EXTRACTED"),
        "INFERRED": all_fields.count("INFERRED"),
        "UNRESOLVED": all_fields.count("UNRESOLVED"),
    }
    validated["_stats"] = counts
    print(f"[validate] Stats: {counts}")
    return validated
