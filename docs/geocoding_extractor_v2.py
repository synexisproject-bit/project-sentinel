"""
extractor.py — LLM-based place name extraction from dream records.

Uses claude-haiku-4-5 for cost efficiency (~15k records).
llm_extracted_symbols is a JSON array of strings e.g. ["tsunami", "moon", "backyard"]
Place extraction comes primarily from narrative_text.
"""

import json
import logging

import anthropic

log = logging.getLogger(__name__)

EXTRACTION_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are a geographic entity extractor for a scientific dream research database.
Your task: identify real-world place names from dream narrative text and symbol lists.

Rules:
- Extract ONLY real geographic places (cities, countries, regions, bodies of water, landmarks, streets, neighborhoods)
- Include both explicit mentions ("I was in Paris") and implicit ones ("near the Eiffel Tower" → Paris, France)
- Order by specificity and confidence — most geocodable first
- EXCLUDE: fictional places, vague references ("a city", "the ocean", "an island"), purely symbolic geography
- If no real places are identifiable, return an empty array
- Return ONLY valid JSON — no commentary, no markdown fences

Output format:
{"places": ["place1", "place2", ...]}

Examples:
- "I was swimming in the Thames near Tower Bridge" → {"places": ["Tower Bridge, London", "River Thames, London", "London, UK"]}
- "driving through the desert" → {"places": []}
- "my grandmother's house in Cleveland" → {"places": ["Cleveland, Ohio, USA"]}
- "an island with volcanoes" → {"places": []}
- "riding through amazing parks in Mexico City" → {"places": ["Mexico City, Mexico"]}
"""


def extract_place_names(
    client: anthropic.Anthropic,
    symbols_json: str,
    narrative_text: str,
    max_retries: int = 2,
) -> list[str]:
    """
    Extract place names from a dream record using Claude.
    symbols_json is a JSON array of symbol strings e.g. ["tsunami", "moon"]
    """
    # Extract any geographic hints from the flat symbol array
    place_hints = _extract_place_hints_from_symbols(symbols_json)

    parts = []
    if narrative_text and narrative_text.strip():
        parts.append(f"DREAM NARRATIVE:\n{narrative_text.strip()[:2000]}")
    if place_hints:
        parts.append(f"GEOGRAPHIC SYMBOLS DETECTED: {json.dumps(place_hints)}")

    if not parts:
        return []

    user_message = "\n\n".join(parts)
    user_message += "\n\nExtract all real geographic place names from the above."

    for attempt in range(max_retries + 1):
        try:
            response = client.messages.create(
                model=EXTRACTION_MODEL,
                max_tokens=256,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            raw = response.content[0].text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            places = data.get("places", [])
            if isinstance(places, list):
                return [str(p).strip() for p in places if p]
            return []

        except json.JSONDecodeError as e:
            if attempt < max_retries:
                continue
            log.warning("Extraction parse failed after %d attempts", max_retries + 1)
            return []
        except anthropic.RateLimitError:
            import time
            log.warning("Rate limit hit — sleeping 30s")
            time.sleep(30)
        except anthropic.APIError as e:
            log.error("Anthropic API error: %s", e)
            raise

    return []


def _extract_place_hints_from_symbols(symbols_json: str) -> list[str]:
    """
    Parse llm_extracted_symbols JSON array and surface any
    geographic-sounding symbols as hints to the LLM.
    e.g. ["tsunami", "volcano", "Japan"] → ["Japan"]
    """
    if not symbols_json:
        return []

    try:
        data = json.loads(symbols_json)
    except (json.JSONDecodeError, TypeError):
        return []

    # Handle flat array of strings (actual schema)
    if isinstance(data, list):
        geo_keywords = {
            "ocean", "sea", "river", "lake", "mountain", "volcano", "island",
            "coast", "beach", "desert", "forest", "jungle", "valley", "canyon",
        }
        hints = []
        for item in data:
            if isinstance(item, str):
                # Include if it looks like a proper noun (capitalized, not a geo keyword)
                words = item.strip().split()
                if words and words[0][0].isupper() and item.lower() not in geo_keywords:
                    hints.append(item)
        return hints

    # Handle object schema (future-proofing)
    if isinstance(data, dict):
        hints = []
        for field in ["locations", "location", "places", "place", "setting",
                      "geographic_context", "geography", "country", "city", "region"]:
            val = data.get(field)
            if val is None:
                continue
            if isinstance(val, list):
                hints.extend(str(v) for v in val if v)
            elif isinstance(val, str) and val.strip():
                hints.append(val.strip())
        return list(dict.fromkeys(hints))

    return []

def strip_reddit_title(narrative_text: str, source_name: str) -> str:
    """
    Reddit posts have their title prepended as the first line of narrative_text
    during archive import. Strip it before geocoding to avoid title-sourced
    false positives. Only applies to reddit:: sources.
    """
    if not source_name or not source_name.startswith('reddit::'):
        return narrative_text
    if not narrative_text:
        return narrative_text
    # Find first newline — everything before it is the title
    first_newline = narrative_text.find('\n')
    if first_newline == -1:
        # No newline means it's title-only, no body — return empty
        return ''
    return narrative_text[first_newline:].strip()
