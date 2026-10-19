"""gruffet command line. Designed to be driven by a coding agent: terse, deterministic output."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter

from . import __version__
from .store import Store
from .verify import DEFAULT_REQUIRED


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--workdir", default=os.environ.get("GRUFFET_DIR", "gruffet-out"),
                   help="where the database, images and reports live (default: ./gruffet-out)")
    return p


def _parse_latlon(s: str) -> tuple[float, float]:
    try:
        a, b = s.split(",")
        return float(a), float(b)
    except ValueError:
        raise argparse.ArgumentTypeError("use --latlon LAT,LON, e.g. 31.52,74.35")


def _parse_tag(s: str) -> tuple[str, str]:
    if "=" not in s:
        raise argparse.ArgumentTypeError("use KEY=VALUE, e.g. amenity=dentist")
    k, v = s.split("=", 1)
    return k.strip(), v.strip()


def build_parser() -> argparse.ArgumentParser:
    c = _common()
    ap = argparse.ArgumentParser(prog="gruffet", description=__doc__)
    ap.add_argument("--version", action="version", version=f"gruffet {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", parents=[c], help="probe every backend and report what works")
    sub.add_parser("research", help="research any question or prospect profile using available providers")

    def add_discover(p):
        p.add_argument("keyword", help='what to find, e.g. "dentist", "restaurant", "travel agency"')
        g = p.add_mutually_exclusive_group()
        g.add_argument("--near", help='place name, e.g. "Lahore, Pakistan"')
        g.add_argument("--latlon", type=_parse_latlon, help="LAT,LON instead of --near")
        p.add_argument("--radius", type=int, default=3000, help="search radius in metres (default 3000)")
        p.add_argument("--limit", type=int, default=200, help="max businesses to pull (default 200)")
        p.add_argument("--osm-tag", type=_parse_tag, action="append", help="explicit OSM tag KEY=VALUE (repeatable)")
        p.add_argument("--region", help="ISO country code for phone parsing, e.g. PK (auto-detected from --near)")
        p.add_argument("--source", choices=["osm", "gmaps", "both"], default="osm",
                       help="osm (default, keyless and ToS-friendly) | gmaps (opt-in plugin) | both")
        p.add_argument("--gmaps-no-details", action="store_true",
                       help="gmaps: don't open each place page (fewer Google requests, but no website/phone)")
        p.add_argument("--accept-google-tos-risk", action="store_true",
                       help="required for --source gmaps/both: you accept Google's terms risk; local use only")

    def add_enrich(p):
        p.add_argument("--render", choices=["never", "auto", "always"], default="auto",
                       help="browser rendering for JS-only sites (needs the [browser] extra)")
        p.add_argument("--concurrency", type=int, default=8)
        p.add_argument("--max-pages", type=int, default=3, help="pages per site: home + contact/about (default 3)")
        p.add_argument("--refresh", action="store_true", help="ignore the 7-day page cache")

    def add_verify(p):
        p.add_argument("--require", default=",".join(DEFAULT_REQUIRED), help="gates that must pass for 'perfect'")
        p.add_argument("--min-sources", type=int, default=2, help="independent source families to corroborate a phone/email")
        p.add_argument("--min-score", type=int, default=75, help="minimum score for 'perfect' (default 75; use 90+ to demand phone AND email)")
        p.add_argument("--no-dns", action="store_true", help="skip MX lookups (offline)")

    p = sub.add_parser("discover", parents=[c], help="find businesses on OpenStreetMap")
    add_discover(p)
    p = sub.add_parser("enrich", parents=[c], help="read each lead's own website for contacts, socials, images")
    add_enrich(p)
    p = sub.add_parser("verify", parents=[c], help="cross-check every lead and assign a tier")
    add_verify(p)
    p = sub.add_parser("review", parents=[c], help="compact cards for borderline leads (for the agent to judge)")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--budget", type=int, default=1500, help="approx token cap for the output")
    p = sub.add_parser("show", parents=[c], help="all evidence for one lead")
    p.add_argument("id")
    p.add_argument("--budget", type=int, default=1200)
    p = sub.add_parser("resolve", parents=[c], help="record the agent's verdict on a review lead")
    p.add_argument("id")
    p.add_argument("decision", choices=["accept", "reject"])
    p.add_argument("--reason", required=True)
    p.add_argument("--rename", help="with accept: the business's current name, when the listed name is stale")
    p = sub.add_parser("missing", parents=[c], help="leads with no website, for the agent to web-search")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--budget", type=int, default=1200)
    p = sub.add_parser("add", parents=[c], help="add agent-found evidence (website, or phone/email/address with --source-url)")
    p.add_argument("id")
    p.add_argument("field", choices=["website", "phone", "email", "address"])
    p.add_argument("value")
    p.add_argument("--source-url", help="page where a phone/email/address was seen (required for those fields)")
    p.add_argument("--note", default="", help='how it was found, e.g. "web search"')
    p = sub.add_parser("images", parents=[c], help="download photos for the best leads")
    p.add_argument("--per-lead", type=int, default=5)
    p.add_argument("--min-px", type=int, default=200)
    p.add_argument("--tiers", default="perfect,agent-approved")
    p.add_argument("--retry-failed", action="store_true")
    p = sub.add_parser("export", parents=[c], help="write the XLSX workbook")
    p.add_argument("path", nargs="?", default=None, help="default: <workdir>/leads.xlsx")
    p.add_argument("--no-thumbs", action="store_true")
    sub.add_parser("stats", parents=[c], help="one-line summary of the current dataset")

    p = sub.add_parser("compete", help="competitor analysis: pricing, tech, content activity, weak spots")
    cs = p.add_subparsers(dest="ccmd", required=True)
    q = cs.add_parser("add", parents=[c], help="add competitor websites")
    q.add_argument("urls", nargs="+")
    q.add_argument("--note", default="")
    q = cs.add_parser("from-leads", parents=[c], help="use verified leads' websites as the competitor set")
    q.add_argument("--tiers", default="perfect,agent-approved")
    q = cs.add_parser("run", parents=[c], help="analyse every competitor site")
    q.add_argument("--render", choices=["never", "auto", "always"], default="auto")
    q.add_argument("--concurrency", type=int, default=6)
    q = cs.add_parser("report", parents=[c], help="compact fact cards for the agent to write the analysis from")
    q.add_argument("--budget", type=int, default=1500)

    p = sub.add_parser("note", parents=[c], help="save an analysis (written by the agent) into the workbook's Analysis sheet")
    p.add_argument("title")
    p.add_argument("body", help="the text, or @path/to/file.md")

    p = sub.add_parser("run", parents=[c], help="discover -> enrich -> verify -> images -> export in one go")
    add_discover(p)
    add_enrich(p)
    add_verify(p)
    p.add_argument("--no-images", action="store_true")
    return ap


def _progress(done: int, total: int) -> None:
    if done == total or done % 10 == 0:
        print(f"  processed {done}/{total}", file=sys.stderr)


def _do_discover(store: Store, a) -> None:
    source = getattr(a, "source", "osm")
    if source in ("gmaps", "both"):
        from .plugins.gmaps import RISK_NOTICE
        if not a.accept_google_tos_risk:
            raise ValueError(RISK_NOTICE)
        if not a.near:
            raise ValueError("--source gmaps needs --near PLACE")
    if source in ("osm", "both"):
        from .discover import discover
        s = discover(store, a.keyword, near=a.near, latlon=a.latlon, radius_m=a.radius, limit=a.limit,
                     osm_tags=a.osm_tag, region=a.region)
        print(f"discover (osm): {s['found']} found near {s['place'][:60]} -> {s['created']} new, "
              f"{s['merged_duplicates']} duplicates merged, {s['skipped_unnamed']} unnamed skipped")
    if source in ("gmaps", "both"):
        import httpx
        from . import USER_AGENT
        from .discover import geocode
        from .plugins.gmaps import discover_gmaps
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as c:
            g = geocode(a.near, c)
        region = a.region or g["region"]
        if region:
            store.set_meta("region", region)
        s = discover_gmaps(store, a.keyword, a.near, limit=a.limit, region=region, center=(g["lat"], g["lon"]),
                           details=not a.gmaps_no_details)
        print(f"discover (gmaps): {s['cards']} results -> {s['created']} new, {s['merged_into_existing']} merged "
              f"into existing leads, {s['skipped']} skipped")


def _do_enrich(store: Store, a) -> None:
    from .enrich import enrich_all
    s = asyncio.run(enrich_all(store, concurrency=a.concurrency, render=a.render, max_pages=a.max_pages,
                               refresh=a.refresh, progress=_progress))
    print(f"enrich: {s['ok']} sites read, {s['unreachable']} unreachable, {s['no_website']} without a website")


def _do_verify(store: Store, a) -> Counter:
    from .verify import verify_all
    counts = verify_all(store, required=tuple(x.strip() for x in a.require.split(",") if x.strip()),
                        min_sources=a.min_sources, min_score=a.min_score, check_dns=not a.no_dns)
    print("verify: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return Counter(counts)


def _do_images(store: Store, per_lead: int, min_px: int, tiers: tuple[str, ...], retry: bool = False) -> None:
    from .images import download_images
    s = asyncio.run(download_images(store, per_lead=per_lead, tiers=tiers, min_px=min_px, retry_failed=retry))
    print(f"images: {s['downloaded']} saved ({s['skipped_small']} too small, {s['duplicates']} duplicates, "
          f"{s['failed']} failed) for {s['leads']} leads")


def _do_export(store: Store, path: str | None, thumbs: bool = True) -> None:
    from .export import export
    s = export(store, path or str(store.workdir / "leads.xlsx"), thumbs=thumbs)
    print(f"export: {s['file']}  (perfect={s['perfect']}, agent-approved={s['agent_approved']}, "
          f"review={s['review']}, needs-data={s['incomplete']}, rejected={s['rejected']})")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "research":
        from .research import main as research_main
        return research_main(argv[1:])
    a = build_parser().parse_args(argv)
    if a.cmd == "doctor":
        from .doctor import run
        return run()

    store = Store(a.workdir)
    try:
        if a.cmd == "discover":
            _do_discover(store, a)
        elif a.cmd == "enrich":
            _do_enrich(store, a)
        elif a.cmd == "verify":
            _do_verify(store, a)
        elif a.cmd == "review":
            from .review import cards
            print(cards(store, a.limit, a.budget))
        elif a.cmd == "show":
            from .review import evidence
            print(evidence(store, a.id, a.budget))
        elif a.cmd == "missing":
            from .review import missing_cards
            print(missing_cards(store, a.limit, a.budget))
        elif a.cmd == "add":
            from .review import add_fact
            v = add_fact(store, a.id, a.field, a.value, a.source_url, a.note)
            print(f"{a.id}: added {a.field} {v}. Next: gruffet enrich && gruffet verify")
        elif a.cmd == "resolve":
            from .review import resolve
            print(f"{a.id} -> {resolve(store, a.id, a.decision, a.reason, a.rename)}")
        elif a.cmd == "images":
            _do_images(store, a.per_lead, a.min_px, tuple(a.tiers.split(",")), a.retry_failed)
        elif a.cmd == "export":
            _do_export(store, a.path, not a.no_thumbs)
        elif a.cmd == "compete":
            from . import compete as cp
            if a.ccmd == "add":
                ids = cp.add_competitors(store, a.urls, a.note)
                print(f"compete: {len(ids)} added. Next: gruffet compete run")
            elif a.ccmd == "from-leads":
                ids = cp.from_leads(store, tuple(a.tiers.split(",")))
                print(f"compete: {len(ids)} competitors taken from leads. Next: gruffet compete run")
            elif a.ccmd == "run":
                s = asyncio.run(cp.analyze_all(store, a.concurrency, a.render, _progress))
                print(f"compete: {s['ok']} analysed, {s['blocked']} blocked automated access, {s['unreachable']} unreachable. "
                      f"Next: gruffet compete report")
            else:
                print(cp.report(store, a.budget))
        elif a.cmd == "note":
            body = a.body
            if body.startswith("@"):
                from pathlib import Path
                body = Path(body[1:]).read_text(encoding="utf-8")
            store.add_note(a.title, body)
            print(f"note saved ({len(body)} chars). It appears in the Analysis sheet on export.")
        elif a.cmd == "stats":
            c = Counter(r["tier"] for r in store.leads())
            print(f"leads={sum(c.values())} " + " ".join(f"{k}={v}" for k, v in sorted(c.items()))
                  + f" competitors={len(store.competitors())} notes={len(store.notes())}")
        elif a.cmd == "run":
            if not (a.near or a.latlon):
                print("error: provide --near or --latlon", file=sys.stderr)
                return 2
            _do_discover(store, a)
            if not store.leads():
                print("error: no businesses found. Try a larger --radius, a different keyword, or an explicit "
                      "--osm-tag KEY=VALUE.", file=sys.stderr)
                return 1
            _do_enrich(store, a)
            counts = _do_verify(store, a)
            if not a.no_images:
                _do_images(store, 5, 200, ("perfect", "agent-approved"))
            _do_export(store, None)
            if counts.get("review"):
                print(f"next: {counts['review']} borderline leads. Run `gruffet review`, judge them, "
                      f"`gruffet resolve`, then `gruffet export` again.")
    except (ValueError, KeyError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
