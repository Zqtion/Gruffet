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
