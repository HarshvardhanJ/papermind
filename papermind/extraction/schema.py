"""
schema.py

The extraction schema has two parts:

  - Fixed fields: present for every paper, regardless of research
    domain. These map directly to columns on the Paper model.

  - `dynamic_metadata`: domain-specific fields the LLM finds in this
    particular paper. A sensor paper yields {"analyte": "acetone",
    "response_time_seconds": 7.2}; an ML paper yields {"benchmark":
    "ImageNet", "top1_accuracy": 84.2}. This is what gets stored in
    the Paper.extra_metadata JSON column, and is why that column has
    no fixed schema of its own -- the shape is decided per paper, at
    extraction time, by what the paper actually reports.
"""

from pydantic import BaseModel, Field


class PaperExtraction(BaseModel):
    title: str = Field(description="The paper's title, exactly as written")
    authors: list[str] = Field(default_factory=list, description="Author names")
    year: int | None = Field(default=None, description="Publication year, if stated")

    key_claim: str = Field(description="The central argument or finding, in one or two sentences")
    main_result: str = Field(description="The primary quantitative or qualitative outcome reported")
    limitations: str | None = Field(default=None, description="Limitations the authors themselves acknowledge, if any")

    dynamic_metadata: dict = Field(
        default_factory=dict,
        description=(
            "Domain-specific quantitative or categorical facts found in this paper: "
            "material names, measured values with units, datasets, benchmarks, "
            "operating conditions -- whatever this specific paper reports that a "
            "researcher in this field would want to filter or compare on."
        ),
    )
