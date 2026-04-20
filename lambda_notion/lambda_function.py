"""
Terza Lambda: riceve l'output della Lambda organize (origin, count, places, meta) e appende blocchi a una pagina Notion.
Env: NOTION_INTEGRATION_TOKEN (Bearer), NOTION_PAGE_ID (UUID o stringa con suffisso UUID).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NOTION_VERSION = "2022-06-28"
MAX_BLOCKS_PER_REQUEST = 100
MAX_TEXT = 1900
# Notion: ~3 richieste/sec; tra batch append restiamo sotto la soglia
BATCH_SLEEP_SEC = 0.35

_HEX32 = re.compile(r"[0-9a-fA-F]{32}")


def _normalize_page_id(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    m = _HEX32.search(s)
    if not m:
        return s
    h = m.group(0).lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _trunc(s: str, n: int = MAX_TEXT) -> str:
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _rich_text_plain(content: str) -> dict[str, Any]:
    return {
        "type": "text",
        "text": {"content": _trunc(content), "link": None},
    }


def _rich_text_link(label: str, url: str) -> dict[str, Any]:
    return {
        "type": "text",
        "text": {"content": _trunc(label), "link": {"url": url}},
    }


def _paragraph_block(rich_text: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text},
    }


def _divider_block() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def _bullet_block_for_place(p: dict[str, Any]) -> dict[str, Any]:
    nome = (p.get("nome") or "").strip() or "(senza nome)"
    link = (p.get("link") or "").strip()
    categoria = p.get("categoria")
    area = p.get("area")
    dist = p.get("distanza_km")
    ind = p.get("indirizzo")
    cols = p.get("collections") or []
    note = (p.get("note") or "").strip()

    parts: list[str] = []
    if categoria:
        parts.append(str(categoria))
    if area:
        parts.append(str(area))
    if dist is not None:
        parts.append(f"{dist} km")
    if ind:
        parts.append(str(ind))
    tail = " · ".join(parts)

    rich: list[dict[str, Any]] = []
    if link:
        rich.append(_rich_text_link(nome, link))
    else:
        rich.append(_rich_text_plain(nome))
    if tail:
        rich.append(_rich_text_plain(f" — {tail}"))
    if isinstance(cols, list) and cols:
        rich.append(_rich_text_plain(f" [{', '.join(str(c) for c in cols)}]"))
    if note and note.lower() != nome.lower():
        rich.append(_rich_text_plain(f" — {note}"))

    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich},
    }


def _notion_append_children(token: str, block_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    body = json.dumps({"children": children}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    token = os.environ.get("NOTION_INTEGRATION_TOKEN", "").strip()
    page_raw = os.environ.get("NOTION_PAGE_ID", "").strip()
    page_id = _normalize_page_id(page_raw)

    if not token:
        raise RuntimeError("NOTION_INTEGRATION_TOKEN mancante (variabile ambiente).")
    if not page_id:
        raise RuntimeError("NOTION_PAGE_ID mancante o non valido.")

    places = event.get("places")
    if not isinstance(places, list):
        raise ValueError('Input atteso: JSON organize con campo "places" (lista).')

    count = event.get("count")
    origin = event.get("origin")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header_line = f"Import Maps — {len(places)} luoghi"
    if isinstance(count, int):
        header_line = f"Import Maps — {len(places)} luoghi (count={count})"
    if isinstance(origin, dict) and origin.get("address"):
        header_line += f" — origine: {origin['address']}"
    header_line += f" — {now}"

    blocks: list[dict[str, Any]] = [
        _paragraph_block([_rich_text_plain(header_line)]),
        _divider_block(),
    ]
    for p in places:
        if isinstance(p, dict):
            blocks.append(_bullet_block_for_place(p))

    total_appended = 0
    batches = 0
    for i in range(0, len(blocks), MAX_BLOCKS_PER_REQUEST):
        chunk = blocks[i : i + MAX_BLOCKS_PER_REQUEST]
        batches += 1
        try:
            _notion_append_children(token, page_id, chunk)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.exception("Notion HTTP %s: %s", e.code, err_body)
            raise RuntimeError(f"Notion API {e.code}: {err_body[:2000]}") from e
        except urllib.error.URLError as e:
            logger.exception("Notion network error")
            raise RuntimeError(str(e.reason or e)) from e

        total_appended += len(chunk)
        if i + MAX_BLOCKS_PER_REQUEST < len(blocks):
            time.sleep(BATCH_SLEEP_SEC)

    return {
        "ok": True,
        "page_id": page_id,
        "blocks_appended": total_appended,
        "batches": batches,
        "places_written": len(places),
    }
