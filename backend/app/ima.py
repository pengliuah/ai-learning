"""IMA (ima.qq.com) note API client.

Saves learning content as IMA notes via the OpenAPI ``import_doc`` endpoint.
Uses stdlib ``urllib`` to avoid adding an HTTP client dependency.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

IMA_BASE_URL = "https://ima.qq.com"
IMPORT_DOC_PATH = "/openapi/note/v1/import_doc"


def import_note(
    client_id: str,
    api_key: str,
    content: str,
    title: str = "",
    folder_name: str = "",
) -> dict:
    """Create a note in IMA from Markdown content.

    Returns ``{"note_id": str, "raw": <full response>}`` on success.
    Raises ``RuntimeError`` on network or API-level errors.
    """
    md = f"# {title}\n\n{content}" if title else content
    body = json.dumps(
        {
            "content_format": 1,  # MARKDOWN
            "content": md,
            "folder_name": folder_name or "",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        IMA_BASE_URL + IMPORT_DOC_PATH,
        data=body,
        headers={
            "ima-openapi-clientid": client_id,
            "ima-openapi-apikey": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        logger.error("ima import_note: request failed: %s", exc)
        raise RuntimeError(f"IMA API request failed: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"IMA API returned non-JSON: {raw[:200]}")

    # IMA wraps results: {"err_code": 0, "err_msg": "", "data": {"note_id": ...}}
    err_code = data.get("err_code", data.get("errcode", 0))
    if err_code:
        err_msg = data.get("err_msg", data.get("errmsg", "unknown"))
        logger.error("ima import_note: api error %s: %s", err_code, err_msg)
        raise RuntimeError(f"IMA API error {err_code}: {err_msg}")

    note_id = ""
    inner = data.get("data")
    if isinstance(inner, dict):
        note_id = inner.get("note_id", "")
    elif isinstance(inner, str):
        note_id = inner

    logger.info("ima import_note: ok note_id=%s", note_id)
    return {"note_id": note_id, "raw": data}