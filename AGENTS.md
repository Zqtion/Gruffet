# Agent instructions for Gruffet

Gruffet finds and cross-checks business leads with no API keys. **You are the decision layer**: the CLI scrapes
deterministically, you only judge the borderline cases. The same instructions as `skills/gruffet/SKILL.md`, in short:

```
gruffet doctor                                   # probe backends
gruffet run "<keyword>" --near "<place>"          # discover → enrich → verify → images → export
gruffet missing                                  # leads without a website → web-search → gruffet add <id> website <url>
gruffet add <id> phone "<n>" --source-url <page> # contact facts must cite the page they came from
gruffet review --budget 1500                     # compact cards for borderline leads
gruffet resolve <id> accept|reject --reason "…" [--rename "Current Name"]
gruffet export                                   # gruffet-out/leads.xlsx

gruffet discover <kw> --near <place> --source both --accept-google-tos-risk   # opt-in Maps plugin: only if the user accepts the risk
gruffet compete add <url> ...                    # competitors you found by web search (never guess URLs)
gruffet compete run && gruffet compete report    # facts per competitor, compact cards
gruffet note "<title>" "@analysis.md"            # your write-up, from the facts only, into the Analysis sheet
```

Rules: read cards, never raw pages. Never guess a URL. Never accept a lead that failed a hard gate
(`website_alive`, `identity_match`, `not_closed`). `incomplete` = missing data, not a bad business. Business contact
details only: no personal social profiles, no guessed personal emails. Be honest about counts and limits.

## Developing

```
uv venv && uv pip install -e ".[dev]" && pytest
```

- `src/gruffet/`: `discover` (OSM) · `fetch` (robots, cache, optional browser) · `extract` (pure, no LLM) ·
  `enrich` · `verify` (gates → score → tier) · `review` (cards, resolve, add) · `images` · `export` · `cli` ·
  `compete` + `techscan` (pure: tech signatures, weak-spot signals, pricing and sitemap parsing).
- Keep extractors and gates **pure and unit-tested**. A gate must say `unknown` when evidence is missing, never `pass`.
- Do not add API-key dependencies. Do not bypass robots.txt or bot protection (CAPTCHAs, 403 walls). Do not add
  personal-profile scraping to the core. `src/gruffet/plugins/` is opt-in and local-only; keep it out of the default path.

## Research Mode (experimental)

For a user asking an open-ended question or a specialized prospect/decision-maker search, **start with**:

    gruffet research "<the user's exact question>" --plan-only
    gruffet research "<the user's exact question>" --mode auto --limit 10

For professional contacts, add explicit role filters and qualification terms:

    gruffet research "UK immigration law firms handling Skilled Worker visas" \
      --mode prospects --roles "partner,head of immigration" \
      --keywords "Skilled Worker,immigration" --limit 20

Research Mode chooses:
- Agent Reach / Exa via mcporter for specialist company discovery and open-web research (optional, must be configured).
- OSM additionally for supported place-based categories when a location is supplied.
- Existing polite Fetcher with Crawl4AI rendering fallback for deep HTML reading.
- Evidence-first people/role extraction and cited research exports.

**Crucial:** The initial planner is deterministic. You, the coding agent, are the reasoning layer.
If an extraction has insufficient evidence, **do not invent a name, role, URL or email**.
Read research.json and research.md, assess each source and state what remains unverified.
For unsupported social platforms, official directories and paid providers, do not fabricate a connector.
Don't claim an individual is independently verified because a firm webpage says their name.
See [docs/RESEARCH_MODE.md](docs/RESEARCH_MODE.md).