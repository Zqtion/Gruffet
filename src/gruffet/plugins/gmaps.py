"""OPT-IN, LOCAL-ONLY plugin: Google Maps results through a real browser.

READ THIS FIRST. Google's Terms of Service restrict scraping Maps, and Google may block you. You run this on
your own machine and you accept that risk. Do NOT use it inside a hosted or paid product, and don't redistribute
Google-derived data. It is never part of the default pipeline: it needs `--source gmaps --accept-google-tos-risk`.

Behaviour you can rely on:
- One headless browser, one search, slow scrolling, a hard cap on results. No proxies, no stealth tricks.
- If Google shows a CAPTCHA / "unusual traffic" page it STOPS and says so. It never tries to get past one.
- A cookie-consent page gets the privacy-preserving answer ("Reject all"); it never accepts tracking.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus, urlparse

import phonenumbers

from ..store import Store
from ..util import haversine_m, norm_phone, normalize_url

RISK_NOTICE = (
    "The Google Maps plugin is opt-in and local-only. Google's Terms of Service restrict scraping Maps and may block "
    "you; do not use it in a hosted or paid product or redistribute Google-derived data. If you accept that risk, "
    "re-run with --accept-google-tos-risk."
)
MAX_RESULTS = 120
_COORD = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
_AT = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
_STARS = re.compile(r"(\d(?:[.,]\d)?)\s*stars?(?:\s*([\d.,]+)\s*reviews?)?", re.I)
_PAREN = re.compile(r"(\d\.\d)\s*\(\s*([\d.,]+)\s*\)")
_GOOGLE_HOSTS = ("google.", "gstatic.", "googleusercontent.", "goo.gl", "ggpht.")
_CONSENT_BUTTON = re.compile(r"(reject all|tout refuser|alle ablehnen|rechazar todo|rifiuta tutto|alles afwijzen|"
                             r"recusar tudo|odrzuć wszystko)", re.I)


class MapsBlocked(RuntimeError):
    """Google asked for human verification or otherwise refused. We stop; we never work around it."""


# JS run inside the page: one record per result card, no interpretation.
_EXTRACT_JS = """() => {
  const feed = document.querySelector('div[role="feed"]');
  if (!feed) return [];
  const seen = new Set(), out = [];
  feed.querySelectorAll('a[href*="/maps/place/"]').forEach(a => {
    if (seen.has(a.href)) return; seen.add(a.href);
    let card = a.closest('div[role="article"]') || a.parentElement;
    for (let i = 0; i < 4 && card && (card.innerText || '').length < 25; i++) card = card.parentElement;
    if (!card) return;
    out.push({
      name: a.getAttribute('aria-label') || '',
      href: a.href,
      text: card.innerText || '',
      links: [...card.querySelectorAll('a[href]')].map(x => x.href),
      imgs: [...card.querySelectorAll('[role="img"][aria-label]')].map(x => x.getAttribute('aria-label')),
    });
  });
  return out;
}"""


# JS for a single place page: the stable data-item-id attributes carry website / phone / address.
_DETAIL_JS = """() => {
  const q = s => document.querySelector(s);
  const web = q('a[data-item-id="authority"]'), ph = q('button[data-item-id^="phone"]'), ad = q('button[data-item-id="address"]');
  return {
    website: web ? web.href : '',
    phone: ph ? ((ph.getAttribute('data-item-id') || '').replace('phone:tel:', '') || ph.innerText || '') : '',
    address: ad ? (ad.getAttribute('aria-label') || ad.innerText || '') : '',
  };
}"""


def parse_card(raw: dict, region: str | None) -> dict | None:
    """Pure: one raw DOM record -> a place dict. Heuristic on purpose, because Google's class names change often."""
    lines = [ln.strip() for ln in (raw.get("text") or "").splitlines() if ln.strip()]
    name = (raw.get("name") or (lines[0] if lines else "")).strip()
    if not name:
        return None
    href = raw.get("href") or ""
    m = _COORD.search(href) or _AT.search(href)
    lat, lon = (float(m.group(1)), float(m.group(2))) if m else (None, None)

    website = None
    detail_site = raw.get("website_detail") or ""
    if detail_site.startswith("http") and not any(g in (urlparse(detail_site).hostname or "") for g in _GOOGLE_HOSTS):
        website = normalize_url(detail_site)
    for link in ([] if website else raw.get("links") or []):
        host = (urlparse(link).hostname or "").lower()
        if link.startswith("http") and host and not any(g in host for g in _GOOGLE_HOSTS):
            website = normalize_url(link)
            break

    phone = norm_phone(re.sub(r"[^\d+]", "", raw.get("phone_detail") or ""), region) if raw.get("phone_detail") else None
    body = "\n".join(lines)
    try:
        for pm in ([] if phone else phonenumbers.PhoneNumberMatcher(body, region, leniency=phonenumbers.Leniency.VALID)):
            phone = phonenumbers.format_number(pm.number, phonenumbers.PhoneNumberFormat.E164)
            break
    except Exception:
        pass

    rating = None
    for label in list(raw.get("imgs") or []) + [body]:
        sm = _STARS.search(label) or _PAREN.search(label)
        if sm:
            n = (sm.group(2) or "").replace(",", "")
            rating = f"{sm.group(1).replace(',', '.')}" + (f" ({n} reviews)" if n else "")
            break

    category = address = None
    if raw.get("address_detail"):
        address = re.sub(r"^\s*Address:\s*", "", raw["address_detail"]).strip()
    for ln in lines:
        if "·" in ln or "⋅" in ln:
            parts = [p.strip() for p in re.split(r"[·⋅]", ln) if p.strip()]
            if parts and not category and not re.search(r"\d\.\d", parts[0]):
                category = parts[0]
                for p in parts[1:]:
                    if not address and (re.search(r"\d", p) or "," in p):
                        address = p
                        break
                if category:
                    break
    low = body.lower()
    closed = ("permanently closed" if "permanently closed" in low
              else "temporarily closed" if "temporarily closed" in low else None)
    return {"name": name, "href": href, "lat": lat, "lon": lon, "website": website, "phone": phone,
            "rating": rating, "category": category, "address": address, "closed": closed}


async def _handle_consent(page) -> None:
    if "consent.google" not in page.url:
        return
    btn = page.get_by_role("button", name=_CONSENT_BUTTON)
    if await btn.count() == 0:
        raise MapsBlocked("Google showed a cookie-consent page I couldn't answer automatically. "
                          "Open Google Maps once in your own browser, then retry.")
    await btn.first.click()  # privacy-preserving choice: reject non-essential cookies
    await page.wait_for_load_state("domcontentloaded")


async def _guard(page) -> None:
    content = (await page.content()).lower()
    if "/sorry/" in page.url or "unusual traffic" in content or 'src="https://www.google.com/recaptcha' in content:
        raise MapsBlocked("Google asked for human verification (CAPTCHA / unusual traffic). Stopped. "
                          "Gruffet will not try to get past it: wait a while, use a smaller --limit, or use the OSM source.")


async def _add_details(page, raw: list[dict]) -> None:
    """Open each place's own page to read website/phone/address. ~1 extra Google request per place, slow on purpose."""
    for r in raw:
        await asyncio.sleep(2.2)
        try:
            await page.goto(r["href"], wait_until="domcontentloaded", timeout=30000)
            await _guard(page)
            try:
                await page.wait_for_selector('button[data-item-id="address"], a[data-item-id="authority"]', timeout=6000)
            except Exception:
                pass  # some places have no address/website buttons
            d = await page.evaluate(_DETAIL_JS)
            r["website_detail"], r["phone_detail"], r["address_detail"] = d["website"], d["phone"], d["address"]
        except MapsBlocked:
            raise
        except Exception:
            continue  # one place failing to load must not lose the rest


async def scrape(query: str, place: str, limit: int, region: str | None, headless: bool = True,
                 details: bool = True) -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:  # pragma: no cover
        raise RuntimeError('The browser extra is required: pip install "gruffet[browser]" && crawl4ai-setup') from e
    limit = max(1, min(limit, MAX_RESULTS))
    url = "https://www.google.com/maps/search/" + quote_plus(f"{query} near {place}") + "?hl=en"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            ctx = await browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 900})
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await _handle_consent(page)
            await _guard(page)
            try:
                await page.wait_for_selector('div[role="feed"]', timeout=20000)
            except Exception:
                await _guard(page)
                raise RuntimeError("No results list appeared. Google may have changed its page, or the search has no "
                                   "matches. This plugin parses a live page, so it can break without warning.")
            raw: list[dict] = []
            for _ in range(14):  # slow, bounded scrolling
                raw = await page.evaluate(_EXTRACT_JS)
                if len(raw) >= limit or "reached the end of the list" in (await page.content()).lower():
                    break
                await page.evaluate("""() => { const f = document.querySelector('div[role="feed"]');
                                              if (f) f.scrollBy(0, f.scrollHeight); }""")
                await asyncio.sleep(1.8)
                await _guard(page)
            raw = raw[:limit]
            if details and raw:
                await _add_details(page, raw)
            return raw
        finally:
            await browser.close()


def discover_gmaps(store: Store, keyword: str, near: str, limit: int = 40, region: str | None = None,
                   center: tuple[float, float] | None = None, max_km: float = 25.0, headless: bool = True,
                   details: bool = True) -> dict:
    raw = asyncio.run(scrape(keyword, near, limit, region, headless, details))
    created = merged = skipped = 0
    for r in raw:
        p = parse_card(r, region)
        if not p:
            skipped += 1
            continue
        if center and p["lat"] is not None and haversine_m(center[0], center[1], p["lat"], p["lon"]) > max_km * 1000:
            skipped += 1  # Google padded the list with a far-away place
            continue
        lid, is_new = store.upsert_lead(p["name"], p["category"], p["lat"], p["lon"], region, fuzzy=True)
        created += is_new
        merged += not is_new
        src = f"gmaps:{p['href'][:200]}"
        store.add_claim(lid, "name", p["name"], src)
        if p["phone"]:
            store.add_claim(lid, "phone", norm_phone(p["phone"], region) or p["phone"], src)
        if p["website"]:
            store.add_claim(lid, "website", p["website"], src)
        if p["address"]:
            store.add_claim(lid, "address", p["address"], src)
        if p["rating"]:
            store.add_claim(lid, "rating", p["rating"], src)
        if p["closed"]:
            store.add_claim(lid, "closed", f"Google Maps: {p['closed']}", src)
    store.commit()
    summary = {"source": "gmaps", "cards": len(raw), "created": created, "merged_into_existing": merged, "skipped": skipped}
    store.log_run("discover-gmaps", {"keyword": keyword, "near": near, "limit": limit}, summary)
    return summary
