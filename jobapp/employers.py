"""Find the restaurants, grocery stores and shops near her, from OpenStreetMap.

Job boards only show employers that post there. Plenty of local hiring never
reaches them: Publix only takes applications on its own site, many franchise
restaurants use their own hiring pages, and small local places put a sign in
the window. This lists the actual businesses within her radius so she can
check each one's jobs directly.

Uses two free public services, no key needed:
  * Nominatim   - turns a ZIP code or city into map coordinates
  * Overpass    - finds businesses within a radius of those coordinates
Both ask for a descriptive User-Agent and light use, which one search is.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote_plus

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "JobHelper/1.0 (personal job-search tool)"
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "geocode_cache.json"
TIMEOUT = 60

# OpenStreetMap tag value -> the app's industry name
CATEGORIES = {
    "amenity": {
        "fast_food": "Fast food / Restaurant", "restaurant": "Fast food / Restaurant",
        "cafe": "Fast food / Restaurant", "ice_cream": "Fast food / Restaurant",
        "fuel": "Grocery", "pharmacy": "Retail",
    },
    "shop": {
        "supermarket": "Grocery", "convenience": "Grocery", "bakery": "Grocery", "butcher": "Grocery",
        "deli": "Grocery", "greengrocer": "Grocery", "wholesale": "Grocery",
        "department_store": "Retail", "variety_store": "Retail", "general": "Retail", "discount": "Retail",
        "clothes": "Retail", "shoes": "Retail", "hardware": "Retail", "doityourself": "Retail",
        "chemist": "Retail", "pet": "Retail", "furniture": "Retail", "electronics": "Retail",
        "sports": "Retail", "craft": "Retail", "books": "Retail", "gift": "Retail", "beauty": "Retail",
        "car_parts": "Retail", "garden_centre": "Retail", "mobile_phone": "Retail", "toys": "Retail",
        "second_hand": "Retail", "charity": "Retail", "mall": "Retail",
    },
}


@dataclass
class Employer:
    name: str
    category: str
    locations: int
    address: str = ""
    is_chain: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def geocode(place: str, session: requests.Session | None = None) -> tuple[float, float]:
    """ZIP code or 'City, ST' -> (lat, lon). Cached, since Nominatim asks for light use."""
    s = session or requests.Session()
    key = place.strip().lower()
    try:
        cache = json.loads(CACHE_PATH.read_text())
    except Exception:  # noqa: BLE001
        cache = {}
    if key in cache:
        return tuple(cache[key])
    params = {"format": "json", "limit": 1, "countrycodes": "us"}
    if re.fullmatch(r"\d{5}", key):
        params["postalcode"] = key
    else:
        params["q"] = place
    resp = s.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        raise ValueError(f"Couldn't find '{place}' on the map. Try a ZIP code or 'City, ST'.")
    lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
    cache[key] = [lat, lon]
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache))
    except Exception:  # noqa: BLE001
        pass
    return lat, lon


def overpass_query(lat: float, lon: float, radius_miles: float) -> str:
    r = int(radius_miles * 1609.34)
    amenity = "|".join(CATEGORIES["amenity"])
    shop = "|".join(CATEGORIES["shop"])
    return (
        f'[out:json][timeout:{TIMEOUT}];('
        f'nwr["amenity"~"^({amenity})$"](around:{r},{lat},{lon});'
        f'nwr["shop"~"^({shop})$"](around:{r},{lat},{lon});'
        f');out tags center;'
    )


def _address(tags: dict) -> str:
    street = " ".join(x for x in [tags.get("addr:housenumber"), tags.get("addr:street")] if x)
    return ", ".join(x for x in [street, tags.get("addr:city")] if x)


def group_businesses(elements: list[dict]) -> list[Employer]:
    """Overpass elements -> one Employer per brand/name, chains first, then by number of locations."""
    groups: dict[str, Employer] = {}
    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("brand") or tags.get("name") or "").strip()
        if not name:
            continue
        category = ""
        for key in ("amenity", "shop"):
            category = CATEGORIES[key].get(tags.get(key, ""), "")
            if category:
                break
        if not category:
            continue
        k = re.sub(r"[^a-z0-9]", "", name.lower())
        if k in groups:
            groups[k].locations += 1
            groups[k].is_chain = groups[k].is_chain or bool(tags.get("brand"))
        else:
            groups[k] = Employer(name=name, category=category, locations=1, address=_address(tags),
                                 is_chain=bool(tags.get("brand") or tags.get("brand:wikidata")))
    return sorted(groups.values(), key=lambda e: (not e.is_chain, -e.locations, e.name.lower()))


def find_employers(place: str, radius_miles: float, session: requests.Session | None = None) -> list[Employer]:
    s = session or requests.Session()
    lat, lon = geocode(place, s)
    resp = s.post(OVERPASS_URL, data={"data": overpass_query(lat, lon, radius_miles)},
                  headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT + 10)
    resp.raise_for_status()
    return group_businesses(resp.json().get("elements", []))


def job_links(name: str, place: str, radius_miles: int) -> dict[str, str]:
    """Where to look for this employer's openings. Google's own job panel works fine in a
    normal browser, even though automated searches get blocked."""
    q = quote_plus(name)
    where = quote_plus(place)
    return {
        "Google jobs": f"https://www.google.com/search?q={quote_plus(f'{name} jobs near {place}')}&udm=8",
        "Indeed": f"https://www.indeed.com/jobs?q=%22{q}%22&l={where}&radius={radius_miles}",
        "Careers page": f"https://www.google.com/search?q={quote_plus(name + ' careers apply')}",
    }
