"""Enrich leads from their own websites: homepage + up to two contact/about pages -> claims."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.parse import urlparse

from . import extract as ex
from . import techscan as ts
from .fetch import Fetcher, Page
from .store import Store
from .util import norm_phone, normalize_url


def _record_page(store: Store, lid: str, page: Page, region: str | None, is_home: bool) -> None:
    src = f"site:{page.final_url or page.url}"
    soup = ex.soup_of(page.html)
    text = ex.visible_text(soup)
    contact_page = "contact" in urlparse(page.final_url or page.url).path.lower()

    jl = ex.business_from_jsonld(ex.jsonld_items(soup))
    for n in jl["names"][:2]:
        store.add_claim(lid, "meta.jsonld_name", n, src)
    for p in jl["phones"]:
        n = norm_phone(p, region)
        if n:
            store.add_claim(lid, "phone", n, src, "EXTRACTED")
    for e in jl["emails"]:
        if "@" in e and ex._email_ok(e):
            store.add_claim(lid, "email", e, src, "EXTRACTED")
    for a in jl["addresses"][:1]:
        store.add_claim(lid, "address", a, src, "EXTRACTED")
    if jl["rating"]:
        store.add_claim(lid, "rating", jl["rating"], src, "EXTRACTED")

    for n, label in ex.extract_phones(soup, text, region, contact_page):
        store.add_claim(lid, "phone", n, src, label)
    for e, label in ex.extract_emails(soup, text):
        store.add_claim(lid, "email", e, src, label)
    for plat, url in ex.extract_socials(soup, page.final_url or page.url).items():
        store.add_claim(lid, f"social:{plat}", url, src, "EXTRACTED")

    for url in jl["images"]:
        store.add_image(lid, url, page.final_url or page.url, "", "photo")
    for url in jl["logos"]:
        store.add_image(lid, url, page.final_url or page.url, "", "logo")
    for im in ex.extract_images(soup, page.final_url or page.url):
        store.add_image(lid, im["url"], page.final_url or page.url, im["alt"], im["kind"])

    if is_home:
        for k, v in ex.page_meta(soup).items():
            if v:
                store.add_claim(lid, f"meta.{k}", v, src)
        if ex.looks_parked(text):
            store.add_claim(lid, "meta.parked", "1", src, "INFERRED")
        store.add_claim(lid, "meta.text_sample", text[:1500], src)
        for name in ts.tech_stack(page.html):
            store.add_claim(lid, "tech", name, src, "EXTRACTED")
        for sig, detail in ts.site_signals(page.html, page.final_url or page.url, soup).items():
            store.add_claim(lid, f"signal:{sig}", detail, src, "INFERRED")
    for snippet in ex.closed_signals(text):
        store.add_claim(lid, "closed", snippet, src, "INFERRED")


async def enrich_lead(store: Store, fetcher: Fetcher, lid: str, max_pages: int = 3) -> dict:
    lead = store.lead(lid)
    region = lead["region"] or store.get_meta("region")
    sites = [normalize_url(w) for w in store.values(lid, "website")]
    sites = [s for s in sites if s]
    store.clear_claims(lid, "site:")
    if not sites:
        return {"lead": lid, "status": "no_website"}
    home = await fetcher.get(sites[0])
    src = f"site:{home.final_url or home.url}"
    store.add_claim(lid, "meta.http_status", str(home.status or 0), src)
    if home.error:
        store.add_claim(lid, "meta.error", home.error, src)
    if home.blocked:
        store.add_claim(lid, "meta.robots_blocked", "1", src)
    if home.insecure_tls:
        store.add_claim(lid, "meta.insecure_tls", "1", src)
    if home.rendered:
        store.add_claim(lid, "meta.rendered", "1", src)
    if not home.ok:
        return {"lead": lid, "status": "unreachable", "error": home.error or home.status}

    _record_page(store, lid, home, region, is_home=True)
    soup = ex.soup_of(home.html)
    extra = ex.find_contact_links(soup, home.final_url or home.url, limit=max(0, max_pages - 1))
    pages = await asyncio.gather(*(fetcher.get(u) for u in extra))
    n = 1
    for pg in pages:
        if pg.ok:
            _record_page(store, lid, pg, region, is_home=False)
            n += 1
    store.commit()
    return {"lead": lid, "status": "ok", "pages": n}


async def enrich_all(store: Store, leads: list | None = None, concurrency: int = 8, render: str = "auto",
                     respect_robots: bool = True, max_pages: int = 3, refresh: bool = False,
                     progress: Callable[[int, int], None] | None = None) -> dict:
    leads = leads if leads is not None else store.leads()
    summary = {"leads": len(leads), "ok": 0, "unreachable": 0, "no_website": 0}
    gate = asyncio.Semaphore(concurrency * 2)
    done = 0
    async with Fetcher(store, concurrency=concurrency, render=render, respect_robots=respect_robots,
                       max_age_s=0 if refresh else 7 * 86400) as fetcher:
        async def one(row):
            nonlocal done
            async with gate:
                try:
                    r = await enrich_lead(store, fetcher, row["id"], max_pages)
                except Exception as e:  # one bad site must never kill the batch
                    r = {"status": "unreachable", "error": f"{type(e).__name__}: {e}"}
                summary[r["status"]] = summary.get(r["status"], 0) + 1
                done += 1
                if progress:
                    progress(done, len(leads))
        await asyncio.gather(*(one(r) for r in leads))
    store.commit()
    store.log_run("enrich", {"render": render, "max_pages": max_pages}, summary)
    return summary
