"""
summary.py - Generate a human-readable extraction report saved to output/.
"""

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"
REPORT_PATH = OUTPUT_DIR / "extraction_report.txt"


def _val(field: dict | None) -> str:
    if not isinstance(field, dict):
        return "—"
    v = field.get("value")
    return str(v) if v is not None else "—"


def _status(field: dict | None) -> str:
    if not isinstance(field, dict):
        return "UNRESOLVED"
    return field.get("status", "UNRESOLVED")


def generate_report(validated_dict: dict, doi: str) -> Path:
    """
    Generate a human-readable extraction report and save to output/extraction_report.txt.

    Args:
        validated_dict: Output from validate_extraction()
        doi:            Citation DOI string

    Returns:
        Path to the written report file.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    site = validated_dict.get("site", {})
    species = validated_dict.get("species", {})
    traits = validated_dict.get("traits", [])
    stats = validated_dict.get("_stats", {})

    total = sum(stats.values())
    extracted = stats.get("EXTRACTED", 0)
    inferred = stats.get("INFERRED", 0)
    unresolved = stats.get("UNRESOLVED", 0)

    def pct(n):
        return f"{round(n / total * 100, 1)}%" if total else "0%"

    lines = []
    lines.append("=" * 70)
    lines.append("  PECAN LLM EXTRACTION REPORT")
    lines.append("=" * 70)
    lines.append("")

    # --- Citation ---
    lines.append("CITATION")
    lines.append("-" * 40)
    lines.append(f"  DOI     : {doi}")
    # Try to find a title field in traits (not always present)
    lines.append("")

    # --- Site ---
    lines.append("SITE")
    lines.append("-" * 40)
    for key, field in site.items():
        lines.append(f"  {key:12s}: {_val(field):30s} [{_status(field)}]")
    lines.append("")

    # --- Species ---
    lines.append("SPECIES")
    lines.append("-" * 40)
    for key, field in species.items():
        lines.append(f"  {key:20s}: {_val(field):28s} [{_status(field)}]")
    lines.append("")

    # --- Trait counts ---
    lines.append(f"TRAITS / YIELDS")
    lines.append("-" * 40)
    lines.append(f"  Total observations : {len(traits)}")
    lines.append("")

    # --- Status breakdown ---
    lines.append("STATUS BREAKDOWN")
    lines.append("-" * 40)
    lines.append(f"  Total fields  : {total}")
    lines.append(f"  EXTRACTED     : {extracted:3d}  ({pct(extracted)})")
    lines.append(f"  INFERRED      : {inferred:3d}  ({pct(inferred)})")
    lines.append(f"  UNRESOLVED    : {unresolved:3d}  ({pct(unresolved)})")
    lines.append("")

    # --- Top 5 trait rows with evidence ---
    lines.append("TOP TRAIT OBSERVATIONS (with evidence quotes)")
    lines.append("-" * 70)
    shown = 0
    for trait in traits:
        if shown >= 5:
            break
        var = trait.get("variable_name", {})
        mean = trait.get("mean", {})
        units = trait.get("units", {})
        treat = trait.get("treatment", {})
        evidence = mean.get("evidence_quote", "") if isinstance(mean, dict) else ""

        var_val = _val(var)
        if var_val == "—":
            continue

        lines.append(f"  Variable  : {var_val}  [{_status(var)}]")
        lines.append(f"  Mean      : {_val(mean)} {_val(units)}  [{_status(mean)}]")
        lines.append(f"  Treatment : {_val(treat)}")
        if evidence:
            # Wrap long evidence quotes at 65 chars
            quote = evidence[:200]
            lines.append(f"  Evidence  : \"{quote}\"")
        lines.append("")
        shown += 1

    if not shown:
        lines.append("  (No trait observations extracted)")
        lines.append("")

    # --- Validation warnings ---
    warnings = []
    if unresolved > 0:
        warnings.append(f"{unresolved} field(s) could not be resolved from the paper.")
    if _val(site.get("lat")) == "—" or _val(site.get("lon")) == "—":
        warnings.append("Site coordinates missing — may need manual lookup.")
    if _val(species.get("scientific_name")) == "—":
        warnings.append("Scientific name not found — check species section of paper.")
    if len(traits) == 0:
        warnings.append("No trait/yield observations extracted.")

    lines.append("VALIDATION WARNINGS")
    lines.append("-" * 40)
    if warnings:
        for w in warnings:
            lines.append(f"  ! {w}")
    else:
        lines.append("  None — all fields resolved successfully.")
    lines.append("")
    lines.append("=" * 70)

    report_text = "\n".join(lines)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[summary] Report saved to {REPORT_PATH}")
    return REPORT_PATH
