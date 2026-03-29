"""
extract_figures.py - Extract figures from PDF using Docling, then analyze with Claude Vision.
Usage: from src.extract_figures import extract_and_analyze_figures
"""

import anthropic
import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = Path(__file__).parent.parent / "output"
FIGURES_DIR = OUTPUT_DIR / "figures"
FIGURE_JSON_PATH = OUTPUT_DIR / "figure_extraction.json"

VISION_PROMPT = """This is a figure from a scientific paper about miscanthus and switchgrass biomass yields in UK and France.
Look at this figure carefully.
1. What variable is shown on the Y axis? Include units.
2. What is on the X axis?
3. What species or treatments are shown (list each series)?
4. Read off as many data point values as you can from the chart.
5. For each value you can read directly from an axis label: status=EXTRACTED
   For each value you estimated between gridlines: status=INFERRED
Return ONLY valid JSON with this structure:
{
  "figure_id": "...",
  "y_axis_variable": "...",
  "y_axis_units": "...",
  "x_axis": "...",
  "series": ["..."],
  "data_points": [
    {"series": "...", "x_value": ..., "y_value": ..., "status": "EXTRACTED|INFERRED", "confidence": "HIGH|MEDIUM|LOW"}
  ]
}"""


def _extract_figure_images(pdf_path: str) -> list[dict]:
    """Use Docling to extract figure images from PDF. Returns list of {figure_id, path, page}."""
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    # Try to import PdfFormatOption (Docling v2+)
    try:
        from docling.document_converter import PdfFormatOption
        pipeline_options = PdfPipelineOptions()
        pipeline_options.images_scale = 2.0
        pipeline_options.generate_picture_images = True
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
    except ImportError:
        # Fallback: basic converter without picture image generation
        converter = DocumentConverter()

    print(f"[figures] Converting PDF with Docling (picture extraction enabled)...")
    result = converter.convert(pdf_path)
    doc = result.document

    figures = []
    figure_count = 0

    for element, _level in doc.iterate_items():
        element_type = type(element).__name__
        if element_type != "PictureItem":
            continue

        figure_count += 1
        figure_id = f"fig_{figure_count:02d}"
        fig_path = FIGURES_DIR / f"{figure_id}.png"

        saved = False

        # Strategy 1: element.get_image(doc) — Docling v2 standard
        if hasattr(element, "get_image"):
            try:
                img = element.get_image(doc)
                if img is not None:
                    img.save(str(fig_path), "PNG")
                    saved = True
            except Exception as e:
                print(f"  [figures] get_image() failed for {figure_id}: {e}")

        # Strategy 2: element.image.pil_image — some Docling versions
        if not saved and hasattr(element, "image"):
            try:
                raw_img = element.image
                if hasattr(raw_img, "pil_image") and raw_img.pil_image is not None:
                    raw_img.pil_image.save(str(fig_path), "PNG")
                    saved = True
                elif hasattr(raw_img, "save"):
                    raw_img.save(str(fig_path), "PNG")
                    saved = True
            except Exception as e:
                print(f"  [figures] image attr failed for {figure_id}: {e}")

        if not saved:
            print(f"  [figures] Could not save image for {figure_id} — skipping")
            continue

        # Get page number from provenance
        page_no = None
        if hasattr(element, "prov") and element.prov:
            try:
                page_no = element.prov[0].page_no
            except (IndexError, AttributeError):
                pass

        figures.append({
            "figure_id": figure_id,
            "path": str(fig_path),
            "page": page_no,
        })
        print(f"  Saved figure {figure_id} (page {page_no}) → {fig_path}")

    return figures


def _analyze_figure_with_claude(client: anthropic.Anthropic, figure_id: str, fig_path: str) -> dict:
    """Send a figure PNG to Claude Vision and return parsed JSON analysis."""
    with open(fig_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    prompt = VISION_PROMPT.replace('"figure_id": "..."', f'"figure_id": "{figure_id}"')

    print(f"  [vision] Analyzing {figure_id} with Claude vision...")
    try:
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )
        response_text = message.content[0].text
    except Exception as e:
        print(f"  [vision] Claude API error for {figure_id}: {e}")
        return {
            "figure_id": figure_id,
            "error": str(e),
            "data_points": [],
        }

    # Parse JSON from response
    import re

    text = response_text.strip()

    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        parsed["figure_id"] = figure_id  # ensure figure_id is set
        return parsed
    except json.JSONDecodeError:
        # Try to extract JSON object with regex
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                parsed["figure_id"] = figure_id
                return parsed
            except json.JSONDecodeError:
                pass

    return {
        "figure_id": figure_id,
        "raw_response": response_text[:500],
        "error": "JSON parse failed",
        "data_points": [],
    }


def extract_and_analyze_figures(pdf_path: str) -> dict:
    """
    Full figure extraction pipeline:
    1. Use Docling to find and save all figures as PNGs
    2. Analyze each figure PNG with Claude Vision
    3. Save results to output/figure_extraction.json

    Returns:
        dict with keys: figures_found, results, summary
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
    client = anthropic.Anthropic(api_key=api_key)

    # Step 1: Extract figure images
    figures = _extract_figure_images(pdf_path)

    if not figures:
        print("[figures] No figures extracted from PDF.")
        result = {
            "figures_found": 0,
            "results": [],
            "summary": {
                "figures_found": 0,
                "figures_analyzed": 0,
                "total_data_points": 0,
                "status_breakdown": {},
            },
        }
        with open(FIGURE_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    # Step 2: Analyze each figure with Claude Vision
    print(f"\n[figures] Analyzing {len(figures)} figures with Claude Vision...")
    analysis_results = []
    for fig in figures:
        analysis = _analyze_figure_with_claude(client, fig["figure_id"], fig["path"])
        analysis["page"] = fig.get("page")
        analysis_results.append(analysis)

    # Step 3: Build summary
    total_data_points = sum(
        len(r.get("data_points", [])) for r in analysis_results
    )
    status_counts: dict[str, int] = {}
    for r in analysis_results:
        for dp in r.get("data_points", []):
            s = dp.get("status", "UNKNOWN")
            status_counts[s] = status_counts.get(s, 0) + 1

    summary = {
        "figures_found": len(figures),
        "figures_analyzed": len(analysis_results),
        "total_data_points": total_data_points,
        "status_breakdown": status_counts,
    }

    output = {
        "figures_found": len(figures),
        "results": analysis_results,
        "summary": summary,
    }

    # Step 4: Save JSON
    with open(FIGURE_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\n[figures] Results saved to {FIGURE_JSON_PATH}")

    # Step 5: Print summary
    print("\n" + "=" * 60)
    print("  FIGURE EXTRACTION SUMMARY")
    print("=" * 60)
    print(f"  Figures found      : {summary['figures_found']}")
    print(f"  Figures analyzed   : {summary['figures_analyzed']}")
    print(f"  Total data points  : {summary['total_data_points']}")
    if status_counts:
        print(f"  Status breakdown:")
        for status, count in sorted(status_counts.items()):
            print(f"    {status:12s}: {count}")
    print()
    for r in analysis_results:
        fig_id = r.get("figure_id", "?")
        y_var = r.get("y_axis_variable", "?")
        y_units = r.get("y_axis_units", "")
        x_ax = r.get("x_axis", "?")
        series = r.get("series", [])
        dp_count = len(r.get("data_points", []))
        page = r.get("page", "?")
        print(f"  [{fig_id}] (page {page})")
        print(f"    Y-axis   : {y_var} ({y_units})")
        print(f"    X-axis   : {x_ax}")
        if series:
            print(f"    Series   : {', '.join(str(s) for s in series)}")
        print(f"    Data pts : {dp_count}")
        print()
    print("=" * 60)

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/extract_figures.py <pdf_path>")
        sys.exit(1)
    extract_and_analyze_figures(sys.argv[1])
