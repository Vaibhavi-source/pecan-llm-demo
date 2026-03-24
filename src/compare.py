"""
compare.py - Compare pipeline output against BETYdb ground truth via API.
"""

import csv
import json
import urllib.request
import urllib.parse
from pathlib import Path


BETY_API_BASE = "https://www.betydb.org"


def _fetch_bety_yields(doi: str) -> list[dict]:
    """
    Fetch yield records from BETYdb public API filtered by DOI.

    Returns a list of yield dicts from BETYdb, or [] if none found.
    """
    # BETYdb citations endpoint to find citation id for this DOI
    citation_url = (
        f"{BETY_API_BASE}/citations.json"
        f"?doi={urllib.parse.quote(doi, safe='')}&fmt=json"
    )
    try:
        with urllib.request.urlopen(citation_url, timeout=15) as resp:
            citations = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[compare] Warning: could not reach BETYdb citations API: {e}")
        return []

    # citations.json returns {"data": [...]} or a list
    if isinstance(citations, dict):
        citation_list = citations.get("data", [])
    else:
        citation_list = citations

    if not citation_list:
        print(f"[compare] No BETYdb citations found for DOI: {doi}")
        return []

    citation_id = citation_list[0].get("id") or citation_list[0].get("citation", {}).get("id")
    if not citation_id:
        print("[compare] Could not parse citation id from BETYdb response.")
        return []

    print(f"[compare] Found BETYdb citation id={citation_id} for DOI {doi}")

    # Fetch yields for this citation
    yields_url = (
        f"{BETY_API_BASE}/yields.json"
        f"?type=All&fmt=json&citation_id={citation_id}"
    )
    try:
        with urllib.request.urlopen(yields_url, timeout=15) as resp:
            yields_resp = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[compare] Warning: could not fetch yields: {e}")
        return []

    if isinstance(yields_resp, dict):
        return yields_resp.get("data", [])
    return yields_resp


def _normalize(value) -> str:
    """Normalize a value to a comparable string."""
    if value is None:
        return ""
    return str(value).strip().lower()


def _values_match(pipeline_val, bety_val, tolerance: float = 0.05) -> bool:
    """
    Check if two values match. Numeric values use a relative tolerance.
    """
    p = _normalize(pipeline_val)
    b = _normalize(bety_val)
    if not p or not b:
        return False
    if p == b:
        return True
    # Try numeric comparison
    try:
        pf = float(p)
        bf = float(b)
        if bf == 0:
            return pf == 0
        return abs(pf - bf) / abs(bf) <= tolerance
    except ValueError:
        return False


def compare_with_bety(csv_path: str | Path, doi: str) -> dict:
    """
    Compare pipeline output CSV against BETYdb ground truth for a given DOI.

    Args:
        csv_path: Path to output/bety_upload.csv
        doi:      Citation DOI string

    Returns:
        dict with keys:
          pipeline_rows   - list of pipeline row dicts
          bety_rows       - list of BETYdb yield dicts
          comparisons     - list of comparison result dicts
          accuracy        - dict with matched/total/pct
    """
    csv_path = Path(csv_path)

    # Load pipeline rows
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    with open(csv_path, encoding="utf-8") as f:
        pipeline_rows = list(csv.DictReader(f))

    print(f"[compare] Loaded {len(pipeline_rows)} pipeline rows from {csv_path.name}")

    # Fetch BETYdb ground truth
    bety_rows = _fetch_bety_yields(doi)
    print(f"[compare] Fetched {len(bety_rows)} BETYdb yield records")

    if not bety_rows:
        print("[compare] No BETYdb data to compare against.")
        return {
            "pipeline_rows": pipeline_rows,
            "bety_rows": [],
            "comparisons": [],
            "accuracy": {"matched": 0, "total": 0, "pct": 0.0},
        }

    # Build comparison table
    # Match pipeline rows to BETYdb rows by variable name (best-effort)
    comparisons = []
    matched = 0

    for p_row in pipeline_rows:
        p_var = _normalize(p_row.get("variable_name", ""))
        p_mean = p_row.get("mean", "")
        p_units = p_row.get("units", "")

        # Find the closest BETYdb row by variable name
        best_bety = None
        for b in bety_rows:
            b_var = _normalize(
                b.get("trait", {}).get("name", "") if isinstance(b.get("trait"), dict)
                else b.get("variable_name", b.get("trait_name", ""))
            )
            if b_var and p_var and (b_var in p_var or p_var in b_var):
                best_bety = b
                break

        if best_bety is not None:
            b_mean = (
                best_bety.get("yield", {}).get("mean")
                if isinstance(best_bety.get("yield"), dict)
                else best_bety.get("mean", best_bety.get("yield_mean", ""))
            )
            b_units = (
                best_bety.get("yield", {}).get("units")
                if isinstance(best_bety.get("yield"), dict)
                else best_bety.get("units", "")
            )
            match = _values_match(p_mean, b_mean)
            if match:
                matched += 1
            comparisons.append({
                "variable": p_row.get("variable_name", ""),
                "pipeline_mean": p_mean,
                "bety_mean": str(b_mean) if b_mean is not None else "",
                "pipeline_units": p_units,
                "bety_units": str(b_units) if b_units is not None else "",
                "match": "YES" if match else "NO",
            })
        else:
            comparisons.append({
                "variable": p_row.get("variable_name", ""),
                "pipeline_mean": p_mean,
                "bety_mean": "(not found in BETYdb)",
                "pipeline_units": p_units,
                "bety_units": "",
                "match": "NO",
            })

    total = len(comparisons)
    pct = round(matched / total * 100, 1) if total else 0.0

    # Print side-by-side table
    print("\n" + "-" * 90)
    print(f"  {'Variable':22s} {'Pipeline':14s} {'BETYdb':14s} {'P.Units':12s} {'B.Units':12s} Match")
    print(f"  {'-'*22} {'-'*14} {'-'*14} {'-'*12} {'-'*12} -----")
    for c in comparisons:
        print(
            f"  {str(c['variable'])[:22]:22s} "
            f"{str(c['pipeline_mean'])[:14]:14s} "
            f"{str(c['bety_mean'])[:14]:14s} "
            f"{str(c['pipeline_units'])[:12]:12s} "
            f"{str(c['bety_units'])[:12]:12s} "
            f"{c['match']}"
        )
    print("-" * 90)
    print(f"  Accuracy: {matched}/{total} matched ({pct}%)")
    print("-" * 90)

    return {
        "pipeline_rows": pipeline_rows,
        "bety_rows": bety_rows,
        "comparisons": comparisons,
        "accuracy": {"matched": matched, "total": total, "pct": pct},
    }
