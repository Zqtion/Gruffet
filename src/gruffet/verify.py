"""Cross-checking: independent gates -> score -> tier.

A lead is only "perfect" when every *required* gate passes on evidence from independent
source families (OSM tags vs the business's own website vs DNS), never on a single claim.

Gates (status: pass / fail / unknown):
  website_alive         the listed website answers and is not a parked/for-sale page   [hard]
  identity_match        the site is really this business (name match or shared phone)  [hard]
  not_closed            no "permanently closed" signal anywhere                        [hard]
  phone_corroborated    the same E.164 phone appears in >= min_sources families
  email_verified        an email whose domain has MX and ties to the site (or 2 families)
  contact_corroborated  phone_corroborated OR email_verified

Tiers: perfect (required gates pass) / agent-approved (borderline, accepted by the agent) /
review (some gates unknown) / incomplete (no contact data yet: missing data, NOT a bad lead) /
reject (a hard gate failed, or the agent rejected it).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import dns.exception
import dns.resolver
from rapidfuzz import fuzz

from .store import Store
from .util import norm_name, registered_domain

HARD_GATES = ("website_alive", "identity_match", "not_closed")
DEFAULT_REQUIRED = ("website_alive", "identity_match", "contact_corroborated", "not_closed")
ALL_TIERS = ("perfect", "agent-approved", "review", "incomplete", "reject", "new")


# -- DNS -----------------------------------------------------------------------
def mx_lookup(domain: str, timeout: float = 5.0) -> bool | None:
    """True = domain can receive mail, False = it cannot, None = lookup inconclusive."""
    res = dns.resolver.Resolver()
    res.lifetime = timeout
    try:
        res.resolve(domain, "MX")
        return True
    except dns.resolver.NoAnswer:
        try:  # RFC 5321: no MX -> implicit MX at A/AAAA
            res.resolve(domain, "A")
            return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return False
        except dns.exception.DNSException:
            return None
    except dns.resolver.NXDOMAIN:
        return False
    except dns.exception.DNSException:
        return None


def resolve_domains(domains: set[str]) -> dict[str, bool | None]:
    if not domains:
        return {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        return dict(zip(domains, pool.map(mx_lookup, domains)))


# -- individual gates ------------------------------------------------------------
def _first(store: Store, lid: str, field: str) -> str | None:
    v = store.values(lid, field)
    return v[0] if v else None


def gate_website_alive(store: Store, lid: str) -> tuple[str, str]:
    sites = store.values(lid, "website")
    if not sites:
        return "unknown", "no website listed"
    if _first(store, lid, "meta.robots_blocked"):
        return "unknown", "robots.txt disallows fetching this site"
    if _first(store, lid, "meta.parked"):
        return "fail", "parked or for-sale domain"
    status = _first(store, lid, "meta.http_status")
    if status is None:
        return "unknown", "site not fetched yet (run enrich)"
    code = int(status)
    note = " (invalid TLS cert)" if _first(store, lid, "meta.insecure_tls") else ""
    if 200 <= code < 300:
        return "pass", f"HTTP {code}{note}"
    if code in (401, 403, 429, 503):
        return "unknown", f"site refused automated access (HTTP {code})"
    if code == 0:
        return "fail", f"unreachable: {_first(store, lid, 'meta.error') or 'no response'}"[:160]
    return "fail", f"HTTP {code}"


def gate_identity(store: Store, lid: str, name: str) -> tuple[str, str]:
    if _first(store, lid, "meta.http_status") is None or not (_first(store, lid, "meta.title") or _first(store, lid, "meta.h1")
                                                              or _first(store, lid, "meta.text_sample")):
        return "unknown", "no site content to compare"
    # Strongest signal: a phone listed on OSM also appears on the site => same business.
    for p in store.values(lid, "phone"):
        fam = store.families_for(lid, "phone", p)
        if "osm" in fam and "site" in fam:
            return "pass", f"phone {p} appears on both OSM and the site"
    nn = norm_name(name)
    cands = [norm_name(v) for f in ("meta.jsonld_name", "meta.title", "meta.h1", "meta.site_name")
             for v in store.values(lid, f)]
    dom = registered_domain(_first(store, lid, "website"))
    if dom:
        cands.append(dom.split(".")[0].replace("-", " "))
    best = 0.0
    for c in cands:
        if not c:
            continue
        s = fuzz.token_set_ratio(nn, c)
        if len(nn) >= 5:
            s = max(s, fuzz.partial_ratio(nn, c))
        best = max(best, s)
    sample = norm_name(_first(store, lid, "meta.text_sample") or "")
    if nn and nn in sample:
        return "pass", "business name appears in the site text"
    if best >= 80:
        return "pass", f"name matches site title/domain ({best:.0f}/100)"
    if best >= 55:
        return "unknown", f"weak name match ({best:.0f}/100): check the site is this business"
    return "fail", f"site does not appear to be this business (name match {best:.0f}/100)"


def gate_not_closed(store: Store, lid: str) -> tuple[str, str]:
    hits = store.claims(lid, "closed")
    if hits:
        return "fail", f"closure signal ({hits[0]['source']}): {hits[0]['value'][:100]}"
    return "pass", "no closure signal found (absence of evidence, not proof)"


def gate_phone(store: Store, lid: str, min_sources: int) -> tuple[str, str]:
    phones = store.values(lid, "phone")
    if not phones:
        return "unknown", "no phone found"
    best_p, best_fam = None, set()
    for p in phones:
        fam = store.families_for(lid, "phone", p)
        if len(fam) > len(best_fam):
            best_p, best_fam = p, fam
    if len(best_fam) >= min_sources:
        return "pass", f"{best_p} confirmed by {'+'.join(sorted(best_fam))}"
    return "unknown", f"{best_p} seen only in {'+'.join(sorted(best_fam))}"


def gate_email(store: Store, lid: str, min_sources: int, mx: dict[str, bool | None]) -> tuple[str, str]:
    emails = store.values(lid, "email")
    if not emails:
        return "unknown", "no email found"
    site_dom = registered_domain(_first(store, lid, "website"))
    saw_dead = saw_unknown = False
    for e in emails:
        dom = e.rsplit("@", 1)[-1]
        ok = mx.get(dom)
        if ok is False:
            saw_dead = True
            continue
        if ok is None:
            saw_unknown = True
            continue
        fam = store.families_for(lid, "email", e)
        if registered_domain(dom) == site_dom and "site" in fam:
            return "pass", f"{e}: domain has MX and matches the business website"
        if len(fam) >= min_sources:
            return "pass", f"{e}: has MX and confirmed by {'+'.join(sorted(fam))}"
    if saw_unknown:
        return "unknown", "email domain lookup was inconclusive"
    if saw_dead:
        return "fail", "email domain has no mail server"
    return "unknown", f"{emails[0]}: single source or domain does not match the website"


# -- scoring ------------------------------------------------------------------
def score_lead(gates: dict[str, str], store: Store, lid: str) -> int:
    s = {"pass": 1.0, "unknown": 0.2, "fail": 0.0}
    pts = 25 * s[gates["website_alive"]] + 25 * s[gates["identity_match"]]
    pts += 15 * (1.0 if gates["phone_corroborated"] == "pass" else 0.25 if store.values(lid, "phone") else 0)
    pts += 15 * (1.0 if gates["email_verified"] == "pass" else 0.25 if store.values(lid, "email") else 0)
    pts += 10 if gates["not_closed"] == "pass" else 0
    pts += 4 if store.values(lid, "address") else 0
    pts += 2 if store.values(lid, "hours") else 0
    pts += 1 if store.lead(lid)["category"] else 0
    pts += 3 if any(r["field"].startswith("social:") for r in store.claims(lid)) else 0
    return int(round(pts))


def verify_lead(store: Store, lid: str, mx: dict[str, bool | None], required: tuple[str, ...] = DEFAULT_REQUIRED,
                min_sources: int = 2, min_score: int = 75) -> tuple[str, int]:
    lead = store.lead(lid)
    results = {
        "website_alive": gate_website_alive(store, lid),
        "identity_match": gate_identity(store, lid, lead["name"]),
        "not_closed": gate_not_closed(store, lid),
        "phone_corroborated": gate_phone(store, lid, min_sources),
        "email_verified": gate_email(store, lid, min_sources, mx),
    }
    if "pass" in (results["phone_corroborated"][0], results["email_verified"][0]):
        results["contact_corroborated"] = ("pass", "; ".join(
            r[1] for k, r in results.items() if k in ("phone_corroborated", "email_verified") and r[0] == "pass"))
    elif store.values(lid, "phone") or store.values(lid, "email"):
        results["contact_corroborated"] = ("unknown", "contact seen but not independently confirmed")
    else:
        results["contact_corroborated"] = ("fail", "no phone or email found anywhere")
    for gate, (status, detail) in results.items():
        store.set_gate(lid, gate, status, detail)
    status = {g: r[0] for g, r in results.items()}
    score = score_lead(status, store, lid)

    hard_fail = [g for g in HARD_GATES if status[g] == "fail"]
    v = store.verdict(lid)
    missing = [g for g in required if status.get(g) != "pass"]
    if hard_fail:  # evidence says this is not a usable lead
        tier, reason = "reject", f"{hard_fail[0]}: {results[hard_fail[0]][1]}"
    elif v and v["decision"] == "reject":
        tier, reason = "reject", f"agent rejected: {v['reason']}"
    elif status["contact_corroborated"] == "fail":
        # No evidence either way. This is missing data, not a bad business, so it is NOT a reject.
        if not store.values(lid, "website"):
            hint = "find the official website"
        elif status["website_alive"] != "pass":
            hint = f"website not readable ({results['website_alive'][1]}); check by hand"
        else:
            hint = "none found on its site"
        tier, reason = "incomplete", f"no contact data yet: {hint}"
    elif v and v["decision"] == "accept":
        tier, reason = "agent-approved", f"agent accepted: {v['reason']}"
    elif not missing and score >= min_score:
        tier, reason = "perfect", "all required gates passed"
    else:
        why = [f"{g}={status.get(g)}" for g in missing] or [f"score {score} < {min_score}"]
        tier, reason = "review", ", ".join(why)
    store.set_tier(lid, score, tier, reason)
    return tier, score


def verify_all(store: Store, required: tuple[str, ...] = DEFAULT_REQUIRED, min_sources: int = 2,
               min_score: int = 75, check_dns: bool = True) -> dict:
    leads = store.leads()
    domains = {e.rsplit("@", 1)[-1] for r in leads for e in store.values(r["id"], "email")} if check_dns else set()
    mx = resolve_domains(domains)
    counts: dict[str, int] = {}
    for r in leads:
        tier, _ = verify_lead(store, r["id"], mx, required, min_sources, min_score)
        counts[tier] = counts.get(tier, 0) + 1
    store.commit()
    store.log_run("verify", {"required": required, "min_sources": min_sources, "min_score": min_score}, counts)
    return counts
