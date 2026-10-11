"""`gruffet doctor`: probe each backend for real (Agent Reach style), not just check it is installed."""
from __future__ import annotations

import importlib.util
import sys

import httpx

from . import USER_AGENT, __version__
from .verify import mx_lookup

OK, WARN, BAD = "OK ", "!  ", "X  "


def _probe(url: str, **kw) -> tuple[bool, str]:
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=10, follow_redirects=True, **kw)
        return r.status_code < 400, f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        return False, type(e).__name__


def run() -> int:
    lines: list[tuple[str, str]] = [(OK, f"gruffet {__version__} on Python {sys.version.split()[0]}")]
    ok, d = _probe("https://nominatim.openstreetmap.org/status")
    lines.append((OK if ok else BAD, f"Nominatim geocoding (OpenStreetMap): {d}"))
    ok, d = _probe("https://overpass-api.de/api/status")
    lines.append((OK if ok else WARN, f"Overpass business search (primary): {d}"))
    mx = mx_lookup("gmail.com")
    lines.append((OK if mx else (WARN if mx is None else BAD), "DNS MX lookup (email verification): "
                  + ("working" if mx else "inconclusive - offline or DNS blocked" if mx is None else "failing")))
    has_c4ai = importlib.util.find_spec("crawl4ai") is not None
    lines.append((OK if has_c4ai else WARN,
                  "Crawl4AI browser fallback for JS-only sites: " + ("installed" if has_c4ai else
                  'not installed (optional): pip install "gruffet[browser]" && crawl4ai-setup')))
    lines.append((OK if importlib.util.find_spec("PIL") else BAD, "Pillow image support"))
    has_pw = importlib.util.find_spec("playwright") is not None
    lines.append((OK if has_pw else WARN, "Google Maps plugin (opt-in, local only, against Google's terms): "
                  + ("available, needs --source gmaps --accept-google-tos-risk" if has_pw else
                     'needs the browser extra: pip install "gruffet[browser]"')))
    print("gruffet doctor\n" + "=" * 40)
    for sym, msg in lines:
        print(f"  {sym} {msg}")
    bad = sum(1 for s, _ in lines if s == BAD)
    print(f"\n{'All required backends working.' if not bad else f'{bad} required backend(s) failing.'}")
    return 1 if bad else 0
