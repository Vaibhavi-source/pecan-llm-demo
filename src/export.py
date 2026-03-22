"""
export.py - Export validated extraction to JSON and BETYdb bulk upload CSV.
"""

import json
import csv
from pathlib import Path


OUTPUT_DIR = Path(__file__).parent.parent / "output"


def export_results(validated_dict: dict, doi: str) -> tuple[Path, Path]:
    """
    Export validated extraction results.

    Outputs:
        - output/extracted.json  (full intermediate representation)
        - output/bety_upload.csv (BETYdb bulk upload format)

    Args:
        validated_dict: Output from validate_extraction()
        doi: Citation DOI string (e.g. "10.xxxx/xxxxx")

    Returns:
        Tuple of (json_path, csv_path)
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    # ---- 1. Save full IR JSON ----
    json_path = OUTPUT_DIR / "extracted.json"
    export_data = {k: v for k, v in validated_dict.items() if not k.startswith("_")}
    export_data["doi"] = doi

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    print(f"[export] Full IR JSON saved to {json_path}")

    # ---- 2. Build BETYdb CSV ----
    csv_path = OUTPUT_DIR / "bety_upload.csv"

    site = validated_dict.get("site", {})
    species = validated_dict.get("species", {})
    traits = validated_dict.get("traits", [])

    def val(field_dict):
        """Extract the value from a field dict, return empty string if missing/None."""
        if isinstance(field_dict, dict):
            v = field_dict.get("value")
            return "" if v is None else str(v)
        return "" if field_dict is None else str(field_dict)

    def stat(field_dict):
        if isinstance(field_dict, dict):
            return field_dict.get("status", "UNRESOLVED")
        return "UNRESOLVED"

    def evid(field_dict):
        if isinstance(field_dict, dict):
            return field_dict.get("evidence_quote", "")[:120]
        return ""

    rows = []
    for trait in traits:
        row = {
            "citation_doi": doi,
            "site_name": val(site.get("name")),
            "lat": val(site.get("lat")),
            "lon": val(site.get("lon")),
            "country": val(site.get("country")),
            "species": val(species.get("scientific_name")),
            "common_name": val(species.get("common_name")),
            "treatment": val(trait.get("treatment")),
            "date": val(trait.get("date")),
            "variable_name": val(trait.get("variable_name")),
            "mean": val(trait.get("mean")),
            "SE": val(trait.get("SE")),
            "n": val(trait.get("n")),
            "units": val(trait.get("units")),
            "status": stat(trait.get("mean")),
            "evidence": evid(trait.get("mean")),
        }
        rows.append(row)

    if not rows:
        # Write header-only CSV if no traits found
        rows = [{
            "citation_doi": doi, "site_name": val(site.get("name")),
            "lat": val(site.get("lat")), "lon": val(site.get("lon")),
            "country": val(site.get("country")),
            "species": val(species.get("scientific_name")),
            "common_name": val(species.get("common_name")),
            "treatment": "", "date": "", "variable_name": "",
            "mean": "", "SE": "", "n": "", "units": "",
            "status": "UNRESOLVED", "evidence": "",
        }]

    fieldnames = [
        "citation_doi", "site_name", "lat", "lon", "country",
        "species", "common_name", "treatment", "date", "variable_name",
        "mean", "SE", "n", "units", "status", "evidence",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[export] BETYdb CSV saved to {csv_path} ({len(rows)} rows)")
    return json_path, csv_path
