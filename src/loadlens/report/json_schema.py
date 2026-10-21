"""JSON schema of the verdict that `loadlens verdict --json` writes (schemas/verdict.schema.json).

The schema is generated from the model, never written by hand; a test checks that the committed
file is the generated one. Regenerate it with:

    loadlens schema schemas/verdict.schema.json
"""

import json
from typing import Any

from loadlens.verdict import Verdict

DIALECT = "https://json-schema.org/draft/2020-12/schema"


def verdict_json_schema() -> dict[str, Any]:
    # Serialization mode: the schema describes what is written, which is what a reader gets.
    schema = Verdict.model_json_schema(mode="serialization")
    return {"$schema": DIALECT, **schema}


def verdict_json_schema_text() -> str:
    return json.dumps(verdict_json_schema(), indent=2, ensure_ascii=False) + "\n"
