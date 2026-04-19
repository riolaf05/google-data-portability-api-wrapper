"""
AWS Lambda: Google Data Portability API — export risorse Maps (liste salvate, luoghi preferiti).

L'API non espone endpoint per singola lista: si avvia un job di archivio per resource group
(es. saved.collections) e si scarica l'export (CSV in archivio) al completamento.
Documentazione: https://developers.google.com/data-portability/user-guide/methods
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any

# Endpoint REST
DATAPORTABILITY_BASE = "https://dataportability.googleapis.com/v1"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Resource group IDs (allineati agli scope dataportability.*)
# https://developers.google.com/data-portability/schema-reference/save
RESOURCE_SAVED_COLLECTIONS = "saved.collections"
# Maps starred / preferiti
RESOURCE_MAPS_STARRED = "maps.starred_places"


def _normalize_oauth_secret(raw: Any) -> dict[str, str]:
    """
    Accetta il formato atteso (client_id, client_secret, refresh_token) oppure
    varianti comuni: camelCase, JSON client Google (chiavi installed/web).
    """
    if not isinstance(raw, dict):
        raise RuntimeError("Il secret OAuth deve essere un oggetto JSON.")

    data = dict(raw)

    # JSON "Credenziali OAuth" da Google Cloud (client_secret_....json)
    for nest_key in ("installed", "web"):
        nested = data.get(nest_key)
        if isinstance(nested, dict) and "client_id" in nested:
            data.setdefault("client_id", nested.get("client_id"))
            data.setdefault("client_secret", nested.get("client_secret"))
            break

    aliases = {
        "client_id": ("clientId", "CLIENT_ID", "google_client_id"),
        "client_secret": ("clientSecret", "CLIENT_SECRET", "google_client_secret"),
        "refresh_token": ("refreshToken", "REFRESH_TOKEN", "google_refresh_token"),
    }
    out: dict[str, str] = {}
    for canon, alts in aliases.items():
        val = data.get(canon)
        if val is None:
            for a in alts:
                if a in data and data[a] is not None:
                    val = data[a]
                    break
        if val is None or str(val).strip() == "":
            if canon == "refresh_token":
                raise RuntimeError(
                    "Manca refresh_token nel JSON. Il file client_secret_*.json scaricato da Google Cloud "
                    "contiene solo client_id/client_secret (e installed/web): non include mai il refresh token. "
                    "Ottieni refresh_token con OAuth (es. OAuth Playground o script con redirect), poi aggiungi "
                    "in secret.json una riga \"refresh_token\": \"...\" accanto a client_id e client_secret. "
                    f"Chiavi attuali nel JSON: {sorted(data.keys())}."
                )
            raise RuntimeError(
                f"Secret OAuth incompleto: manca {canon}. "
                f"Chiavi presenti nel JSON: {sorted(data.keys())}. "
                "Servono client_id, client_secret e refresh_token (anche in camelCase o dentro installed/web)."
            )
        out[canon] = str(val).strip()
    return out


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, Any]:
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    elif raw_body is not None:
        data = raw_body
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = resp.getcode()
            text = resp.read().decode("utf-8")
            if not text:
                return status, None
            return status, json.loads(text)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body) if err_body else {"raw": err_body}
        except json.JSONDecodeError:
            parsed = {"raw": err_body}
        raise RuntimeError(f"HTTP {e.code} {method} {url}: {parsed}") from e


def _get_oauth_credentials() -> dict[str, str]:
    raw_json = os.environ.get("GOOGLE_OAUTH_JSON", "").strip()
    if raw_json:
        return _normalize_oauth_secret(json.loads(raw_json))
    # Fallback locale / test senza file unico
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        if not os.environ.get(key):
            raise RuntimeError(
                "Impostare GOOGLE_OAUTH_JSON (JSON con client_id, client_secret, refresh_token) "
                "oppure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN"
            )
    return _normalize_oauth_secret(
        {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
        }
    )


def _access_token(creds: dict[str, str]) -> str:
    form = urllib.parse.urlencode(
        {
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    status, data = _http_json(
        "POST",
        OAUTH_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        raw_body=form,
    )
    if status != 200 or not isinstance(data, dict) or "access_token" not in data:
        raise RuntimeError(f"Token response inattesa: {status} {data}")
    return str(data["access_token"])


def initiate_archive(access_token: str, resources: list[str]) -> str:
    url = f"{DATAPORTABILITY_BASE}/portabilityArchive:initiate"
    status, data = _http_json(
        "POST",
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        body={"resources": resources},
    )
    if status not in (200, 201) or not isinstance(data, dict):
        raise RuntimeError(f"initiate fallita: {status} {data}")
    job_id = data.get("archiveJobId")
    if not job_id:
        raise RuntimeError(f"Nessun archiveJobId nella risposta: {data}")
    return str(job_id)


def get_archive_state(access_token: str, job_id: str) -> dict[str, Any]:
    jid = urllib.parse.quote(str(job_id).strip(), safe="")
    url = f"{DATAPORTABILITY_BASE}/archiveJobs/{jid}/portabilityArchiveState"
    status, data = _http_json(
        "GET",
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError(f"getPortabilityArchiveState fallita: {status} {data}")
    return data


def _download_url(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def _parse_csv_content(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _extract_from_blob(blob: bytes) -> list[dict[str, Any]]:
    """Se ZIP, estrae CSV; altrimenti prova come CSV."""
    out: list[dict[str, Any]] = []
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".csv"):
                    with zf.open(name) as f:
                        rows = _parse_csv_content(f.read())
                        out.append({"file": name, "rows": rows, "row_count": len(rows)})
    else:
        rows = _parse_csv_content(blob)
        out.append({"file": "(inline)", "rows": rows, "row_count": len(rows)})
    return out


def poll_until_complete(
    access_token: str,
    job_id: str,
    *,
    interval_sec: float,
    max_wait_sec: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max_wait_sec
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = get_archive_state(access_token, job_id)
        state = str(last.get("state", ""))
        if state == "COMPLETE":
            return last
        if state == "FAILED":
            raise RuntimeError(f"Job fallito: {last}")
        if state == "CANCELLED":
            raise RuntimeError(f"Job annullato: {last}")
        time.sleep(interval_sec)
    raise TimeoutError(
        f"Timeout dopo {max_wait_sec}s; ultimo stato: {last}. "
        "Ripeti l'invocazione con action=poll e lo stesso job_id."
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Evento esempio:
      { "action": "export", "resources": ["saved.collections"] }
      { "action": "initiate", "resources": ["saved.collections"] }
      { "action": "poll", "job_id": "..." }
      { "action": "download", "job_id": "..." }  # stato COMPLETE
    """
    if isinstance(event, str):
        event = json.loads(event)

    action = (event.get("action") or "export").lower()
    resources = event.get("resources") or [RESOURCE_SAVED_COLLECTIONS]
    if isinstance(resources, str):
        resources = [resources]

    poll_interval = float(os.environ.get("POLL_INTERVAL_SEC", "30"))
    max_wait = float(os.environ.get("MAX_POLL_SECONDS", "840"))

    creds = _get_oauth_credentials()
    token = _access_token(creds)

    if action == "initiate":
        job_id = initiate_archive(token, resources)
        return {
            "ok": True,
            "archiveJobId": job_id,
            "resources": resources,
            "hint": "Usa action=poll con questo job_id (o export per flusso completo).",
        }

    if action == "export":
        jid = initiate_archive(token, resources)
        final = poll_until_complete(
            token, jid, interval_sec=poll_interval, max_wait_sec=max_wait
        )
        urls = final.get("urls") or []
        downloads: list[dict[str, Any]] = []
        for u in urls:
            blob = _download_url(u)
            downloads.append(
                {
                    "extracted": _extract_from_blob(blob),
                }
            )
        return {
            "ok": True,
            "archiveJobId": jid,
            "resources": resources,
            "finalState": final,
            "downloads": downloads,
        }

    job_id = event.get("job_id") or event.get("archiveJobId")
    if not job_id:
        raise ValueError(
            "job_id richiesto per poll e download. Per export usa action=export senza job_id."
        )

    if action == "poll":
        state = get_archive_state(token, str(job_id))
        return {"ok": True, "state": state}

    if action == "download":
        state = get_archive_state(token, str(job_id))
        st = str(state.get("state", ""))
        if st != "COMPLETE":
            return {"ok": False, "message": "Job non ancora COMPLETE", "state": state}
        urls = state.get("urls") or []
        files_out: list[dict[str, Any]] = []
        for u in urls:
            blob = _download_url(u)
            files_out.append(
                {
                    "url_prefix": u[:80] + "...",
                    "extracted": _extract_from_blob(blob),
                }
            )
        return {"ok": True, "state": state, "downloads": files_out}

    raise ValueError(
        f"action sconosciuta: {action}. Usa export | initiate | poll | download"
    )
