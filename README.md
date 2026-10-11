# Gruffet

Free, keyless, **cross-checked** lead generation and market research for coding agents.
It runs inside Claude Code, Codex, Cursor or Antigravity. There are no API keys: the agent you
already use is the LLM, and the scraping itself is deterministic, so it costs almost no tokens.

```
leads:        discover → enrich → verify → (agent reviews borderline leads) → images ─┐
competitors:  add sites → analyse (pricing, tech, content, weak spots) → agent writes analysis ─┴→ one .xlsx
```

> **Status: v0.1, early.** The lead pipeline and a first competitor-analysis module work end to end and are tested (see
> [What works today](#what-works-today) and [Not built yet](#not-built-yet)). Please read the
> [limits](#honest-limits) before relying on the output.

## Why it is different

Most scrapers return whatever they found. Gruffet treats every fact as a **claim** with a source and
a label (`EXTRACTED` / `INFERRED` / `AMBIGUOUS`, the same audit-trail idea as graphify), then only
calls a lead **perfect** when independent sources agree:

| Gate | Passes when |
|---|---|
| `website_alive` | the listed website answers, and is not a parked / for-sale page |
| `identity_match` | the site is really this business (name match, or the OSM phone is also on the site) |
| `not_closed` | no "permanently closed" signal anywhere |
| `contact_corroborated` | a phone is confirmed by 2+ independent sources (OSM, the business's own site, or an external page the agent cites), **or** an email has working mail servers and ties to the site |

Anything that is not clearly good or bad goes to a small queue of **review cards** (~100 tokens each)
that your agent judges. Everything else is decided by code. Tiers:

`perfect` · `agent-approved` · `review` · `incomplete` (no contact data yet; missing data, *not* a bad lead) · `reject`

A hard-failed lead (dead site, wrong business, closed) can never be "accepted" by the agent.

## Install

Needs Python 3.10+. Quickest (installs the `gruffet` command):

```bash
uv tool install git+https://github.com/t4j44/Gruffet.git     # or: pip install git+https://github.com/t4j44/Gruffet.git
gruffet doctor                                                # probes every backend for real
gruffet run "dentist" --near "Leeds, United Kingdom" --limit 40
```

Or from a clone (for development):

```bash
git clone https://github.com/t4j44/Gruffet.git && cd Gruffet
uv venv && uv pip install -e ".[dev]"      # or: python -m venv .venv && pip install -e ".[dev]"
pytest
```

Optional, for JavaScript-only sites: `pip install -e ".[browser]" && crawl4ai-setup` (uses Crawl4AI's browser).

## Use

One command:

```bash
gruffet run "dentist" --near "Leeds, United Kingdom" --radius 2500 --limit 40
```

Or step by step, which is how an agent should drive it:

```bash
gruffet discover "travel agency" --near "Dhaka, Bangladesh" --radius 4000   # OpenStreetMap, no key
gruffet enrich                    # reads each lead's own website (robots.txt respected)
gruffet verify                    # gates → score → tier
gruffet missing                   # leads with no website → agent web-searches → `gruffet add`
gruffet review --budget 1500      # compact cards for borderline leads
gruffet resolve <id> accept --reason "…" [--rename "Current Name"]
gruffet images                    # photos for the best leads (source URLs recorded)
gruffet export                    # → gruffet-out/leads.xlsx
```

### Optional: Google Maps plugin (local only, against Google's terms)

```bash
pip install -e ".[browser]" && crawl4ai-setup          # one-time: the plugin drives a real browser
gruffet discover dentist --near "Leeds, United Kingdom" --source gmaps --accept-google-tos-risk --limit 20
gruffet discover dentist --near "Leeds, United Kingdom" --source both --accept-google-tos-risk   # OSM + Maps, merged
```

Read this before using it:

- **Google's Terms of Service restrict scraping Maps and Google may block you.** You run it on your own machine and
  accept that risk. It is refused unless you pass `--accept-google-tos-risk`.
- **Never use it inside a hosted or paid product, and don't redistribute Google-derived data.** Keep it out of anything you sell.
- It is deliberately gentle: one browser, one search, slow scrolling, a hard cap of 120 results, about one extra request
  per place (to read the website and phone from the place page; `--gmaps-no-details` skips that).
- **If Google shows a CAPTCHA or "unusual traffic" page it stops and says so. It will not try to get past it.**
  Cookie banners get the privacy-preserving answer (reject non-essential).
- It parses a live page, so it can break whenever Google changes its layout.

Maps adds a second independent source, so more leads clear the cross-checks. In one live run (10 results, Leeds dentists)
perfect leads rose from 2 to 10, each backed by a phone confirmed on both the Maps listing and the business's own site.

Competitor analysis (any websites: SaaS rivals, local competitors, or your verified leads as a market):

```bash
gruffet compete add https://rival-one.com https://rival-two.com   # your agent finds these by web search
gruffet compete from-leads        # or: use the verified leads' websites as the market
gruffet compete run               # positioning, pricing, tech stack, sitemap activity, weak spots
gruffet compete report            # compact fact cards (~250 tokens per competitor) for the agent
gruffet note "Comparison" "@analysis.md"   # the agent's write-up, saved into the workbook
gruffet export
```

Every competitor fact keeps its source and an `EXTRACTED` / `INFERRED` label. Pricing and weak-spot signals are heuristics:
check the source page before quoting a number. Sites that refuse automated access are marked *blocked* and left alone.

The workbook has: **Perfect Leads** (with photo thumbnails), Review Queue, Needs Data, Rejected,
**Gate Matrix** (every gate, colour-coded, with the reason in a cell comment), **Evidence** (every claim
with its source and label), Images, **Competitors** + Competitor Evidence, **Analysis** (the agent's written
conclusions), Market Snapshot, Run Log, About. Perfect Leads also shows each site's tech stack and weak spots
(no HTTPS, no mobile viewport, no analytics, stale copyright), handy for web and marketing agencies.

## Using it from an agent

- **Claude Code:** copy `skills/gruffet/` to `.claude/skills/gruffet/` (project) or `~/.claude/skills/` (global).
- **Codex / Cursor / others:** [`AGENTS.md`](AGENTS.md) has the same instructions; most agents read it automatically.
  Antigravity support is untested; if it reads `AGENTS.md` it should work, and the CLI is the same everywhere.

The rules the agent follows are in the skill: read cards, not pages; never guess a URL; cite a source for every
phone/email it adds; never override a failed hard gate.

## What works today

Verified on a live run (dentists within 2.5 km of central Leeds, UK, 40 requested):

- 15 businesses found on OpenStreetMap → **2 perfect**, 1 agent-approved, 1 review, 11 needs-data.
- Only 3 of 15 had a website in OSM; the rest need the `missing` → web-search → `add` loop.
- The gates caught a real problem: a listed practice whose website now says a different name
  (renamed/taken over). A naive scraper would have exported it as perfect under the stale name.
  The agent accepted it with `--rename` after checking the evidence.
- **Competitor analysis** was run live on three real lead-data vendors: two analysed (positioning, pricing, tech stack,
  sitemap size, social links), one correctly reported as *blocked* (HTTP 403) and left alone. The run exposed and fixed
  a price-to-plan misattribution and misleading sitemap "freshness" numbers.
- **Google Maps plugin** was run live on a small search (details above). The first version returned only names and
  addresses because Google's list cards don't show phone or website; reading each place page fixed that. The card parsing
  is unit-tested on hand-written samples, not on Google's live page.
- 41 unit tests cover extraction (JSON-LD, `mailto:`, Cloudflare-obfuscated emails, `[at]` forms, socials,
  images, JS-app detection), the gates, duplicate merging, renames, tech/pricing/sitemap parsing, and the XLSX export.
  The optional browser fallback (Crawl4AI) was checked against a JavaScript-only page and a static page.

## Not built yet

Roadmap, in order. None of this exists yet:

1. **Second independent source** (Overture Maps / Wikidata) so more leads can reach "perfect" without the agent.
2. **Competitor analysis, deeper**: re-run and diff over time, review aggregation, ad-library signals.
3. **Marketplace/product module** (Amazon-style: product, offers, reviews, bestsellers).
4. **More opt-in local plugins**, off by default and never part of any hosted service: social *business pages* through
   [Agent Reach](https://github.com/Panniantong/Agent-Reach), which needs *your* logged-in browser session. Personal
   profiles stay out. (The Google Maps plugin already exists; see above.)
5. **MCP server**, scheduled refreshes, CRM export, and a one-line installer for the skill.

## Honest limits

- **Coverage = OpenStreetMap coverage.** Sparse areas give sparse results, and many entries have no phone or website.
- **"Perfect" means precision over recall.** It proves two independent sources agree. It does not prove the business is good, open today, or that the contact is the right person. Absence of a closure signal is not proof of being open.
- **Generic names** ("Dental Clinic") can fuzzy-match the wrong site. The shared-phone check is the strong signal.
- **Addresses are not cross-checked yet.** A chain or multi-branch business can pass with a phone that belongs to a
  different branch. Check the address column before outreach.
- **Sites that refuse automated access** (HTTP 403/429, bot walls) are reported as "unknown" or "blocked", never rejected, and Gruffet does not try to get around them. Check those by hand. The optional browser mode is only for pages that need JavaScript to show their content.
- **Public OSM servers are shared** and sometimes overloaded; discovery retries across mirrors and fails loudly rather than returning an empty list.
- **Trust/chain sites** list organisation-wide inboxes; those aren't leads for outreach.
- **Images belong to their owners.** Gruffet records source URL and page for each image; don't republish without permission.
- **You are responsible for lawful use**: honour robots.txt (done automatically), site terms, and marketing/privacy law
  (GDPR, PECR, CAN-SPAM, etc.) when contacting anyone. Gruffet only collects *business* contact details published by the
  business itself and deliberately does not scrape personal social profiles or guess personal email addresses.

## Credits

Design drew on seven open-source projects; see [`THIRD_PARTY.md`](THIRD_PARTY.md). MIT licensed.

## Feedback and contributing

This is an early release and real-world feedback is the most useful thing you can give it. Please
[open an issue](https://github.com/t4j44/Gruffet/issues) with what you searched for, what worked, and what didn't
(redact any personal data). See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to run the tests and the project's ground rules.
