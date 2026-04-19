#!/usr/bin/env python3
"""
Ottiene (o rinnova) il refresh token OAuth Google e lo scrive in secret.json.

Prerequisiti in Google Cloud Console (client OAuth di tipo Desktop o Web):
  - Se usi questo script così com'è, aggiungi tra gli URI di reindirizzamento autorizzati:
      http://127.0.0.1:8090/
    (Applicazione desktop → URI di reindirizzamento, oppure Web con lo stesso URI se consentito.)

Uso (dalla root del repo):
  python scripts/get_refresh_token.py
  python scripts/get_refresh_token.py --secret path/al/secret.json

Solo librerie standard (nessuna pip install).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Deve coincidere con un URI registrato sul client OAuth
REDIRECT_URI = "http://127.0.0.1:8090/"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8090

# Scope Data Portability (liste salvate + preferiti Maps)
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/dataportability.saved.collections",
    "https://www.googleapis.com/auth/dataportability.maps.starred_places",
]


def _load_secret(path: Path) -> dict:
    if not path.is_file():
        print(f"File non trovato: {path}", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _extract_client_creds(data: dict) -> tuple[str, str]:
    """Stessa logica concettuale del Lambda: supporto a installed/web."""
    cid = data.get("client_id")
    sec = data.get("client_secret")
    for key in ("installed", "web"):
        nested = data.get(key)
        if isinstance(nested, dict):
            if not cid:
                cid = nested.get("client_id")
            if not sec:
                sec = nested.get("client_secret")
    if not cid or not sec:
        raise SystemExit(
            "secret.json deve contenere client_id e client_secret "
            "(in chiaro o dentro installed/web)."
        )
    return str(cid).strip(), str(sec).strip()


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    body = urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Scambio code fallito HTTP {e.code}: {err}") from e


def main() -> None:
    parser = argparse.ArgumentParser(description="OAuth Google → refresh_token in secret.json")
    parser.add_argument(
        "--secret",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "secret.json",
        help="Percorso a secret.json (default: ../secret.json dalla root repo)",
    )
    args = parser.parse_args()
    secret_path: Path = args.secret

    raw = _load_secret(secret_path)
    client_id, client_secret = _extract_client_creds(raw)

    scopes = " ".join(DEFAULT_SCOPES)
    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_full = f"{AUTH_URL}?{urlencode(auth_params)}"

    state: dict[str, str] = {}
    event = threading.Event()

    class OAuthHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args_: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path not in ("", "/"):
                self.send_error(404)
                return
            qs = parse_qs(parsed.query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if "code" in qs:
                state["code"] = qs["code"][0]
                self.wfile.write(
                    "<!DOCTYPE html><meta charset=utf-8><title>OK</title>"
                    "<p>Autorizzazione ricevuta. Puoi chiudere questa finestra e tornare al terminale.</p>"
                    .encode("utf-8")
                )
                event.set()
            elif "error" in qs:
                err = qs.get("error", ["unknown"])[0]
                desc = qs.get("error_description", [""])[0]
                state["error"] = f"{err}: {desc}"
                self.wfile.write(
                    f"<!DOCTYPE html><meta charset=utf-8><title>Errore</title><p>{err}: {desc}</p>".encode(
                        "utf-8"
                    )
                )
                event.set()
            else:
                self.wfile.write(
                    b"<!DOCTYPE html><p>Attendere il redirect da Google...</p>"
                )

    httpd = HTTPServer((LISTEN_HOST, LISTEN_PORT), OAuthHandler)

    def serve() -> None:
        httpd.serve_forever()

    th = threading.Thread(target=serve, daemon=True)
    th.start()

    print("Apri il browser per autorizzare l'app (o usa l'URL sotto se non si apre da solo).\n")
    print(auth_full, "\n")
    webbrowser.open(auth_full)

    if not event.wait(timeout=600):
        print("Timeout 10 minuti senza ricevere il redirect.", file=sys.stderr)
        sys.exit(1)

    if "error" in state:
        print(state["error"], file=sys.stderr)
        sys.exit(1)
    if "code" not in state:
        print("Nessun authorization code ricevuto.", file=sys.stderr)
        sys.exit(1)

    httpd.shutdown()
    httpd.server_close()

    token_payload = _exchange_code(state["code"], client_id, client_secret)
    refresh = token_payload.get("refresh_token")
    if not refresh:
        print(
            "Risposta token senza refresh_token. Prova a revocare l'accesso dell'app in "
            "https://myaccount.google.com/permissions e rilancia lo script, oppure verifica "
            "che il client sia corretto e access_type=offline sia applicato.",
            file=sys.stderr,
        )
        print("Risposta:", json.dumps(token_payload, indent=2), file=sys.stderr)
        sys.exit(1)

    raw["client_id"] = client_id
    raw["client_secret"] = client_secret
    raw["refresh_token"] = refresh

    with secret_path.open("w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Aggiornato {secret_path.resolve()} con refresh_token.")
    print("Esegui terraform apply (cartella terraform/) per propagare il JSON alla Lambda.")


if __name__ == "__main__":
    main()
