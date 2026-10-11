"""Deterministic extraction from HTML: no LLM, no tokens.

Order of trust: JSON-LD (schema.org) > mailto:/tel: links > Cloudflare-protected emails >
regex over visible text. Each extractor returns plain data; labelling happens in enrich.py.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

import phonenumbers
from bs4 import BeautifulSoup

from .util import normalize_url, norm_phone, registered_domain

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_JUNK_TLDS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js", "woff", "woff2", "ttf", "ico", "pdf", "avif"}
_JUNK_DOMAINS = {"example.com", "domain.com", "email.com", "yourdomain.com", "sentry.io", "wixpress.com",
                 "sentry-next.wixpress.com", "mysite.com", "test.com"}
_JUNK_LOCALS = {"you", "your", "name", "email", "user", "username", "example", "test", "yourname", "john.doe"}
_OBFUSCATED = [
    (re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", re.I), "@"),
    (re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", re.I), "."),
]

_BUSINESS_TYPES = {
    "localbusiness", "organization", "corporation", "store", "restaurant", "dentist", "medicalbusiness",
    "medicalclinic", "physician", "legalservice", "attorney", "realestateagent", "travelagency",
    "healthclub", "beautysalon", "hairsalon", "autorepair", "hotel", "lodgingbusiness", "foodestablishment",
    "professionalservice", "financialservice", "accountingservice", "educationalorganization", "school",
    "pharmacy", "hospital", "bakery", "cafeorcoffeeshop", "barorpub", "gymorhealthclub", "homeandconstructionbusiness",
    "automotivebusiness", "emergencyservice", "sportsactivitylocation", "entertainmentbusiness",
}

_PARKED = re.compile(
    r"(this domain (is|may be) for sale|buy this domain|domain (has )?expired|parked (free|domain)|"
    r"sedoparking|hugedomains|future home of|domain is available|related searches:)", re.I)
_CLOSED = [re.compile(p, re.I) for p in (
    r"permanently\s+closed", r"closed\s+permanently", r"no\s+longer\s+(?:in\s+business|operating|open)",
    r"we\s+(?:have\s+)?(?:permanently\s+)?closed\s+(?:down|our\s+doors)")]

_SOCIAL = {
    "facebook.com": "facebook", "fb.com": "facebook", "instagram.com": "instagram", "linkedin.com": "linkedin",
    "twitter.com": "twitter", "x.com": "twitter", "youtube.com": "youtube", "tiktok.com": "tiktok",
    "wa.me": "whatsapp", "pinterest.com": "pinterest",
}
_SOCIAL_SKIP = re.compile(r"(sharer|share|intent|dialog|plugins|/tr\b|login|policies|privacy|/p/|/reel|/watch|/hashtag|/explore)", re.I)
_BAD_IMG = re.compile(
    r"(sprite|icon|favicon|pixel|spacer|loader|loading|placeholder|emoji|badge|payment|flag|arrow|button|"
    r"blank|1x1|tracking|googleadservices|doubleclick|gravatar|captcha|star-rating|rating-star)", re.I)
_CONTACT_HINT = re.compile(r"(contact|about|reach|get-in-touch|find-us|location|visit)", re.I)


def soup_of(html: str) -> BeautifulSoup:
    # Lone surrogates (from odd encodings or browser output) make lxml raise; one bad page must not kill a batch.
    clean = (html or "").encode("utf-8", "replace").decode("utf-8", "replace")
    return BeautifulSoup(clean, "lxml")


def visible_text(html_or_soup) -> str:
    soup = soup_of(html_or_soup) if isinstance(html_or_soup, str) else html_or_soup
    soup = BeautifulSoup(str(soup), "lxml") if not isinstance(html_or_soup, str) else soup
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def page_meta(soup: BeautifulSoup) -> dict[str, str]:
    def meta(**attrs):
        t = soup.find("meta", attrs=attrs)
        return (t.get("content") or "").strip() if t else ""
    h1 = soup.find("h1")
    return {
        "title": (soup.title.get_text(strip=True) if soup.title else "")[:200],
        "h1": (h1.get_text(" ", strip=True) if h1 else "")[:200],
        "site_name": meta(property="og:site_name")[:200],
    }


# -- JSON-LD -------------------------------------------------------------
def jsonld_items(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            out.append(node)
            walk(node.get("@graph", []))

    for s in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = (s.string or s.get_text() or "").strip()
        if not raw:
            continue
        try:
            walk(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def _types(item: dict) -> set[str]:
    t = item.get("@type", [])
    t = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
    return {str(x).rsplit("/", 1)[-1].lower() for x in t}


def _as_list(v) -> list:
    return v if isinstance(v, list) else ([] if v in (None, "") else [v])


def _img_urls(v) -> list[str]:
    urls: list[str] = []
    for x in _as_list(v):
        if isinstance(x, str):
            urls.append(x)
        elif isinstance(x, dict) and isinstance(x.get("url") or x.get("contentUrl"), str):
            urls.append(x.get("url") or x.get("contentUrl"))
    return urls


def _address(a) -> str:
    if isinstance(a, str):
        return a
    if isinstance(a, dict):
        country = a.get("addressCountry")
        country = country.get("name") if isinstance(country, dict) else country
        parts = [a.get("streetAddress"), a.get("addressLocality"), a.get("addressRegion"), a.get("postalCode"), country]
        return ", ".join(str(p) for p in parts if p)
    return ""


def business_from_jsonld(items: list[dict]) -> dict:
    """Merge the business-like JSON-LD nodes of a page into one record."""
    rec: dict = {"names": [], "phones": [], "emails": [], "urls": [], "addresses": [], "images": [],
                 "logos": [], "same_as": [], "rating": None}
    for it in items:
        types = _types(it)
        if not (types & _BUSINESS_TYPES or (it.get("name") and (it.get("telephone") or it.get("address")))):
            continue
        if isinstance(it.get("name"), str):
            rec["names"].append(it["name"].strip())
        rec["phones"] += [str(p) for p in _as_list(it.get("telephone"))]
        rec["emails"] += [str(e).replace("mailto:", "").strip().lower() for e in _as_list(it.get("email"))]
        rec["urls"] += [str(u) for u in _as_list(it.get("url")) if isinstance(u, str)]
        addr = _address(it.get("address"))
        if addr:
            rec["addresses"].append(addr)
        rec["images"] += _img_urls(it.get("image"))
        rec["logos"] += _img_urls(it.get("logo"))
        rec["same_as"] += [str(u) for u in _as_list(it.get("sameAs")) if isinstance(u, str)]
        ar = it.get("aggregateRating")
        if isinstance(ar, dict) and ar.get("ratingValue"):
            rec["rating"] = f"{ar.get('ratingValue')} ({ar.get('reviewCount') or ar.get('ratingCount') or '?'} reviews)"
    return rec


# -- contacts ---------------------------------------------------------------
def decode_cfemail(hexstr: str) -> str | None:
    """Decode Cloudflare's data-cfemail obfuscation."""
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2)).lower()
    except (ValueError, IndexError):
        return None


_SYSTEM_LOCAL = re.compile(r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster|abuse|unsubscribe|bounce)", re.I)
_NOISE_LOCAL = re.compile(r"(speak[-_.]?up|privacy|dpo|gdpr|careers?|jobs?|recruit|press|media|webmaster|complaints?|"
                          r"foi|safeguarding|accessibility|unsubscribe|donotreply)", re.I)
_BUSINESS_LOCAL = re.compile(r"^(info|contact|enquir(y|ies)|hello|reception|appointments?|bookings?|office|admin|"
                             r"sales|support|team|mail|clinic|practice|smiles?)(?=$|[-_.@0-9])", re.I)


def email_rank(e: str) -> int:
    """Lower is better: role inboxes people actually read, then names, then noisy/system boxes."""
    local = e.split("@", 1)[0]
    if _BUSINESS_LOCAL.match(local):
        return 0
    if _NOISE_LOCAL.search(local):
        return 2
    return 1


def _email_ok(e: str) -> bool:
    local, _, dom = e.lower().rpartition("@")
    return bool(local and dom and len(e) <= 254 and dom.rsplit(".", 1)[-1] not in _JUNK_TLDS
                and dom not in _JUNK_DOMAINS and local not in _JUNK_LOCALS and ".." not in e
                and not _SYSTEM_LOCAL.match(local))


def extract_emails(soup: BeautifulSoup, text: str) -> list[tuple[str, str]]:
    """-> [(email, label)]. mailto/cfemail = EXTRACTED; plain text = EXTRACTED; de-obfuscated = INFERRED."""
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if h.lower().startswith("mailto:"):
            for e in EMAIL_RE.findall(h[7:].split("?")[0]):
                if _email_ok(e):
                    found.setdefault(e.lower(), "EXTRACTED")
    for t in soup.find_all(attrs={"data-cfemail": True}):
        e = decode_cfemail(t["data-cfemail"])
        if e and _email_ok(e):
            found.setdefault(e, "EXTRACTED")
    for e in EMAIL_RE.findall(text):
        if _email_ok(e):
            found.setdefault(e.lower(), "EXTRACTED")
    deob = text
    for rx, rep in _OBFUSCATED:
        deob = rx.sub(rep, deob)
    if deob != text:
        for e in EMAIL_RE.findall(deob):
            if _email_ok(e):
                found.setdefault(e.lower(), "INFERRED")
    return list(found.items())


def _contact_scope_text(soup: BeautifulSoup, whole: bool, full_text: str) -> str:
    if whole:
        return full_text
    chunks = []
    for el in soup.find_all(["footer", "header", "address"]):
        chunks.append(el.get_text(" ", strip=True))
    for el in soup.find_all(attrs={"class": re.compile("contact", re.I)}):
        chunks.append(el.get_text(" ", strip=True))
    for el in soup.find_all(attrs={"id": re.compile("contact", re.I)}):
        chunks.append(el.get_text(" ", strip=True))
    return " \n ".join(chunks)


def extract_phones(soup: BeautifulSoup, full_text: str, region: str | None, contact_page: bool = False,
                   cap: int = 5) -> list[tuple[str, str]]:
    """-> [(E.164, label)]. tel: links are EXTRACTED; numbers matched in text are INFERRED."""
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        if a["href"].lower().startswith("tel:"):
            n = norm_phone(a["href"][4:].split(";")[0], region)
            if n:
                found.setdefault(n, "EXTRACTED")
    scope = _contact_scope_text(soup, contact_page, full_text)
    if not scope.strip() or (not found and len(full_text) < 3000):
        scope = full_text  # tiny pages put the phone in the body; long pages stay scoped to avoid noise
    if scope:
        try:
            for m in phonenumbers.PhoneNumberMatcher(scope, region, leniency=phonenumbers.Leniency.VALID):
                found.setdefault(phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164), "INFERRED")
                if len(found) >= cap:
                    break
        except Exception:
            pass
    return list(found.items())[:cap]


def extract_socials(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    """Business pages only (LinkedIn /company, not personal /in profiles)."""
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"])
        p = urlparse(url)
        host = (p.hostname or "").lower().removeprefix("www.")
        plat = _SOCIAL.get(host)
        if not plat or _SOCIAL_SKIP.search(url):
            continue
        path = p.path.strip("/")
        if not path:
            continue
        if plat == "linkedin" and not path.startswith(("company", "school")):
            continue
        out.setdefault(plat, f"https://{host}/{path}")
    return out


# -- images -----------------------------------------------------------------
def _best_srcset(srcset: str) -> str | None:
    best, best_w = None, -1.0
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 1.0
        if len(bits) > 1:
            try:
                w = float(bits[1].rstrip("wx"))
            except ValueError:
                pass
        if w > best_w:
            best, best_w = bits[0], w
    return best


def extract_images(soup: BeautifulSoup, base_url: str, cap: int = 30) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []

    def add(raw, alt="", kind="photo", cls=""):
        if not raw or raw.startswith("data:"):
            return
        url = urljoin(base_url, raw.strip())
        p = urlparse(url)
        if p.scheme not in ("http", "https") or url in seen:
            return
        low = p.path.lower()
        if low.endswith((".svg", ".ico")) or _BAD_IMG.search(p.path + " " + cls):
            return
        if kind == "photo" and "logo" in (low + " " + alt.lower() + " " + cls.lower()):
            kind = "logo"
        seen.add(url)
        out.append({"url": url, "alt": alt[:200], "kind": kind})

    for prop in ("og:image", "og:image:url", "twitter:image"):
        t = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if t:
            add(t.get("content"), kind="cover")
    for img in soup.find_all("img"):
        try:
            w, h = int(re.sub(r"\D", "", img.get("width", "") or "0") or 0), int(re.sub(r"\D", "", img.get("height", "") or "0") or 0)
        except ValueError:
            w = h = 0
        if (w and w < 80) or (h and h < 80):
            continue
        src = (_best_srcset(img.get("srcset") or img.get("data-srcset") or "")
               or img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src"))
        add(src, img.get("alt", "") or "", cls=" ".join(img.get("class", []) or []))
        if len(out) >= cap:
            break
    return out[:cap]


# -- navigation / signals ---------------------------------------------------
def find_contact_links(soup: BeautifulSoup, base_url: str, limit: int = 2) -> list[str]:
    base_dom = registered_domain(base_url)
    scored: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = normalize_url(urljoin(base_url, href.split("#")[0]))
        if not url or registered_domain(url) != base_dom or url.rstrip("/") == base_url.rstrip("/"):
            continue
        hay = urlparse(url).path + " " + a.get_text(" ", strip=True)
        if _CONTACT_HINT.search(hay):
            scored[url] = max(scored.get(url, 0), 2 if "contact" in hay.lower() else 1)
    return [u for u, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:limit]


_JS_ROOT = re.compile(r"""(id=["'](root|app|__next|__nuxt|svelte)["']|ng-app|data-reactroot|data-server-rendered)""", re.I)
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\b(?:src|type=[\"']application/ld\+json)\b)[^>]*>(.*?)</script>", re.I | re.S)
_NEEDS_JS = re.compile(r"(enable javascript|requires javascript|javascript is (required|disabled)|turn on javascript)", re.I)


def needs_js(html: str, text: str) -> bool:
    """Heuristic: nearly empty visible text AND real signs of a client-side app. A tiny static page with one
    inline script (e.g. example.com) must not trigger a browser launch."""
    if len(text) >= 200:
        return False
    low = html.lower()
    inline = sum(len(m.group(1)) for m in _INLINE_SCRIPT.finditer(html))   # app code/data, not JSON-LD
    return bool(_NEEDS_JS.search(html) or _JS_ROOT.search(html) or inline > 500
                or low.count("<script src") + low.count("<script async src") >= 2)


def looks_parked(text: str) -> bool:
    return bool(_PARKED.search(text[:6000]))


def closed_signals(text: str) -> list[str]:
    hits = []
    for rx in _CLOSED:
        m = rx.search(text)
        if m:
            s = max(0, m.start() - 40)
            hits.append(text[s:m.end() + 40].strip())
    return hits
