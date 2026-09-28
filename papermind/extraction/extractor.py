"""
extractor.py

Calls an LLM to extract structured metadata from a paper's full text,
validates the response against PaperExtraction, and retries once with
a stricter prompt if the first attempt fails validation.

Uses Groq (OpenAI-compatible structured output via response_format)
because its free tier is generous enough for development without
needing a paid key. Swapping to another provider means changing
_call_llm only -- everything else (validation, retry, the calling
code in the ingestion pipeline) is provider-agnostic.
"""

import json
import os

from pydantic import ValidationError

from papermind.extraction.schema import PaperExtraction

SYSTEM_PROMPT_PATH = "prompts/extraction.md"

DEFAULT_SYSTEM_PROMPT = """You are analyzing a scientific paper for a research database.

Extract the fields defined by the schema. For `dynamic_metadata`, find
whatever domain-specific quantitative or categorical facts this paper
reports (measured values with units, materials, methods, datasets,
benchmarks) -- these vary by field, so include exactly what this paper
actually states, not a fixed list. Use null / omit a field rather than
guessing when the paper does not state it.

Return only valid JSON matching the schema. No prose before or after."""


def _load_system_prompt() -> str:
    if os.path.exists(SYSTEM_PROMPT_PATH):
        return open(SYSTEM_PROMPT_PATH).read()
    return DEFAULT_SYSTEM_PROMPT


def _call_llm(paper_text: str, strict: bool = False) -> str:
    """
    Returns raw JSON text from the LLM. Truncates paper_text to a safe
    length for the model's context window -- for a full production
    version this would be replaced by feeding section summaries rather
    than raw truncation, but that is out of scope for a first pass.
    """
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not set. Extraction requires an LLM API key -- "
            "see .env.example. Get a free key at console.groq.com."
        )

    client = Groq(api_key=api_key)
    system_prompt = _load_system_prompt()
    if strict:
        system_prompt += (
            "\n\nIMPORTANT: Your previous response was not valid JSON matching "
            "the required schema. Return ONLY a single valid JSON object. "
            "No markdown code fences, no explanation."
        )

    schema_json = json.dumps(PaperExtraction.model_json_schema(), indent=2)

    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "openai/gpt-oss-120b"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Schema:\n{schema_json}\n\nPaper text:\n{paper_text[:12000]}"},
        ],
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def extract_metadata(paper_text: str, max_retries: int = 1) -> tuple[PaperExtraction | None, str | None]:
    """
    Returns (extraction, error_message).
    On success: (PaperExtraction instance, None)
    On failure after retries: (None, error description)
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            raw = _call_llm(paper_text, strict=(attempt > 0))
            data = json.loads(raw)
            extraction = PaperExtraction.model_validate(data)
            return extraction, None
        except json.JSONDecodeError as e:
            last_error = f"LLM did not return valid JSON: {e}"
        except ValidationError as e:
            last_error = f"LLM output did not match schema: {e}"
        except Exception as e:
            last_error = f"Extraction call failed: {e}"

    return None, last_error


if __name__ == "__main__":
    import sys
    from papermind.ingestion.parser import parse_pdf_cached

    if len(sys.argv) < 2:
        print("Usage: python extractor.py <path_to_pdf>")
        sys.exit(1)

    full_text = parse_pdf_cached(sys.argv[1])

    extraction, error = extract_metadata(full_text)
    if error:
        print(f"FAILED: {error}")
    else:
        print(extraction.model_dump_json(indent=2))
