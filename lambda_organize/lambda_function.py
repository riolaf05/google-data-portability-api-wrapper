"""
Seconda Lambda: organizza output Data Portability (takeout) e calcola distanze da un indirizzo.

Input event (Step Functions o invocazione diretta):
{
  "takeout": { ... output prima Lambda (downloads / ok / ...) ... },
  "origin_address": "Via Apuania 16, Roma",   // opzionale se ORIGIN_ADDRESS in env
  "city_filter": "roma"                        // opzionale; default env CITY_FILTER o "roma"
}
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from geopy.distance import geodesic
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

logger = logging.getLogger()
logger.setLevel(logging.INFO)

USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "gmaps-dataportability-organize/1.0")
NOMINATIM_RATE_LIMIT_SEC = 1.1
NOMINATIM_TIMEOUT_SEC = 10
MAX_RETRIES = 3

ROME_PREFIXES = ("0x132f6", "0x132f7", "0x132f3")
HINTERLAND_PREFIXES = ("0x13258", "0x1325f", "0x1325e")
EXCLUDE_PREFIXES = ("0x132f01", "0x4786", "0x477", "0x478")

FID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)")

geolocator = Nominatim(user_agent=USER_AGENT, timeout=NOMINATIM_TIMEOUT_SEC)


def extract_fid(url: str) -> str | None:
    if not url:
        return None
    m = FID_RE.search(url)
    return m.group(1).lower() if m else None


def classify_fid(fid: str | None) -> str | None:
    if not fid:
        return None
    if any(fid.startswith(p) for p in EXCLUDE_PREFIXES):
        return None
    if any(fid.startswith(p) for p in ROME_PREFIXES):
        return "Roma"
    if any(fid.startswith(p) for p in HINTERLAND_PREFIXES):
        return "Castelli/Hinterland"
    return None


def categorize(collections: set[str], title: str, note: str) -> str:
    cols = {c.lower() for c in collections}
    combined = f"{title} {note or ''}".lower()

    def has(words: list[str]) -> bool:
        return any(w in combined for w in words)

    if has(["pizza", "pizzeria", "pinseria"]):
        return "Pizzeria"
    if has(["gelat", "cremeria"]):
        return "Gelateria"
    if has(["sushi", "ramen", "giappon", "ayce"]):
        return "Giapponese/Asiatico"
    if has(["pasticceria", "dolci", "maritozz", "cornett", "tiramisù", "supplì"]):
        return "Pasticceria/Street food"
    if has([" pub", "pub ", "birr", "brewing", "fermento", "craft beer"]):
        return "Pub/Birreria"
    if has(["agritur", "fattoria", "cascina"]):
        return "Agriturismo/Fattoria"
    if has(["libreria", "libri", "fumett"]):
        return "Libreria/Fumetti"
    if has(["mercato"]):
        return "Mercato"
    if has(
        [
            "trattoria",
            "osteria",
            "hosteria",
            "taverna",
            "fraschetta",
            "locanda",
            "bistrot",
            "bistro",
        ]
    ):
        return "Trattoria/Osteria"
    if has(["cocktail", "aperitivo", "cantina"]):
        return "Aperitivi/Cocktail"
    if has(["caffè", "caffe ", "caffetteria", "colazione", "brunch"]):
        return "Bar/Caffè/Colazione"
    if has(["ristorante", "cucina"]):
        return "Ristorante"
    if has(["zoo", "bioparco", "parco", "piazza", "villa ", "galleria"]):
        return "Luogo/Attrazione"

    if "pizzeria" in cols:
        return "Pizzeria"
    if "want to go" in cols:
        return "Da visitare"
    if "domenicale" in cols:
        return "Pranzo domenicale"
    if "coppia" in cols:
        return "Coppia"
    if "aperitivi" in cols:
        return "Aperitivi/Cocktail"
    if "ristorante" in cols:
        return "Ristorante"
    if "bar" in cols:
        return "Bar/Caffè/Colazione"
    return "Altro"


def _row_get(row: dict[str, Any], key: str) -> str:
    val = row.get(key)
    if isinstance(val, list):
        return val[0] if val else ""
    return val or ""


def _first_nonempty(row: dict[str, Any], candidate_keys: list[str]) -> str:
    for k in candidate_keys:
        v = _row_get(row, k)
        if v:
            return str(v).strip()
    for v in row.values():
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def collect_places(takeout: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Percorre takeout.downloads[].extracted[].rows (output prima Lambda / Data Portability)."""
    places: dict[tuple[str, str], dict[str, Any]] = {}

    downloads = takeout.get("downloads", [])
    for dl in downloads:
        for extracted in dl.get("extracted", []):
            file_name = extracted.get("file", "")
            collection_name = os.path.basename(file_name).removesuffix(".csv") or "unknown"
            collection_name = re.sub(r"\(\d+\)$", "", collection_name).strip()

            for row in extracted.get("rows", []):
                title = _first_nonempty(
                    row,
                    [
                        "Title",
                        "title",
                        "Locali da visitare",
                        "Name",
                    ],
                )
                note = _first_nonempty(row, ["Note", "note", "Comment", "comment"])
                url = _first_nonempty(
                    row,
                    [
                        "URL",
                        "url",
                        "item_content_url",
                        "Item_content_url",
                        "Link",
                        "link",
                    ],
                )

                if not title or not url:
                    continue

                fid = extract_fid(url)
                area = classify_fid(fid)
                if area is None:
                    continue

                key = (title.strip(), fid)
                if key not in places:
                    places[key] = {
                        "title": title.strip(),
                        "note": (note or "").strip(),
                        "fid": fid,
                        "url": url.strip(),
                        "area": area,
                        "collections": set(),
                    }
                else:
                    existing_note = places[key]["note"]
                    new_note = (note or "").strip()
                    if new_note and new_note != existing_note:
                        places[key]["note"] = (
                            f"{existing_note}; {new_note}" if existing_note else new_note
                        )
                places[key]["collections"].add(collection_name)

    return places


def _parse_manual_origin_lat_lon() -> tuple[float, float] | None:
    """Coordinate fisse da env (consigliato su Lambda: Nominatim spesso non risponde da IP AWS)."""
    la = os.environ.get("ORIGIN_LAT", "").strip()
    lo = os.environ.get("ORIGIN_LON", "").strip()
    if not la or not lo:
        return None
    try:
        return float(la.replace(",", ".")), float(lo.replace(",", "."))
    except ValueError:
        logger.warning("ORIGIN_LAT/ORIGIN_LON non numerici, ignoro")
        return None


def geocode_origin_address(address: str) -> tuple[float, float, str] | None:
    """Prova più formulazioni; Nominatim da datacenter può fallire comunque."""
    queries = [
        address,
        f"{address}, Italia",
        f"{address}, Italy",
    ]
    for q in queries:
        result = geocode_with_retry(q)
        time.sleep(NOMINATIM_RATE_LIMIT_SEC)
        if result:
            return result
    return None


def geocode_with_retry(query: str) -> tuple[float, float, str] | None:
    for attempt in range(MAX_RETRIES):
        try:
            result = geolocator.geocode(query, exactly_one=True, addressdetails=False)
            if result:
                return result.latitude, result.longitude, result.address
            return None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            wait = 2**attempt
            logger.warning(
                'Geocoding fallito per "%s" (tentativo %s): %s. Retry in %ss',
                query,
                attempt + 1,
                e,
                wait,
            )
            time.sleep(float(wait))
    logger.error('Geocoding abbandonato per "%s" dopo %s tentativi', query, MAX_RETRIES)
    return None


def geocode_place(place: dict[str, Any], city_hint: str) -> tuple[float, float, str] | None:
    city = city_hint.strip() or "Roma"
    queries = [f'{place["title"]}, {city}, Italia', place["title"]]
    for q in queries:
        result = geocode_with_retry(q)
        time.sleep(NOMINATIM_RATE_LIMIT_SEC)
        if result:
            return result
    return None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    logger.info("Event keys: %s", list(event.keys()))

    takeout = event.get("takeout")
    if not takeout:
        raise ValueError('event["takeout"] mancante')

    default_addr = os.environ.get("ORIGIN_ADDRESS", "Via Apuania 16, Roma")
    origin_address = (event.get("origin_address") or "").strip() or default_addr

    city_filter = (event.get("city_filter") or "").strip() or os.environ.get(
        "CITY_FILTER", "roma"
    )

    manual = _parse_manual_origin_lat_lon()
    if manual:
        origin_lat, origin_lon = manual
        origin_display = f"{origin_address} (coordinate da ORIGIN_LAT/ORIGIN_LON)"
        logger.info("Origine da env: lat=%s lon=%s", origin_lat, origin_lon)
    else:
        logger.info("Geocoding origine (Nominatim): %s", origin_address)
        origin_result = geocode_origin_address(origin_address)
        if not origin_result:
            raise RuntimeError(
                f"Impossibile geocodificare l'origine: {origin_address}. "
                "Nominatim spesso non risponde o blocca le richieste dagli IP AWS. "
                "Imposta in Terraform le variabili organize_origin_lat e organize_origin_lon "
                "(es. coordinate da Google Maps) e applica di nuovo."
            )
        origin_lat, origin_lon, origin_display = origin_result
    origin_coords = (origin_lat, origin_lon)

    places_dict = collect_places(takeout)
    logger.info("Luoghi estratti (Roma + hinterland): %s", len(places_dict))

    output: list[dict[str, Any]] = []
    for i, place in enumerate(places_dict.values(), 1):
        logger.info("[%s/%s] %s", i, len(places_dict), place["title"])

        geo = geocode_place(place, city_filter)
        if geo:
            lat, lon, address = geo
            distance_km = round(geodesic(origin_coords, (lat, lon)).kilometers, 2)
        else:
            address = None
            distance_km = None

        output.append(
            {
                "categoria": categorize(place["collections"], place["title"], place["note"]),
                "nome": place["title"],
                "note": place["note"] or None,
                "area": place["area"],
                "indirizzo": address,
                "distanza_km": distance_km,
                "collections": sorted(place["collections"]),
                "link": place["url"],
            }
        )

    output.sort(key=lambda r: (r["distanza_km"] is None, r["distanza_km"] or 0))

    return {
        "origin": {
            "address": origin_address,
            "lat": origin_lat,
            "lon": origin_lon,
        },
        "count": len(output),
        "places": output,
        "meta": {
            "city_filter": city_filter,
            "origin_resolved_label": origin_display,
        },
    }
