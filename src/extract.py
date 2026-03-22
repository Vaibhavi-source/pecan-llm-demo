"""
extract.py - Multi-turn LLM extraction of BETYdb fields using Anthropic API.
"""

import json
import os
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


def _call_claude(client: anthropic.Anthropic, messages: list, prompt: str) -> tuple[str, list]:
    """Send a message to Claude and return the response text and updated messages."""
    messages.append({"role": "user", "content": prompt})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    assistant_text = response.content[0].text
    messages.append({"role": "assistant", "content": assistant_text})
    return assistant_text, messages


def _parse_json_response(text: str) -> dict:
    """Parse JSON from model response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove opening fence
        lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def extract_from_markdown(markdown: str) -> dict:
    """
    Run iterative multi-turn extraction of BETYdb fields from paper markdown.

    Turn 1: Extract site information
    Turn 2: Extract species information
    Turn 3: Extract traits/yields

    Args:
        markdown: Markdown string from ingest_pdf()

    Returns:
        Dictionary with site, species, and traits keys.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")

    client = anthropic.Anthropic(api_key=api_key)
    messages = []

    # Provide paper context as the first user message (not in messages yet — we'll include inline)
    paper_context = f"""Here is a scientific paper in markdown format. Please extract data from it as I ask.

--- PAPER START ---
{markdown[:12000]}
--- PAPER END ---

I will ask you to extract specific fields. Respond only with valid JSON."""

    # Turn 1: Site extraction
    print("[extract] Turn 1: Extracting site information...")
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

    # Turn 2: Species extraction
    print("[extract] Turn 2: Extracting species information...")
    turn2_prompt = """Now extract the SPECIES information from the same paper. Return a JSON object:
{
  "species": {
    "scientific_name": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."},
    "common_name": {"value": ..., "status": "...", "confidence": "...", "evidence_quote": "..."}
  }
}"""

    response2, messages = _call_claude(client, messages, turn2_prompt)
    species_data = _parse_json_response(response2)

    # Turn 3: Traits/yields extraction
    print("[extract] Turn 3: Extracting traits and yield data...")
    turn3_prompt = """Now extract the TRAITS and YIELD data. Return a JSON object with a list of trait observations:
{
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
}
Extract ALL distinct trait/yield measurements you can find. Include yield, biomass, LAI, SLA, or any other quantitative measurements."""

    response3, messages = _call_claude(client, messages, turn3_prompt)
    traits_data = _parse_json_response(response3)

    # Merge all turns
    result = {}
    result.update(site_data)
    result.update(species_data)
    result.update(traits_data)

    print(f"[extract] Extraction complete. Found {len(result.get('traits', []))} trait observations.")
    return result
