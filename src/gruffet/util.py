"""Small pure helpers: name/URL/phone normalisation and geo distance."""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from urllib.parse import urlparse, urlunparse

import phonenumbers
import tldextract

# Offline-safe: use the bundled public-suffix snapshot, never hit the network.
_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

_LEGAL = {"ltd", "limited", "llc", "inc", "incorporated", "corp", "co", "pvt", "private", "pllc", "gmbh", "sa", "srl"}
_FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "yandex.com",
    "zoho.com", "msn.com",
}


def norm_name(name: str) -> str:
    """Lowercase, accent-stripped, punctuation-free, legal suffixes dropped."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    toks = [t for t in s.split() if t not in _LEGAL]
    return " ".join(toks)


def lead_id(name: str, lat: float | None, lon: float | None) -> str:
    key = f"{norm_name(name)}|{round(lat or 0, 3)}|{round(lon or 0, 3)}"
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def normalize_url(u: str | None) -> str | None:
    """Return a clean http(s) URL, or None if it can't be one."""
    if not u:
        return None
    u = u.strip()
    if not u or u.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        u = "https://" + u.lstrip("/")
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        return None
    return urlunparse((p.scheme, p.netloc.lower(), p.path or "/", "", p.query, ""))


def registered_domain(url_or_host: str | None) -> str | None:
    if not url_or_host:
        return None
    host = urlparse(url_or_host).hostname if "://" in url_or_host else url_or_host
    if not host:
        return None
    ext = _TLD(host)
    return ext.top_domain_under_public_suffix.lower() if ext.top_domain_under_public_suffix else None


def is_freemail(domain: str | None) -> bool:
    return (domain or "").lower() in _FREEMAIL


def norm_phone(raw: str | None, region: str | None = None) -> str | None:
    """Parse to E.164, or None if it isn't a valid number."""
    if not raw:
        return None
    try:
        num = phonenumbers.parse(raw.strip(), region.upper() if region else None)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def est_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token); good enough for budget caps."""
    return (len(text) + 3) // 4
