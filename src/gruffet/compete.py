"""Competitor analysis: deterministic facts per competitor site, compact cards for the agent to reason over.

Per competitor: positioning (title/tagline/headings), pricing (heuristic), tech stack, content activity from the
sitemap, social presence, contact details and website weak spots. The agent writes the comparison (SWOT,
gaps) from the cards. Gruffet never makes the call itself, and every fact keeps its source.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

from . import extract as ex
from . import techscan as ts
from .fetch import Fetcher
from .store import Store
from .util import est_tokens, normalize_url, registered_domain

KEY_PAGES = {
    "pricing": re.compile(r"(pricing|plans?|packages?|rates|fees|price)", re.I),
    "features": re.compile(r"(features?|products?|services?|solutions?|what-we-do|offerings?)", re.I),
    "about": re.compile(r"(about|company|our-story|who-we-are)", re.I),
    "blog": re.compile(r"(blog|news|articles|insights|resources)", re.I),
    "careers": re.compile(r"(careers?|jobs|hiring|join-us|work-with-us)", re.I),
    "customers": re.compile(r"(customers|case-stud|testimonials|reviews|clients|success-stor)", re.I),
}
FETCH_KEYS = ("pricing", "features", "about")           # fetched and read; the rest are only noted if present
SITEMAPS = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml")


def find_key_pages(soup, base_url: str) -> dict[str, str]:
    """Best same-site link per key page type (shortest path wins)."""
    base_dom = registered_domain(base_url)
    best: dict[str, tuple[int, str]] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = normalize_url(urljoin(base_url, href.split("#")[0]))
        if not url or registered_domain(url) != base_dom:
            continue
        path = urlparse(url).path
        hay = path + " " + a.get_text(" ", strip=True)[:40]
        for key, rx in KEY_PAGES.items():
            if rx.search(hay) and (key not in best or len(path) < best[key][0]):
                best[key] = (len(path), url)
    return {k: v[1] for k, v in best.items() if v[1].rstrip("/") != base_url.rstrip("/")}


def add_competitors(store: Store, urls: list[str], note: str = "") -> list[str]:
    ids = []
    for u in urls:
        n = normalize_url(u)
        if n:
            ids.append(store.add_competitor(n, note))
    return ids


def from_leads(store: Store, tiers: tuple[str, ...]) -> list[str]:
    """Use the websites of verified leads as the competitor set (e.g. the local market)."""
    ids = []
    for r in store.leads(tiers):
        site = (store.values(r["id"], "website") or [None])[0]
        if site:
            ids.append(store.add_competitor(site, f"lead:{r['id']} {r['name']}"))
    return ids


def _meta_desc(soup) -> str:
    t = soup.find("meta", attrs={"name": re.compile("^description$", re.I)}) or soup.find("meta", attrs={"property": "og:description"})
    return (t.get("content") or "").strip()[:300] if t else ""


async def _sitemap(fetcher: Fetcher, base_url: str) -> dict | None:
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    for path in SITEMAPS:
        page = await fetcher.get(origin + path, allow_render=False)
        if not page.ok or "<loc" not in page.html.lower():
            continue
        urls, children = ts.parse_sitemap(page.html)
        for child in children[:3]:
            cp = await fetcher.get(child, allow_render=False)
            if cp.ok:
                urls += ts.parse_sitemap(cp.html)[0]
        if urls:
            return ts.sitemap_stats(urls)
    return None


async def analyze(store: Store, fetcher: Fetcher, cid: str, url: str) -> dict:
    store.clear_claims(cid, "site:")
    home = await fetcher.get(url)
    src = f"site:{home.final_url or home.url}"
    if not home.ok:
        store.add_claim(cid, "site.error", home.error or f"HTTP {home.status}", src)
        # 401/403/429/503 = the site refuses automated access. We respect that and do not work around it.
        status = "blocked" if home.status in (401, 403, 429, 503) or home.blocked else "unreachable"
        store.set_competitor_status(cid, status)
        return {"id": cid, "status": status}

    base = home.final_url or home.url
    soup = ex.soup_of(home.html)
    text = ex.visible_text(soup)
    meta = ex.page_meta(soup)
    for field, val in (("site.title", meta["title"]), ("site.description", _meta_desc(soup)), ("site.h1", meta["h1"])):
        if val:
            store.add_claim(cid, field, val, src)
    for h in [h.get_text(" ", strip=True)[:90] for h in soup.find_all("h2")][:6]:
        if h:
            store.add_claim(cid, "site.h2", h, src)

    for name in ts.tech_stack(home.html):
        store.add_claim(cid, "site.tech", name, src, "EXTRACTED")
    for sig, detail in ts.site_signals(home.html, base, soup).items():
        store.add_claim(cid, f"site.signal:{sig}", detail, src, "INFERRED")
    for plat, u in ex.extract_socials(soup, base).items():
        store.add_claim(cid, f"site.social:{plat}", u, src)
    for e, label in ex.extract_emails(soup, text)[:3]:
        store.add_claim(cid, "site.email", e, src, label)
    for p, label in ex.extract_phones(soup, text, None)[:3]:
        store.add_claim(cid, "site.phone", p, src, label)
    jl = ex.business_from_jsonld(ex.jsonld_items(soup))
    if jl["rating"]:
        store.add_claim(cid, "site.rating", jl["rating"], src)

    pages = find_key_pages(soup, base)
    for key, u in pages.items():
        store.add_claim(cid, f"site.page:{key}", u, src)
    prices = ts.extract_prices(soup)          # home often shows a starting price
    fetched = await asyncio.gather(*(fetcher.get(pages[k]) for k in FETCH_KEYS if k in pages))
    for key, pg in zip([k for k in FETCH_KEYS if k in pages], fetched):
        if not pg.ok:
            continue
        psoup, psrc = ex.soup_of(pg.html), f"site:{pg.final_url or pg.url}"
        if key == "pricing":
            prices += ts.extract_prices(psoup)
        elif key == "features":
            for h in [h.get_text(" ", strip=True)[:80] for h in psoup.find_all(["h2", "h3"])][:8]:
                if h:
                    store.add_claim(cid, "site.offering", h, psrc)
        elif key == "about" and _meta_desc(psoup):
            store.add_claim(cid, "site.about", _meta_desc(psoup), psrc)
    seen = set()
    for p in prices:
        line = ts.price_line(p)
        if line not in seen:
            seen.add(line)
            store.add_claim(cid, "site.price", line, src, "INFERRED")

    sm = await _sitemap(fetcher, base)
    if sm:
        fresh = ("lastmod looks auto-generated, so freshness is unknown" if sm["lastmod_unreliable"]
                 else f"{sm['recent_90d']} updated in last 90d")
        store.add_claim(cid, "site.content", f"{sm['total']} URLs; {sm['blog']} blog/news; newest {sm['newest'] or '?'}; "
                        f"{fresh}; sections: {sm['top_sections']}", src)
    store.set_competitor_status(cid, "ok")
    store.commit()
    return {"id": cid, "status": "ok"}


async def analyze_all(store: Store, concurrency: int = 6, render: str = "auto",
                      progress: Callable[[int, int], None] | None = None) -> dict:
    rows = store.competitors()
    summary = {"competitors": len(rows), "ok": 0, "unreachable": 0, "blocked": 0}
    done = 0
    gate = asyncio.Semaphore(concurrency)
    async with Fetcher(store, concurrency=concurrency, render=render) as fetcher:
        async def one(r):
            nonlocal done
            async with gate:
                try:
                    res = await analyze(store, fetcher, r["id"], r["url"])
                except Exception as e:  # one broken site must never kill the batch
                    store.add_claim(r["id"], "site.error", f"{type(e).__name__}: {e}"[:160], "site:error")
                    store.set_competitor_status(r["id"], "unreachable")
                    res = {"status": "unreachable"}
                summary[res["status"]] = summary.get(res["status"], 0) + 1
                done += 1
                if progress:
                    progress(done, len(rows))
        await asyncio.gather(*(one(r) for r in rows))
    store.commit()
    store.log_run("compete", {}, summary)
    return summary


def _v(store: Store, cid: str, field: str, n: int = 4, sep: str = "; ", width: int = 70) -> str:
    return sep.join(v[:width] for v in store.values(cid, field)[:n]) or "-"


def card(store: Store, row) -> str:
    cid = row["id"]
    if row["status"] == "blocked":
        return f"[{cid}] blocked: the site refuses automated access ({_v(store, cid, 'site.error', 1)}). Respected; review by hand.\n"
    if row["status"] == "unreachable":
        return f"[{cid}] unreachable: {_v(store, cid, 'site.error', 1)}\n"
    signals = [r["field"].split(":", 1)[1] + ("" if r["field"] != "site.signal:stale_copyright" else f" ({r['value']})")
               for r in store.claims(cid) if r["field"].startswith("site.signal:")]
    socials = [r["field"].split(":", 1)[1] for r in store.claims(cid) if r["field"].startswith("site.social:")]
    pages = [r["field"].split(":", 1)[1] for r in store.claims(cid) if r["field"].startswith("site.page:")]
    return (f"[{cid}] {_v(store, cid, 'site.title', 1)}\n"
            f"  pitch: {_v(store, cid, 'site.description', 1, width=170)} | h1: {_v(store, cid, 'site.h1', 1, width=90)}\n"
            f"  offers: {_v(store, cid, 'site.offering', 5)}\n"
            f"  pricing: {_v(store, cid, 'site.price', 5)}\n"
            f"  tech: {_v(store, cid, 'site.tech', 8, ', ')} | signals: {', '.join(signals) or '-'}\n"
            f"  content: {_v(store, cid, 'site.content', 1, width=190)} | pages: {', '.join(pages) or '-'}\n"
            f"  social: {', '.join(socials) or '-'} | contact: {_v(store, cid, 'site.phone', 1)} {_v(store, cid, 'site.email', 1)}\n")


def report(store: Store, budget: int = 1500) -> str:
    rows = store.competitors()
    if not rows:
        return "No competitors yet. Add some: gruffet compete add <url> ..."
    out, used = [], 0
    for i, r in enumerate(rows):
        c = card(store, r)
        t = est_tokens(c)
        if used + t > budget and out:
            out.append(f"... {len(rows) - i} more competitors (raise --budget)")
            break
        out.append(c)
        used += t
    out.append("Write the comparison from these facts only: positioning, pricing, tech, content activity, gaps. "
               "Pricing and signals are heuristics (INFERRED); check the source page before quoting a number.")
    return "\n".join(out)
