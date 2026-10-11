"""Business discovery from OpenStreetMap (Nominatim + Overpass): free, keyless, ToS-friendly."""
from __future__ import annotations

import re
import time

import httpx

from . import USER_AGENT
from .store import Store
from .util import normalize_url, norm_phone

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

# keyword -> OSM tags. Anything not listed falls back to a name-regex search.
CATEGORY_TAGS: dict[str, list[tuple[str, str]]] = {
    "dentist": [("amenity", "dentist"), ("healthcare", "dentist")],
    "doctor": [("amenity", "doctors"), ("amenity", "clinic"), ("healthcare", "doctor")],
    "clinic": [("amenity", "clinic"), ("healthcare", "clinic")],
    "hospital": [("amenity", "hospital")],
    "pharmacy": [("amenity", "pharmacy")],
    "veterinary": [("amenity", "veterinary")],
    "restaurant": [("amenity", "restaurant")],
    "cafe": [("amenity", "cafe")],
    "bar": [("amenity", "bar"), ("amenity", "pub")],
    "hotel": [("tourism", "hotel"), ("tourism", "guest_house"), ("tourism", "hostel")],
    "gym": [("leisure", "fitness_centre")],
    "salon": [("shop", "hairdresser"), ("shop", "beauty")],
    "barber": [("shop", "hairdresser")],
    "bakery": [("shop", "bakery")],
    "supermarket": [("shop", "supermarket")],
    "clothes": [("shop", "clothes")],
    "electronics": [("shop", "electronics"), ("shop", "mobile_phone")],
    "car repair": [("shop", "car_repair")],
    "car dealer": [("shop", "car")],
    "school": [("amenity", "school")],
    "university": [("amenity", "university")],
    "bank": [("amenity", "bank")],
    "lawyer": [("office", "lawyer")],
    "accountant": [("office", "accountant")],
    "real estate": [("office", "estate_agent")],
    "travel agency": [("shop", "travel_agency"), ("office", "travel_agent")],
    "consultancy": [("office", "consulting"), ("office", "educational_institution")],
    "insurance": [("office", "insurance")],
    "architect": [("office", "architect")],
    "it": [("office", "it")],
}

_SOCIAL_BASE = {
    "facebook": "https://www.facebook.com/",
    "instagram": "https://www.instagram.com/",
    "twitter": "https://twitter.com/",
    "youtube": "https://www.youtube.com/",
}
_CAT_KEYS = ("amenity", "shop", "office", "tourism", "craft", "healthcare", "leisure")


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def geocode(place: str, client: httpx.Client) -> dict:
    r = client.get(NOMINATIM, params={"q": place, "format": "jsonv2", "limit": 1, "addressdetails": 1})
    r.raise_for_status()
    hits = r.json()
    if not hits:
        raise ValueError(f"Could not geocode {place!r}. Try a more specific place name or pass --latlon.")
    h = hits[0]
    return {
        "lat": float(h["lat"]),
        "lon": float(h["lon"]),
        "name": h.get("display_name", place),
        "region": (h.get("address", {}).get("country_code") or "").upper() or None,
    }


def build_query(keyword: str, lat: float, lon: float, radius_m: int, limit: int,
                osm_tags: list[tuple[str, str]] | None = None) -> str:
    around = f"(around:{int(radius_m)},{lat:.6f},{lon:.6f})"
    tags = osm_tags or CATEGORY_TAGS.get(keyword.lower().strip())
    if tags:
        body = "\n".join(f'  nwr{around}["{_q(k)}"="{_q(v)}"]["name"];' for k, v in tags)
    else:  # fallback: any named amenity/shop/office/... whose name matches the keyword
        kw = _q(re.sub(r"\s+", ".*", keyword.strip()))
        body = "\n".join(f'  nwr{around}["name"~"{kw}",i]["{k}"];' for k in _CAT_KEYS)
    return f"[out:json][timeout:60];\n(\n{body}\n);\nout center tags {int(limit)};"


def overpass_elements(payload: dict) -> list[dict]:
    """Return elements, or raise if Overpass reports it failed.

    Overpass answers HTTP 200 with an empty list and a `remark` when a query times out or the
    server is overloaded. Treating that as 'no businesses found' would be a silent failure.
    """
    remark = str(payload.get("remark") or "")
    if "runtime error" in remark.lower() or "timed out" in remark.lower() or "out of memory" in remark.lower():
        raise RuntimeError(remark[:160])
    return payload.get("elements", [])


def overpass(query: str, client: httpx.Client) -> list[dict]:
    errors: list[str] = []
    for attempt in range(3):
        for ep in OVERPASS_ENDPOINTS:
            try:
                r = client.post(ep, data={"data": query}, timeout=90)
                if r.status_code == 200:
                    return overpass_elements(r.json())
                errors.append(f"{ep.split('/')[2]} HTTP {r.status_code}")
            except (httpx.HTTPError, ValueError, RuntimeError) as e:
                errors.append(f"{ep.split('/')[2]} {type(e).__name__}: {str(e)[:80]}")
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("Overpass is overloaded or unreachable (public servers are shared). "
                       "Try again in a minute or use a smaller --radius. Last errors: " + "; ".join(errors[-3:]))


def _split(v: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[;|]", v or "") if p.strip()]


def claims_from_tags(tags: dict[str, str], region: str | None) -> list[tuple[str, str]]:
    """Pure function: OSM tags -> [(field, value)]. Easy to unit-test."""
    out: list[tuple[str, str]] = []
    for k in ("phone", "contact:phone", "mobile", "contact:mobile"):
        for p in _split(tags.get(k)):
            n = norm_phone(p, region)
            if n:
                out.append(("phone", n))
    for k in ("email", "contact:email"):
        for e in _split(tags.get(k)):
            if "@" in e:
                out.append(("email", e.lower()))
    for k in ("website", "contact:website", "url"):
        u = normalize_url(tags.get(k))
        if u:
            out.append(("website", u))
    for plat, base in _SOCIAL_BASE.items():
        for k in (f"contact:{plat}", plat):
            v = (tags.get(k) or "").strip()
            if v:
                out.append((f"social:{plat}", v if v.startswith("http") else base + v.lstrip("@/")))
    if tags.get("addr:full"):
        out.append(("address", tags["addr:full"]))
    else:
        street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
        parts = [street, tags.get("addr:suburb"), tags.get("addr:city"), tags.get("addr:postcode")]
        addr = ", ".join(p for p in parts if p)
        if addr:
            out.append(("address", addr))
    if tags.get("opening_hours"):
        out.append(("hours", tags["opening_hours"]))
        if tags["opening_hours"].strip().lower() == "off":
            out.append(("closed", "opening_hours=off"))
    return out


def category_of(tags: dict[str, str]) -> str | None:
    for k in _CAT_KEYS:
        if tags.get(k):
            return tags[k].replace("_", " ")
    return None


def discover(store: Store, keyword: str, near: str | None = None, latlon: tuple[float, float] | None = None,
             radius_m: int = 3000, limit: int = 200, osm_tags: list[tuple[str, str]] | None = None,
             region: str | None = None) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        if latlon:
            lat, lon = latlon
            place = f"{lat},{lon}"
        elif near:
            g = geocode(near, client)
            lat, lon, place = g["lat"], g["lon"], g["name"]
            region = region or g["region"]
        else:
            raise ValueError("Provide --near PLACE or --latlon LAT,LON")
        query = build_query(keyword, lat, lon, radius_m, limit, osm_tags)
        elements = overpass(query, client)

    if region:
        store.set_meta("region", region)
    created = merged = skipped = 0
    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        elat = el.get("lat") or (el.get("center") or {}).get("lat")
        elon = el.get("lon") or (el.get("center") or {}).get("lon")
        lid, is_new = store.upsert_lead(name, category_of(tags), elat, elon, region)
        created += is_new
        merged += not is_new
        src = f"osm:{el['type']}/{el['id']}"
        store.add_claim(lid, "name", name, src)
        for field, value in claims_from_tags(tags, region):
            store.add_claim(lid, field, value, src)
    store.commit()
    summary = {"place": place, "region": region, "found": len(elements), "created": created,
               "merged_duplicates": merged, "skipped_unnamed": skipped}
    store.log_run("discover", {"keyword": keyword, "near": near, "radius_m": radius_m}, summary)
    return summary
