"""Gruffet Research Mode: intent-based discovery, deep crawl, citations and research memory.

Optional Agent Reach search uses Exa through mcporter (no shell, no credentials read).
The existing Gruffet Fetcher provides httpx, robots, caching and Crawl4AI fallback.
No language-model conclusions are fabricated by this module.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from . import extract
from .discover import CATEGORY_TAGS, discover
from .fetch import Fetcher
from .store import Store

STOP = {"a", "an", "and", "are", "at", "by", "for", "find", "from", "in", "is",
        "me", "of", "on", "or", "the", "to", "uk", "us", "with", "who", "which",
        "what", "that", "these", "their", "our", "about", "how", "can"}
PROSPECT_TERMS = re.compile(
    r"\b(prospects?|leads?|businesses|companies|firms?|agencies|solicitors?|"
    r"lawyers?|dentists?|decision.makers?|founders?|directors?|partners?|"
    r"outreach|clients?|competitors?)\b", re.I)
ROLE_TERMS = r"(?:managing partner|senior partner|partner|head of [a-z][a-z /-]{2,50}|director|founder|co-founder|chief [a-z ]{3,32} officer|CEO|CTO|CFO|solicitor|caseworker|manager|team lead)"
NAME = r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?){1,2}"
PERSON_FORWARD = re.compile(rf"\b(?P<name>{NAME})\s*[-–—,:|]\s*(?P<role>{ROLE_TERMS})\b", re.I)
PERSON_BACKWARD = re.compile(rf"\b(?P<role>{ROLE_TERMS})\s*[-–—,:|]\s*(?P<name>{NAME})\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>\]\[)\"']+", re.I)
DETAIL_TERMS = ("team", "people", "staff", "leadership", "about", "contact", "partner",
                "solicitor", "service", "practice", "pricing", "profile", "attorney", "lawyer")
LOCAL_KEYWORDS = {
    "law firms": "lawyer", "solicitors": "lawyer", "lawyers": "lawyer",
    "bakeries": "bakery", "dentists": "dentist", "cafes": "cafe",
    "restaurants": "restaurant", "accountants": "accountant",
    "estate agents": "real estate", "clinics": "clinic",
}


@dataclass
class Plan:
    question: str
    mode: str
    sources: list[str]
    searches: list[str]
    near: str = ""
    roles: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def plan_query(question: str, mode: str = "auto", source: str = "auto",
               near: str = "", roles: str = "", keywords: str = "") -> Plan:
    """Transparent rules, not an LLM. A coding agent may choose an explicit mode."""
    if not question.strip():
        raise ValueError("A research question is required")
    if mode == "auto":
        mode = "prospects" if PROSPECT_TERMS.search(question) else "research"
    if mode not in ("research", "prospects", "both"):
        raise ValueError("mode must be auto, research, prospects or both")
    role_list = [v.strip() for v in roles.split(",") if v.strip()]
    kw_list = [v.strip() for v in keywords.split(",") if v.strip()]
    if source == "auto":
        sources = ["agent-reach"]
        # OSM helps local place-based searches, not specialist B2B alone.
        if near and mode != "research" and osm_category(question):
            sources.append("osm")
    elif source == "both":
        sources = ["agent-reach", "osm"]
    elif source in ("agent-reach", "osm", "urls"):
        sources = [] if source == "urls" else [source]
    else:
        raise ValueError("unknown discovery source")
    searches = [question.strip()]
    if role_list:
        searches.append(question.strip() + " " + " ".join(role_list) + " team people")
    if mode in ("prospects", "both"):
        searches.append(question.strip() + " official website services team")
    notes = ["Rules-based intent routing; no model inference."]
    if mode in ("prospects", "both"):
        notes.append("Fit assessment is keyword evidence, not buyer intent prediction.")
    return Plan(question.strip(), mode, sources, searches, near, role_list, kw_list, notes)


def osm_category(question: str) -> str | None:
    low = question.lower()
    for phrase, tag in LOCAL_KEYWORDS.items():
        if re.search(r"\b" + re.escape(phrase) + r"\b", low):
            return tag
    for tag in sorted(CATEGORY_TAGS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(tag) + r"s?\b", low):
            return tag
    return None


def safe_url(raw: str) -> str | None:
    """Block local-network targets; Fetcher separately handles robots and rate limits."""
    try:
        url = raw.strip().rstrip(".,;:")
        p = urlparse(url)
        host = (p.hostname or "").lower().rstrip(".")
        if p.scheme not in ("http", "https") or not host or p.username or p.password:
            return None
        if p.port not in (None, 80, 443):
            return None
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return url.split("#", 1)[0]
    except ValueError:
        return None


def parse_reach_urls(output: str) -> list[str]:
    """Accept JSON mcporter content and URL-bearing text, never invent a result URL."""
    text = output
    try:
        data = json.loads(output)
        if isinstance(data, dict) and (data.get("error") or data.get("isError")):
            raise RuntimeError(str(data.get("error") or "Agent Reach returned an error"))
        candidates: list[str] = []

        def walk(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key.lower() in ("url", "link") and isinstance(value, str):
                        candidates.append(value)
                    else:
                        walk(value)
            elif isinstance(obj, list):
                for value in obj:
                    walk(value)
            elif isinstance(obj, str):
                candidates.extend(URL_RE.findall(obj))
        walk(data)
        text = "\n".join(candidates)
    except json.JSONDecodeError:
        pass
    seen: set[str] = set()
    results = []
    for raw in URL_RE.findall(text) + ([text] if text.startswith("https://") else []):
        url = safe_url(raw)
        if url and url not in seen:
            seen.add(url)
            results.append(url)
    return results


def search_agent_reach(query: str, limit: int, timeout: int = 45) -> list[str]:
    """Use the Exa backend configured by Agent Reach; do not run shell commands."""
    if not shutil.which("mcporter"):
        raise RuntimeError(
            "Agent Reach search unavailable: install mcporter and configure Exa. "
            "See docs/RESEARCH_MODE.md; or use --url to supply websites."
        )
    argv = ["mcporter", "call", "exa.web_search_exa", "query=" + query,
            "numResults=" + str(max(1, min(limit, 25))), "--output", "json"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Agent Reach/Exa search timed out") from exc
    if proc.returncode:
        raise RuntimeError("Agent Reach/Exa failed: " + (proc.stderr or proc.stdout)[:180])
    urls = parse_reach_urls(proc.stdout)
    if not urls and proc.stdout.strip():
        raise RuntimeError("Agent Reach returned no usable URLs (check Exa configuration/output)")
    return urls


def page_links(html: str, page_url: str, max_links: int = 4) -> list[str]:
    soup = extract.soup_of(html)
    base = (urlparse(page_url).hostname or "").lower().removeprefix("www.")
    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = safe_url(urljoin(page_url, str(a["href"])))
        if not href or href in seen:
            continue
        host = (urlparse(href).hostname or "").lower().removeprefix("www.")
        if host != base:
            continue
        path = urlparse(href).path.lower()
        label = a.get_text(" ", strip=True).lower()[:90]
        weight = sum(3 if t in path else 1 if t in label else 0 for t in DETAIL_TERMS)
        if weight:
            seen.add(href)
            found.append((weight, href))
    return [url for _, url in sorted(found, key=lambda p: (-p[0], p[1]))[:max_links]]


def extract_people(html: str, page_url: str, roles: list[str] | None = None) -> list[dict]:
    """Names and roles must appear together VERBATIM on the same short page text item."""
    soup = extract.soup_of(html)
    requested = [r.lower() for r in (roles or [])]
    people: dict[tuple[str, str], dict] = {}
    for item in soup.stripped_strings:
        evidence = " ".join(str(item).split())
        if not 8 <= len(evidence) <= 240:
            continue
        for pattern in (PERSON_FORWARD, PERSON_BACKWARD):
            for match in pattern.finditer(evidence):
                name, role = match.group("name"), match.group("role")
                if requested and not any(r in role.lower() for r in requested):
                    continue
                key = (name.casefold(), role.casefold())
                people[key] = {"name": name, "role": role, "source_url": page_url,
                               "evidence": evidence}
    return list(people.values())


def evidence_passages(html: str, question: str, keywords: list[str], limit: int = 4) -> list[str]:
    soup = extract.soup_of(html)
    terms = set(re.findall(r"[a-z]{4,}", question.lower())) - STOP
    terms |= set(k.lower() for k in keywords if len(k) > 2)
    matches: list[tuple[int, str]] = []
    seen: set[str] = set()
    for t in soup.stripped_strings:
        chunk = " ".join(str(t).split())
        if not 25 <= len(chunk) <= 420 or chunk in seen:
            continue
        low = chunk.lower()
        score = sum(1 for term in terms if term in low)
        if score:
            seen.add(chunk)
            matches.append((score, chunk))
    return [text for _, text in sorted(matches, key=lambda p: -p[0])[:limit]]


def extract_contacts(html: str, page_url: str) -> dict:
    soup = extract.soup_of(html)
    text = extract.visible_text(soup)
    emails = [e for e, _ in extract.extract_emails(soup, text)]
    phones = [p for p, _ in extract.extract_phones(soup, text, None, True)]
    return {"emails": sorted(set(emails))[:10], "phones": sorted(set(phones))[:10],
            "source_url": page_url}


def summarize_fit(question: str, pages: list[dict], keywords: list[str]) -> dict:
    """Transparent keyword coverage, not a probability of becoming a customer."""
    terms = keywords or [w for w in re.findall(r"[a-z]{4,}", question.lower())
                         if w not in STOP][:7]
    body = " ".join(e for p in pages for e in p.get("passages", [])).lower()
    matched = [w for w in terms if w.lower() in body]
    missing = [w for w in terms if w.lower() not in body]
    return {"matched": matched, "unconfirmed": missing,
            "status": "evidence-found" if matched else "needs-review"}


async def research(plan: Plan, store: Store, urls: list[str], limit: int = 10,
                   max_pages: int = 4, refresh: bool = False) -> dict:
    warnings: list[str] = []
    collected: list[tuple[str, str]] = [(u, "provided") for u in urls if safe_url(u)]
    if len(collected) != len(urls):
        warnings.append("Some supplied URLs were rejected as invalid or non-public.")
    if "agent-reach" in plan.sources:
        for q in plan.searches:
            try:
                collected += [(u, "agent-reach/exa") for u in await asyncio.to_thread(
                    search_agent_reach, q, limit)]
            except RuntimeError as exc:
                warnings.append(str(exc))
    if "osm" in plan.sources:
        if plan.near and (tag := osm_category(plan.question)):
            try:
                await asyncio.to_thread(discover, store, tag, near=plan.near, limit=limit)
                for row in store.leads():
                    for url in store.values(row["id"], "website"):
                        collected.append((url, "osm"))
            except Exception as exc:
                warnings.append("OSM unavailable: " + type(exc).__name__ + ": " + str(exc)[:140])
        else:
            warnings.append("OSM skipped: requires --near and a recognized place-based category.")
    dedup: dict[str, str] = {}
    for url, source in collected:
        clean = safe_url(url)
        if not clean:
            continue
        key = (urlparse(clean).hostname or "").lower() if plan.mode in ("prospects", "both") else clean
        dedup.setdefault(key, (clean, source))
    targets = list(dedup.values())[:limit]
    results = []
    async with Fetcher(store, concurrency=3, render="auto",
                       max_age_s=0 if refresh else 7 * 86400) as fetcher:
        for home_url, discovery in targets:
            page = await fetcher.get(home_url)
            if not page.ok:
                results.append({"url": home_url, "discovery": discovery, "status": "unavailable",
                                "error": page.error or f"HTTP {page.status}", "pages": []})
                continue
            pages = [page]
            # Only follow same-host internal pages; evidence is never inferred from search snippets.
            for extra in page_links(page.html, page.final_url or page.url, max_pages - 1):
                child = await fetcher.get(extra)
                if child.ok:
                    pages.append(child)
            found_people: dict[tuple[str, str], dict] = {}
            contacts: dict[str, dict] = {}
            details: list[dict] = []
            for pg in pages:
                url = pg.final_url or pg.url
                for person in extract_people(pg.html, url, plan.roles):
                    found_people[(person["name"].lower(), person["role"].lower())] = person
                c = extract_contacts(pg.html, url)
                for kind in ("emails", "phones"):
                    for value in c[kind]:
                        contacts[(kind, value)] = {"type": kind[:-1], "value": value, "source_url": url}
                details.append({"url": url, "rendered": pg.rendered,
                                "passages": evidence_passages(pg.html, plan.question, plan.keywords)})
            fit = summarize_fit(plan.question, details, plan.keywords)
            results.append({"url": page.final_url or home_url, "discovery": discovery, "status": "researched",
                            "pages": details, "people": list(found_people.values()),
                            "contacts": list(contacts.values()), "fit": fit})
    report = {"plan": asdict(plan), "created_at": time.time(),
              "results": results, "warnings": warnings,
              "coverage": {"targets": len(targets), "researched": sum(r["status"] == "researched" for r in results),
                           "people": sum(len(r.get("people", [])) for r in results)}}
    # SQLite memory: snapshot past jobs; site HTML already persists in Store's page cache.
    store.db.execute("""CREATE TABLE IF NOT EXISTS research_history
                         (id TEXT PRIMARY KEY, question TEXT, mode TEXT,
                          created_at REAL, result_json TEXT NOT NULL)""")
    job_id = hashlib.sha256(json.dumps({"question": plan.question,
                                        "time": report["created_at"]}).encode()).hexdigest()[:16]
    store.db.execute("INSERT INTO research_history VALUES (?,?,?,?,?)",
                     (job_id, plan.question, plan.mode, report["created_at"],
                      json.dumps(report, ensure_ascii=False)))
    store.commit()
    report["job_id"] = job_id
    return report


def write_report(report: dict, workdir: str | Path) -> dict[str, str]:
    from openpyxl import Workbook
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "research.json"
    md_path = root / "research.md"
    xlsx_path = root / "research.xlsx"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Gruffet research report", "", "**Question:** " + report["plan"]["question"],
             "**Mode:** " + report["plan"]["mode"], "",
             "> Source excerpts are evidence, not independently verified truth. Review before use.", ""]
    for n, item in enumerate(report["results"], 1):
        lines += [f"## {n}. {item['url']}", f"Status: {item['status']}", ""]
        if item.get("fit"):
            lines.append("**Matched criteria:** " + ", ".join(item["fit"]["matched"]))
        for person in item.get("people", []):
            lines.append(f"- **{person['name']} — {person['role']}**: {person['evidence']} ([source]({person['source_url']}))")
        for contact in item.get("contacts", []):
            lines.append(f"- {contact['type']}: {contact['value']} ([source]({contact['source_url']}))")
        for page in item.get("pages", []):
            for passage in page["passages"]:
                lines.append(f"> {passage}\n>\n> Source: {page['url']}\n")
    if report["warnings"]:
        lines += ["## Warnings"] + ["- " + w for w in report["warnings"]]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    wb = Workbook()
    ws = wb.active
    ws.title = "Research"
    ws.append(["URL", "Status", "Discovery", "Matched keywords", "People", "Contacts"])
    for item in report["results"]:
        ws.append([item["url"], item["status"], item["discovery"],
                   ", ".join(item.get("fit", {}).get("matched", [])),
                   len(item.get("people", [])), len(item.get("contacts", []))])
    evidence = wb.create_sheet("Evidence")
    evidence.append(["URL", "Type", "Value or excerpt", "Source URL"])
    for item in report["results"]:
        for person in item.get("people", []):
            evidence.append([item["url"], "person+role", person["evidence"], person["source_url"]])
        for contact in item.get("contacts", []):
            evidence.append([item["url"], contact["type"], contact["value"], contact["source_url"]])
        for page in item.get("pages", []):
            for passage in page["passages"]:
                evidence.append([item["url"], "passage", passage, page["url"]])
    wb.save(xlsx_path)
    return {"json": str(json_path), "markdown": str(md_path), "xlsx": str(xlsx_path)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gruffet: investigate a question or B2B prospects")
    ap.add_argument("question", help="Research question or ideal prospect description")
    ap.add_argument("--mode", choices=["auto", "research", "prospects", "both"], default="auto")
    ap.add_argument("--source", choices=["auto", "agent-reach", "osm", "both", "urls"], default="auto")
    ap.add_argument("--near", default="", help="Location for place-based searches")
    ap.add_argument("--roles", default="", help="Comma-separated titles (prospects)")
    ap.add_argument("--keywords", default="", help="Comma-separated qualification terms")
    ap.add_argument("--url", action="append", default=[], help="Supply URLs without a discovery provider")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--max-pages", type=int, default=4)
    ap.add_argument("--workdir", default="gruffet-out")
    ap.add_argument("--refresh", action="store_true", help="Refetch sites rather than use cache")
    ap.add_argument("--plan-only", action="store_true", help="Show provider routing, don't search")
    args = ap.parse_args(argv)
    plan = plan_query(args.question, args.mode, args.source, args.near, args.roles, args.keywords)
    if args.plan_only:
        print(json.dumps(asdict(plan), indent=2))
        return 0
    if not plan.sources and not args.url:
        ap.error("No source available. Supply --url or choose --source agent-reach")
    with_store = Store(args.workdir)
    try:
        report = asyncio.run(research(plan, with_store, args.url,
                                      max(1, min(args.limit, 100)),
                                      max(1, min(args.max_pages, 10)), args.refresh))
        paths = write_report(report, args.workdir)
    finally:
        with_store.close()
    print(json.dumps({"coverage": report["coverage"], "warnings": report["warnings"],
                      "files": paths}, indent=2))
    return 0 if report["coverage"]["researched"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
