from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import DATA_DIR
from .schemas import Document, Module, Plan, PlanListItem, PlanSource

logger = logging.getLogger(__name__)

STORE_PATH: Path = DATA_DIR / "plans.json"
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_raw() -> dict:
    if not STORE_PATH.exists():
        return {}
    try:
        with STORE_PATH.open("r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return {}
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return {}


def _save_raw(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, STORE_PATH)


def list_documents() -> list[Document]:
    with _lock:
        data = _load_raw()
    docs = [Document.model_validate(v) for v in data.values()]
    logger.debug("list_documents: count=%d", len(docs))
    return docs


def list_items() -> list[PlanListItem]:
    items: list[PlanListItem] = []
    for doc in list_documents():
        total = len(doc.plan.modules)
        done = sum(1 for m in doc.plan.modules if m.status.value == "completed")
        progress = (done / total) if total else 0.0
        items.append(
            PlanListItem(
                id=doc.id,
                title=doc.plan.title,
                createdAt=doc.createdAt,
                progress=round(progress, 4),
            )
        )
    return items


def get_document(plan_id: str) -> Document | None:
    with _lock:
        data = _load_raw()
    raw = data.get(plan_id)
    logger.debug("get_document: plan_id=%s found=%s", plan_id, raw is not None)
    return Document.model_validate(raw) if raw else None


def save_document(doc: Document) -> Document:
    with _lock:
        data = _load_raw()
        data[doc.id] = doc.model_dump(mode="json")
        _save_raw(data)
    logger.debug("save_document: plan_id=%s", doc.id)
    return doc


def create_document(source: PlanSource, plan: Plan) -> Document:
    now = _now()
    doc = Document(
        id=str(uuid.uuid4()),
        createdAt=now,
        updatedAt=now,
        source=source,
        plan=plan,
    )
    logger.debug("create_document: plan_id=%s title=%s", doc.id, plan.title)
    return save_document(doc)


def delete_document(plan_id: str) -> bool:
    with _lock:
        data = _load_raw()
        if plan_id not in data:
            return False
        del data[plan_id]
        _save_raw(data)
    logger.debug("delete_document: plan_id=%s", plan_id)
    return True


def update_module(plan_id: str, module_id: str, mutate: Callable[[Module], None]) -> Document:
    logger.debug("update_module: plan_id=%s module_id=%s", plan_id, module_id)
    with _lock:
        data = _load_raw()
        raw = data.get(plan_id)
        if raw is None:
            raise KeyError(plan_id)
        doc = Document.model_validate(raw)
        module = next((m for m in doc.plan.modules if m.id == module_id), None)
        if module is None:
            raise KeyError(module_id)
        mutate(module)
        doc.updatedAt = _now()
        data[plan_id] = doc.model_dump(mode="json")
        _save_raw(data)
        return doc