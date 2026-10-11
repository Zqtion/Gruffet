"""Pure site analysis: tech-stack signatures, website weak-spot signals, pricing and sitemap parsing.

Everything here is deterministic (no LLM, no network) and unit-tested. Signals are *hints for a human or
agent to weigh*, never verdicts: a missing analytics tag may just mean the site uses server-side tracking.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

# name -> regexes searched in lower-cased HTML. Order is display order.
TECH: dict[str, list[str]] = {
    "WordPress": [r"/wp-content/", r"/wp-includes/", r'name=["\']generator["\'][^>]*wordpress'],
    "Shopify": [r"cdn\.shopify\.com", r"shopify\.theme"],
    "Wix": [r"wixstatic\.com", r"static\.parastorage\.com"],
    "Squarespace": [r"static1\.squarespace\.com", r"squarespace-cdn\.com"],
    "Webflow": [r"data-wf-(page|site)", r"assets\.website-files\.com"],
    "Next.js": [r"/_next/static/", r"__next_data__"],
    "Nuxt/Vue": [r"/_nuxt/", r"data-server-rendered", r"__nuxt"],
    "React": [r"data-reactroot", r"react-dom"],
    "Angular": [r"ng-version=", r"<app-root"],
    "Gatsby": [r"___gatsby"],
    "jQuery": [r"jquery[.-][\d.]*(min\.)?js", r"/jquery\.js"],
    "Bootstrap": [r"bootstrap(\.min)?\.(css|js)", r"/bootstrap/"],
    "Google Analytics": [r"google-analytics\.com/", r"googletagmanager\.com/gtag/js"],
    "Google Tag Manager": [r"googletagmanager\.com/gtm\.js"],
    "Meta Pixel": [r"connect\.facebook\.net/[^\"']*/fbevents\.js", r"fbq\("],
    "Hotjar": [r"static\.hotjar\.com", r"hotjar\.com/c/hotjar"],
    "Plausible/Matomo": [r"plausible\.io/js", r"matomo\.(js|php)", r"/piwik\.js"],
    "HubSpot": [r"js\.hs-scripts\.com", r"js\.hsforms\.net"],
    "Mailchimp": [r"chimpstatic\.com", r"list-manage\.com"],
    "Klaviyo": [r"static\.klaviyo\.com"],
    "Stripe": [r"js\.stripe\.com"],
    "PayPal": [r"paypal\.com/sdk", r"paypalobjects\.com"],
    "Intercom": [r"widget\.intercom\.io"],
    "Tidio/Tawk/LiveChat": [r"code\.tidio\.co", r"embed\.tawk\.to", r"cdn\.livechatinc\.com"],
    "Zendesk": [r"static\.zdassets\.com", r"zendesk\.com/embeddable"],
    "WhatsApp chat": [r"wa\.me/", r"api\.whatsapp\.com/send", r"whatsapp-chat"],
    "Calendly/booking": [r"assets\.calendly\.com", r"calendly\.com/", r"booksy\.com", r"setmore\.com"],
    "reCAPTCHA": [r"google\.com/recaptcha", r"hcaptcha\.com"],
}
_ANALYTICS = {"Google Analytics", "Google Tag Manager", "Meta Pixel", "Hotjar", "Plausible/Matomo"}
_ENGAGE = {"Intercom", "Tidio/Tawk/LiveChat", "Zendesk", "WhatsApp chat", "Calendly/booking", "HubSpot"}


def tech_stack(html: str) -> list[str]:
    low = (html or "").lower()
    return [name for name, pats in TECH.items() if any(re.search(p, low) for p in pats)]


_COPY = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})", re.I)


def site_signals(html: str, final_url: str, soup: BeautifulSoup, today: date | None = None) -> dict[str, str]:
    """Weak-spot hints, useful to agencies and for competitor gaps. signal -> short detail."""
    today = today or date.today()
    out: dict[str, str] = {}
    stack = set(tech_stack(html))
    if final_url.lower().startswith("http://"):
        out["no_https"] = "served over plain http"
    if not soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}):
        out["no_mobile_viewport"] = "no responsive viewport meta tag"
    if not (stack & _ANALYTICS):
        out["no_analytics"] = "no analytics/pixel tag detected"
    if not (stack & _ENGAGE):
        out["no_chat_or_booking"] = "no chat, booking or CRM widget detected"
    if not soup.find("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        out["no_structured_data"] = "no schema.org JSON-LD"
    years = [int(y) for y in _COPY.findall(html or "") if 1990 <= int(y) <= today.year + 1]
    if years and max(years) <= today.year - 2:
        out["stale_copyright"] = f"footer says (c) {max(years)}"
    return out


# -- pricing -------------------------------------------------------------------
_PRICE = re.compile(r"(?<![\w.])((?:US\$|USD|CA\$|AU\$|\$|€|£|₹|৳|Rs\.?|PKR|BDT|INR|AED|CAD|AUD|EUR|GBP)\s?"
                    r"\d{1,3}(?:[,]\d{3})*(?:\.\d{1,2})?|\d{1,3}(?:[,]\d{3})*(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|PKR|BDT|INR))"
                    r"(?:\s?(?:/|per\s)\s?(mo(?:nth)?|month|yr|year|user|seat|hour|hr))?", re.I)
_GENERIC_HEAD = re.compile(r"^(pricing|prices?|plans?( (and|&) pricing)?|compare plans|our plans|choose a plan)$", re.I)
_PERIOD = re.compile(r"(/\s?mo|per month|monthly|/\s?yr|per year|annual|yearly|one[- ]time|per user|per seat)", re.I)


def extract_prices(soup: BeautifulSoup, cap: int = 8) -> list[dict]:
    """Heuristic: price tokens in short elements, labelled with the nearest preceding heading. -> INFERRED."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for el in soup.find_all(["span", "div", "p", "strong", "b", "h2", "h3", "h4", "li", "td"]):
        txt = el.get_text(" ", strip=True)
        # Skip containers: a card <div> that holds its own heading would inherit the *previous* card's heading.
        if not txt or len(txt) > 90 or el.find(["div", "p", "li", "td", "h1", "h2", "h3", "h4"]):
            continue
        m = _PRICE.search(txt)
        if not m:
            continue
        price = re.sub(r"\s+", "", m.group(1)) if re.match(r"^\D", m.group(1)) else m.group(1)
        period_m = _PERIOD.search(txt)
        if not period_m and el.parent is not None:
            period_m = _PERIOD.search(el.parent.get_text(" ", strip=True)[:140])
        period = (period_m.group(1).lower().replace(" ", "") if period_m else "")
        head = el.find_previous(["h1", "h2", "h3", "h4"])
        plan = head.get_text(" ", strip=True)[:40] if head is not None else ""
        if _GENERIC_HEAD.match(plan):  # "Pricing"/"Plans" is the page title, not a plan name
            plan = ""
        key = (plan, price + period)
        if key in seen:
            continue
        seen.add(key)
        out.append({"plan": plan, "price": price, "period": period})
        if len(out) >= cap:
            break
    return out


def price_line(p: dict) -> str:
    return f"{p['plan'] + ': ' if p['plan'] else ''}{p['price']}{p['period'] and ' ' + p['period']}"


# -- sitemap ---------------------------------------------------------------------
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>(?:\s*<lastmod>\s*([^<\s]+)\s*</lastmod>)?", re.I)


def parse_sitemap(xml: str) -> tuple[list[tuple[str, str | None]], list[str]]:
    """-> (page urls with lastmod, child sitemap urls). Handles sitemap indexes."""
    urls, children = [], []
    is_index = "<sitemapindex" in xml.lower()
    for m in _LOC.finditer(xml or ""):
        (children if is_index else urls).append(m.group(1) if is_index else (m.group(1), m.group(2)))
    return urls, children


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def sitemap_stats(urls: list[tuple[str, str | None]], today: date | None = None) -> dict:
    today = today or date.today()
    from urllib.parse import urlparse
    sections: dict[str, int] = {}
    blog = recent = 0
    newest: date | None = None
    for loc, lastmod in urls:
        path = urlparse(loc).path.strip("/")
        sec = path.split("/")[0] if path else "(home)"
        sections[sec] = sections.get(sec, 0) + 1
        if re.search(r"(^|/)(blog|news|articles|insights|posts?)(/|$)", path):
            blog += 1
        d = _parse_date(lastmod)
        if d:
            newest = max(newest, d) if newest else d
            if (today - d).days <= 90:
                recent += 1
    top = sorted(sections.items(), key=lambda kv: -kv[1])[:5]
    # Many CMSs stamp every URL with the generation date, so "recently updated" is meaningless there.
    unreliable = len(urls) > 50 and recent / len(urls) > 0.8
    return {"total": len(urls), "blog": blog, "newest": newest.isoformat() if newest else "", "recent_90d": recent,
            "lastmod_unreliable": unreliable, "top_sections": ", ".join(f"{k}({v})" for k, v in top)}
