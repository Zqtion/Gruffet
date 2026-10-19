# Gruffet Research Mode (experimental)

Research Mode is an **early, testable integration**, not a fully autonomous fact-checking AI.
It accepts a question or target prospect description and routes to available sources.

## What actually works

- **Question planning:** deterministic intent detection (research vs prospects). Override with --mode.
- **Agent Reach integration:** optional Exa semantic search via mcporter. Agent Reach is a separate installation; no silent simulated results.
- **Local discovery:** existing OpenStreetMap integration remains available for supported place-based categories.
- **Deep websites:** Gruffet's existing httpx/robots/cache Fetcher crawls the result and prioritized internal pages. It uses **Crawl4AI** rendering when its browser extra is installed and the page requires JavaScript.
- **Research evidence:** exact text snippets; conservative name + professional role co-occurrence with source URL; published business contact methods only.
- **Research memory:** SQLite snapshots and the existing cached HTML reduce repeat fetching.
- **Output:** research.json, research.md, research.xlsx, with a separate evidence sheet.

**Not yet implemented:** general-purpose LLM planner, independent person/role validation against regulators, comprehensive web/PDF parsing, intelligent retry loops, statistical confidence, semantic qualification, real-time changes, scheduling, CRM, and SaaS.

## Install

    uv tool install git+https://github.com/Zqtion/Gruffet.git
    gruffet doctor

For Agent Reach's Exa search, install and configure the upstream tools following:
https://github.com/Panniantong/Agent-Reach/blob/main/docs/install.md

Check configuration:

    agent-reach doctor --json
    mcporter config add exa https://mcp.exa.ai/mcp --scope home
    mcporter call exa.web_search_exa query="test" numResults=1

**Do not assume** an "ok" from Agent Reach doctor proves a working Exa connection;
the actual mcporter test must return valid results. No API keys are required by Gruffet
itself, but external discovery providers may have their own conditions or fees.

For JavaScript rendering (from a clone):

    pip install -e ".[browser]"
    crawl4ai-setup

## Examples

Research a question:

    gruffet research "Compare AI legal research products for UK solicitors" --mode research --limit 8

Find companies and roles:

    gruffet research "UK immigration law firms handling Skilled Worker visas" \
      --mode prospects --roles "partner,head of immigration" \
      --keywords "Skilled Worker,immigration" --limit 20

Local businesses (OSM plus semantic web search, where possible):

    gruffet research "dentists" --near "Leeds, United Kingdom" --limit 10

Use only URLs you already know (works without Exa, useful for offline test fixtures):

    gruffet research "immigration firm partners" --source urls \
      --url https://example.org --plan-only

Preview routing without searching:

    gruffet research "UK immigration law firms" --roles "partner" --plan-only

Use a different work directory to keep projects isolated:

    gruffet research "research question" --workdir ./research-client-a

## How this is different from the older gruffet run command

- gruffet run: business-category discovery by location, then verification gates, images, XLSX.
- gruffet research: semantic search first where available, deep site reads, citations, people/role evidence, JSON/Markdown/XLSX.
- Neither mode should call a prospect "verified" solely because a role appeared once on a website.
- A source quotation is only as trustworthy as its original page; Gruffet records evidence rather than independently guaranteeing the claim.

## Privacy & safety

- Search only legally accessible public sources with appropriate permissions.
- Never use person-level contact guesses or automated unsolicited outreach.
- Each discovered name or contact needs human review for the intended purpose and applicable privacy/marketing laws.
- Research Mode refuses obvious local/private URL targets; **do not deploy it as a public untrusted-URL fetching service** without additional DNS, redirect, and network egress protections.
- The tool runs locally, but any external search provider receives the search query. Review provider terms and privacy protections first.

## Proof required before calling it "better"

Use a manually checked dataset for your target industry, then compare:
- precision of accepted companies and named people
- recall/coverage against the reference set
- cost and minutes per **accepted, qualified** prospect
- source attribution accuracy and false-positive rate
- retrievability of past evidence

No performance gains are claimed until this head-to-head benchmark is run.
