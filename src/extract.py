"""
extract.py - Multi-turn LLM extraction of BETYdb fields using Anthropic API.
"""

import json
import os
import re
import anthropic
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """You are a scientific data extraction assistant specializing in ecological and agricultural research papers.
Your task is to extract structured data for the BETYdb (Biofuel Ecophysiological Traits and Yields database).

For each field you extract, you must provide:
- value: the extracted value (string, number, or null if not found)
- status: one of EXTRACTED (directly stated), INFERRED (derived/calculated), or UNRESOLVED (not found)
- confidence: one of HIGH, MEDIUM, or LOW
- evidence_quote: the exact quote from the paper supporting this value (or "" if UNRESOLVED)

Always respond with valid JSON only. No explanations outside the JSON."""

TRAIT_SCHEMA = """{
  "traits": [
    {
      "variable_name": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."},
      "mean": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."},
      "SE": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."},
      "n": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."},
      "units": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."},
      "date": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."},
      "treatment": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."}
    }
  ]
}"""


def _call_claude(
    client: anthropic.Anthropic,
    messages: list,
    prompt: str,
    max_tokens: int = 2048,
) -> tuple[str, list]:
    """Send a message to Claude and return the response text and updated messages."""
    messages.append({"role": "user", "content": prompt})

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    assistant_text = response.content[0].text
    messages.append({"role": "assistant", "content": assistant_text})
    return assistant_text, messages


def _parse_json_response(text: str, fallback_key: str = "") -> dict:
    """
    Parse JSON from model response with graceful fallback.

    Strategy:
      1. Strip markdown fences and try normal json.loads().
      2. If that fails, try to salvage a partial array using regex
         (useful when a large traits list gets truncated mid-stream).
      3. If that also fails, return {fallback_key: []} (or {}) and warn.
    """
    # --- Step 1: strip markdown fences ---
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop opening fence line
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # --- Step 2: normal parse ---
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # --- Step 3: regex salvage of partial array ---
    if fallback_key:
        # Find the opening of the array for fallback_key
        array_pattern = re.compile(
            rf'"{re.escape(fallback_key)}"\s*:\s*(\[.*)',
            re.DOTALL,
        )
        m = array_pattern.search(text)
        if m:
            array_text = m.group(1)
            # Try to close the array by finding the last complete object
            # Walk backwards from the end until we find a valid JSON array
            for end in range(len(array_text), 0, -1):
                candidate = array_text[:end]
                # Ensure it ends with a valid JSON array close
                candidate = candidate.rstrip()
                if not candidate.endswith("]"):
                    # Try appending ]} to close it
                    try:
                        salvaged = json.loads(candidate + "]")
                        print(
                            f"[extract] Warning: JSON was truncated — salvaged "
                            f"{len(salvaged)} partial {fallback_key} items."
                        )
                        return {fallback_key: salvaged}
                    except json.JSONDecodeError:
                        continue
                else:
                    try:
                        salvaged = json.loads(candidate)
                        print(
                            f"[extract] Warning: JSON was truncated — salvaged "
                            f"{len(salvaged)} partial {fallback_key} items."
                        )
                        return {fallback_key: salvaged}
                    except json.JSONDecodeError:
                        continue

    # --- Step 4: total fallback ---
    empty: dict = {fallback_key: []} if fallback_key else {}
    print(
        f"[extract] Warning: Could not parse JSON response "
        f"(returning empty {fallback_key or 'dict'}). "
        f"Raw text starts with: {text[:120]!r}"
    )
    return empty


def extract_from_markdown(markdown: str) -> dict:
    """
    Run iterative multi-turn extraction of BETYdb fields from paper markdown.

    Turn 1 : Extract site information
    Turn 2 : Extract species information
    Turn 3a: Extract first 10 trait/yield measurements
    Turn 3b: Extract any remaining measurements

    Args:
        markdown: Markdown string from ingest_pdf()

    Returns:
        Dictionary with site, species, and traits keys.
        If any turn fails the pipeline continues with whatever was extracted.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")

    client = anthropic.Anthropic(api_key=api_key)
    messages: list = []

    paper_context = f"""Here is a scientific paper in markdown format. Please extract data from it as I ask.

--- PAPER START ---
{markdown[:20000]}
--- PAPER END ---

I will ask you to extract specific fields. Respond only with valid JSON."""

    # Defaults so later merge always has these keys
    site_data: dict = {"site": {}}
    species_data: dict = {"species": {}}
    traits_data: dict = {"traits": []}

    # ------------------------------------------------------------------
    # Turn 1: Site
    # ------------------------------------------------------------------
    print("[extract] Turn 1: Extracting site information...")
    try:
        turn1_prompt = f"""{paper_context}

Extract the SITE information from this paper. Return a JSON object with this exact structure:
{{
  "site": {{
    "name": {{"value": ..., "status": "EXTRACTED|INFERRED|UNRESOLVED", "confidence": "HIGH|MEDIUM|LOW", "evidence_quote": "..."}},
    "lat": {{"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."}},
    "lon": {{"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."}},
    "country": {{"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."}}
  }}
}}"""
        response1, messages = _call_claude(client, messages, turn1_prompt)
        site_data = _parse_json_response(response1)
    except Exception as e:
        print(f"[extract] Turn 1 failed: {e} — continuing with empty site.")

    # ------------------------------------------------------------------
    # Turn 2: Species
    # ------------------------------------------------------------------
    print("[extract] Turn 2: Extracting species information...")
    try:
        turn2_prompt = """Now extract the SPECIES information from the same paper. Return a JSON object:
{
  "species": {
    "scientific_name": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."},
    "common_name": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."}
  }
}"""
        response2, messages = _call_claude(client, messages, turn2_prompt)
        species_data = _parse_json_response(response2)
    except Exception as e:
        print(f"[extract] Turn 2 failed: {e} — continuing with empty species.")

    # ------------------------------------------------------------------
    # Turn 3a: First 10 trait/yield measurements
    # ------------------------------------------------------------------
    print("[extract] Turn 3a: Extracting first 10 trait/yield measurements...")
    all_traits: list = []
    try:
        turn3a_prompt = f"""Now extract the TRAITS and YIELD data from the paper.
Return ONLY the first 10 distinct trait/yield measurements you find.
Include yield, biomass, LAI, SLA, or any other quantitative measurements.
Use this exact JSON structure:
{TRAIT_SCHEMA}"""
        response3a, messages = _call_claude(client, messages, turn3a_prompt, max_tokens=4096)
        traits3a = _parse_json_response(response3a, fallback_key="traits")
        batch_a = traits3a.get("traits", [])
        all_traits.extend(batch_a)
        print(f"[extract] Turn 3a: got {len(batch_a)} observations.")
    except Exception as e:
        print(f"[extract] Turn 3a failed: {e} — continuing with empty traits.")

    # ------------------------------------------------------------------
    # Turn 3b: Any remaining measurements (only if Turn 3a succeeded)
    # ------------------------------------------------------------------
    if all_traits:
        print("[extract] Turn 3b: Extracting any remaining trait/yield measurements...")
        try:
            turn3b_prompt = f"""You already returned the first {len(all_traits)} trait measurements.
Now extract ANY REMAINING trait/yield measurements from the paper that you have not yet reported.
If there are no additional measurements, return: {{"traits": []}}
Use the same JSON structure:
{TRAIT_SCHEMA}"""
            response3b, messages = _call_claude(client, messages, turn3b_prompt, max_tokens=4096)
            traits3b = _parse_json_response(response3b, fallback_key="traits")
            batch_b = traits3b.get("traits", [])
            if batch_b:
                all_traits.extend(batch_b)
                print(f"[extract] Turn 3b: got {len(batch_b)} additional observations.")
            else:
                print("[extract] Turn 3b: no additional observations.")
        except Exception as e:
            print(f"[extract] Turn 3b failed: {e} — using Turn 3a results only.")

    traits_data = {"traits": all_traits}

    # ------------------------------------------------------------------
    # Merge all turns
    # ------------------------------------------------------------------
    result: dict = {}
    result.update(site_data)
    result.update(species_data)
    result.update(traits_data)

    print(f"[extract] Extraction complete. Found {len(result.get('traits', []))} trait observations.")
    return result
