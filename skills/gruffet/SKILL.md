---
name: gruffet
description: Find and verify business leads (and basic market snapshots) for free with no API keys. Use when the user wants leads, a prospect list, local-business research, contact details with photos, or an Excel report of businesses in an area. Cross-checks every contact against independent sources and only exports verified leads. Runs the `gruffet` CLI.
---

# gruffet

You are the decision layer. The CLI does the scraping with no LLM; you only judge the few borderline leads.
**Never read raw pages or whole result files. Use the cards.**

## Workflow

1. `gruffet doctor` (once per session). If Nominatim/Overpass are failing, say so; do not invent data.
2. `gruffet discover "<keyword>" --near "<place>" --radius <m>` then `gruffet enrich` then `gruffet verify`
   (or `gruffet run ...` for all of it). Keep `--limit` small first (40-200).
3. `gruffet missing` lists leads with no website. For each (batch them), **web-search** for the official site.
   - Only `gruffet add <id> website <url> --note "web search"` if the result is clearly the business at that address.
   - **Never guess or construct a URL.** If you can't find it, leave the lead alone.
   - To add a phone/email/address you found, you MUST cite the page: `gruffet add <id> phone "<n>" --source-url <page>`.
     A different page than the business's own site counts as an independent source during cross-checking.
4. `gruffet enrich && gruffet verify` again after adding evidence.
5. `gruffet review --budget 1500`. Judge each card:
   - `accept` only if the evidence in the card shows it is the right business and the contact is credible.
   - If the site shows a different name for the same premises/phone, `accept ... --rename "<current name>"`.
   - `reject` with a short reason if it looks wrong, closed, or not a real business.
   - Unsure? Leave it in the queue. Do not guess. `gruffet show <id> --budget 800` gives the full evidence.
   - Command: `gruffet resolve <id> accept|reject --reason "<one line>"`
6. `gruffet images` (best leads only), then `gruffet export`. Report the counts per tier and the file path.

## Google Maps plugin (only if the user asks for it)

`--source gmaps|both` needs `--accept-google-tos-risk`. Only add that flag if the user has explicitly said they accept
Google's terms risk for local use. Tell them it is against Google's terms, never use it for a hosted or paid product, and
don't redistribute the data. If it reports that Google asked for human verification, **stop**: do not retry in a loop,
do not look for ways around it; suggest waiting or using the default OSM source.

## Competitor analysis

Use when the user wants to compare rivals, size up a local market, or find gaps.

1. Find the competitor sites yourself with web search (e.g. "alternatives to X", "best <category> in <city>").
   Only add sites you actually found: `gruffet compete add <url> <url> ...`. Never construct a URL.
   For a local market, `gruffet compete from-leads` uses the verified leads' websites instead.
2. `gruffet compete run`, then `gruffet compete report --budget 1500` and read only those cards.
3. Write the comparison **from the card facts only** (positioning, pricing, tech, content activity, gaps), and label
   anything speculative as a hypothesis. Pricing and weak-spot signals are heuristics: check the source page before
   quoting a number. A *blocked* competitor was not analysed: say so, don't fill the gap with guesses.
4. Save it: `gruffet note "<title>" "@file.md"` (same title replaces the old one), then `gruffet export`.

## Rules

- A lead that failed a hard gate (`website_alive`, `identity_match`, `not_closed`) cannot be accepted. Don't try to work around it.
- `incomplete` means *missing data*, not a bad business. Say that when summarising.
- Be honest in the summary: how many perfect / agent-approved / still unresolved, and the main limits
  (OpenStreetMap coverage, sites that blocked automated access).
- Collect business contact details only. Do not scrape personal social profiles or guess personal email addresses.
- Remind the user that outreach must follow local marketing and privacy law, and that images belong to their owners.

## Reading results cheaply

`gruffet stats` (one line) · `gruffet review --limit 10 --budget 800` · `gruffet show <id> --budget 600`.
Output goes to `./gruffet-out/` (override with `--workdir` or `GRUFFET_DIR`).
