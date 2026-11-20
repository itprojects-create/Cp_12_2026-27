"""Export the frozen v1 contract: openapi.json (endpoints) + schemas.json (all agent Pydantic models)."""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.main import app
import app.schemas as S

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract")

def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "openapi.json"), "w", encoding="utf-8") as f:
        json.dump(app.openapi(), f, indent=2)
    from pydantic import BaseModel as _BM
    models = {n: c for n, c in vars(S).items()
              if isinstance(c, type) and issubclass(c, _BM) and c is not _BM}
    defs: dict = {}
    for name, cls in sorted(models.items()):
        defs[name] = cls.model_json_schema(ref_template="#/components/schemas/{model}")
    with open(os.path.join(OUT, "schemas.json"), "w", encoding="utf-8") as f:
        json.dump(defs, f, indent=2)
    print(f"exported {len(defs)} schemas + openapi to {OUT}/")

if __name__ == "__main__":
    main()
