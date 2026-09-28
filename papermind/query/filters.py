"""
query_filters.py

Uses an LLM to extract structured filters from a user question,
which are then applied as SQL WHERE clauses before semantic search.
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, Field

SYSTEM_PROMPT = """You are extracting structured filters from a user's question about scientific papers.

The available filter fields (from the paper metadata) are:
- title (string, fuzzy match)
- authors (array of strings, any author name)
- year (integer)
- key_claim (string, semantic)
- main_result (string, semantic)
- extra_metadata (JSON object with domain-specific keys. Common keys from papers include:
  * Transformer papers: d_model, num_layers, num_heads, d_ff, bleu_wmt14_en_de, bleu_wmt14_en_fr, training_time_days, training_gpus, gpu_type, dropout_rate, label_smoothing
  * Upskilling papers: percent_workers_need_reskilling_by_2030, learners_passed_nvidia_certified_professional_exam, risk_item_dataset_size, etc.
  Use the EXACT key names as they appear in the paper's extracted metadata.)

Return ONLY valid JSON with this schema:
{
  "title_contains": "string or null",
  "author_name": "string or null",
  "year": "integer or null",
  "year_min": "integer or null",
  "year_max": "integer or null",
  "extra_metadata_filters": {
    "field_name": "value or null",
    ...
  }
}

Include only fields where the question explicitly mentions a constraint.
For extra_metadata, include only fields that are clearly referenced in the question.
Use null for unspecified fields. No prose, no markdown."""


class QueryFilters(BaseModel):
    title_contains: Optional[str] = None
    author_name: Optional[str] = None
    year: Optional[int] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    extra_metadata_filters: dict = Field(default_factory=dict)


def extract_query_filters(question: str) -> QueryFilters:
    """
    Calls Groq to extract structured filters from the question.
    Returns QueryFilters with any extracted constraints.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        # No API key - return empty filters (no filtering)
        return QueryFilters()

    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL", "openai/gpt-oss-120b"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Question: {question}"},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)
        return QueryFilters(**data)

    except Exception:
        # Any error - return empty filters gracefully
        return QueryFilters()


def apply_filters_to_query(session, filters: QueryFilters):
    """
    Applies the extracted filters as a SQLAlchemy query.
    Works with both SQLite (JSON1 extension) and PostgreSQL (JSONB).
    Returns a list of paper IDs that match.
    """
    from papermind.storage.models import Paper
    from sqlalchemy import or_, and_, cast, String, func

    query = session.query(Paper.id)

    conditions = []

    if filters.title_contains:
        conditions.append(Paper.title.ilike(f"%{filters.title_contains}%"))

    if filters.author_name:
        # Search in JSON array of authors - works for both SQLite and Postgres
        # For SQLite: LIKE on the JSON string (stored as Python list repr)
        # For Postgres: use @> operator
        conditions.append(
            Paper.authors.like(f'%{filters.author_name}%')
        )

    if filters.year is not None:
        conditions.append(Paper.year == filters.year)
    else:
        if filters.year_min is not None:
            conditions.append(Paper.year >= filters.year_min)
        if filters.year_max is not None:
            conditions.append(Paper.year <= filters.year_max)

    if filters.extra_metadata_filters:
        for key, value in filters.extra_metadata_filters.items():
            if value is not None:
                # JSON path query - use json_extract for SQLite compatibility
                # json_extract returns numeric for numbers, so compare appropriately
                if isinstance(value, (int, float)):
                    conditions.append(
                        func.json_extract(Paper.extra_metadata, f'$.{key}') == value
                    )
                else:
                    conditions.append(
                        func.json_extract(Paper.extra_metadata, f'$.{key}') == str(value)
                    )

    if conditions:
        query = query.filter(and_(*conditions))

    return [row[0] for row in query.all()]