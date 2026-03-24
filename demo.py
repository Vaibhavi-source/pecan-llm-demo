"""
demo.py - Full pipeline: ingest -> extract -> validate -> export -> compare -> report
Usage: python demo.py data/papers/paper.pdf --doi 10.xxxx/xxxxx
"""

import argparse
import csv
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))

from src.ingest import ingest_pdf
from src.extract import extract_from_markdown
from src.validate import validate_extraction
from src.export import export_results
from src.compare import compare_with_bety
from src.summary import generate_report

# DOI for the ground-truth paper used to validate the pipeline
GROUND_TRUTH_DOI = "10.1111/gcbb.12077"


def print_summary(validated_dict: dict, csv_path: Path):
    """Print a human-readable summary of the extraction results."""
    stats = validated_dict.get("_stats", {})
    site = validated_dict.get("site", {})
    species = validated_dict.get("species", {})
    traits = validated_dict.get("traits", [])

    print("\n" + "=" * 60)
    print("  EXTRACTION SUMMARY")
    print("=" * 60)

    # Status counts
    total = sum(stats.values())
    print(f"\nField status breakdown ({total} total fields):")
    print(f"  EXTRACTED  : {stats.get('EXTRACTED', 0)}")
    print(f"  INFERRED   : {stats.get('INFERRED', 0)}")
    print(f"  UNRESOLVED : {stats.get('UNRESOLVED', 0)}")

    # Site summary
    print("\nSite:")
    for key, field in site.items():
        if isinstance(field, dict):
            v = field.get("value", "—")
            s = field.get("status", "?")
            c = field.get("confidence", "?")
            print(f"  {key:12s}: {str(v):30s} [{s} / {c}]")

    # Species summary
    print("\nSpecies:")
    for key, field in species.items():
        if isinstance(field, dict):
            v = field.get("value", "—")
            s = field.get("status", "?")
            c = field.get("confidence", "?")
            print(f"  {key:20s}: {str(v):30s} [{s} / {c}]")

    # Traits summary
    print(f"\nTraits/Yields ({len(traits)} observations):")
    print(f"  {'Variable':25s} {'Mean':12s} {'Units':15s} {'Status'}")
    print(f"  {'-'*25} {'-'*12} {'-'*15} {'-'*12}")
    for trait in traits[:10]:
        var = trait.get("variable_name", {})
        mean = trait.get("mean", {})
        units = trait.get("units", {})
        print(
            f"  {str(var.get('value','—')):25s} "
            f"{str(mean.get('value','—')):12s} "
            f"{str(units.get('value','—')):15s} "
            f"{mean.get('status','?')}"
        )
    if len(traits) > 10:
        print(f"  ... and {len(traits) - 10} more rows")

    # Sample CSV output
    print(f"\nSample BETYdb CSV rows from {csv_path}:")
    print("-" * 60)
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                cols = ["variable_name", "mean", "units", "status", "site_name"]
                print("  " + " | ".join(f"{c:18s}" for c in cols))
                print("  " + "-" * (len(cols) * 21))
                for row in rows[:5]:
                    print("  " + " | ".join(f"{str(row.get(c,''))[:18]:18s}" for c in cols))
                if len(rows) > 5:
                    print(f"  ... ({len(rows)} total rows in CSV)")
    except Exception as e:
        print(f"  (Could not read CSV preview: {e})")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="PEcAn LLM Demo: Extract BETYdb traits from a scientific PDF"
    )
    parser.add_argument("pdf_path", help="Path to the input PDF file")
    parser.add_argument(
        "--doi",
        default="10.0000/unknown",
        help="Citation DOI (e.g. 10.1234/example)",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: PDF not found at '{pdf_path}'")
        sys.exit(1)

    print(f"\nPEcAn LLM Demo Pipeline")
    print(f"PDF  : {pdf_path}")
    print(f"DOI  : {args.doi}")
    print("-" * 40)

    # Step 1: Ingest
    markdown = ingest_pdf(str(pdf_path))

    # Step 2: Extract
    raw_extraction = extract_from_markdown(markdown)

    # Step 3: Validate
    validated = validate_extraction(raw_extraction)

    # Step 4: Export
    json_path, csv_path = export_results(validated, doi=args.doi)

    # Step 5: Print inline summary
    print_summary(validated, csv_path)

    # Step 6: BETYdb accuracy comparison (only for ground-truth DOI)
    if args.doi == GROUND_TRUTH_DOI:
        print(f"\n[compare] Running BETYdb ground-truth comparison for DOI {args.doi}...")
        try:
            compare_results = compare_with_bety(csv_path, args.doi)
            acc = compare_results["accuracy"]
            print(
                f"\n  Pipeline accuracy vs BETYdb: "
                f"{acc['matched']}/{acc['total']} ({acc['pct']}%)"
            )
        except Exception as e:
            print(f"  [compare] Skipped: {e}")

    # Step 7: Generate text report
    report_path = generate_report(validated, doi=args.doi)

    print(f"\nOutputs saved:")
    print(f"  JSON   : {json_path}")
    print(f"  CSV    : {csv_path}")
    print(f"  Report : {report_path}")


if __name__ == "__main__":
    main()
