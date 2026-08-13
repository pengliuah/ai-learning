"""One-time migration: plans.json -> PostgreSQL.

Reads every document from backend/data/plans.json and inserts it into the
database via the normal store layer (save_document).  Run after setting
DATABASE_URL and applying the schema:

    cd backend
    uv run python scripts/migrate_json_to_pg.py

Idempotent: if a plan id already exists in the DB it is replaced (upsert).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the backend package is importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import init_schema          # noqa: E402
from app.schemas import Document        # noqa: E402
from app.store import save_document     # noqa: E402

PLANS_JSON = Path(__file__).resolve().parent.parent / "data" / "plans.json"


def main() -> None:
    if not PLANS_JSON.exists():
        print(f"No plans.json at {PLANS_JSON} - nothing to migrate.")
        return

    init_schema()

    raw = json.loads(PLANS_JSON.read_text(encoding="utf-8"))
    if not raw:
        print("plans.json is empty - nothing to migrate.")
        return

    count = 0
    for plan_id, doc_dict in raw.items():
        doc = Document.model_validate(doc_dict)
        save_document(doc)
        count += 1
        print(f"  migrated {plan_id} ({doc.plan.title})")

    print(f"\nDone: {count} plan(s) migrated to PostgreSQL.")


if __name__ == "__main__":
    main()
