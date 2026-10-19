# Gruffet v0.1.0 — Early Preview

**Status: prerelease for early users and contributors.**

Gruffet is an open-source, locally run Python lead-discovery and competitor-research CLI for coding agents.

## Available in v0.1.0

- Local-business discovery through OpenStreetMap
- Business website enrichment, published contacts, and provenance-labeled evidence
- Rule-based business identity/contact checks and review tiers
- Initial competitor website research
- Excel workbooks with lead tiers, supporting evidence, and review queues
- Optional Crawl4AI browser rendering for JavaScript-heavy websites

## Important limitations

- OpenStreetMap discovery is not suited to every specialized B2B sector and has uneven coverage.
- Agreement between sources does not establish that a business is open, branch-correct, or a qualified buyer.
- The optional Google Maps plugin conflicts with Google scraping restrictions and is not for paid or hosted deployments.
- **Gruffet Research Mode (Agent Reach / Exa, deep people research) remains experimental in draft PR #2 and is not part of this prerelease.**
- Users must comply with privacy, marketing, data source and website-access requirements.

## Install

```bash
uv tool install git+https://github.com/Zqtion/Gruffet.git@v0.1.0
gruffet doctor
gruffet run "dentist" --near "Leeds, United Kingdom" --limit 40
```

The introductory video is a **promotional explainer**, not independent evidence of the tool's live output.

Feedback: https://github.com/Zqtion/Gruffet/issues

Contributing: https://github.com/Zqtion/Gruffet/blob/main/CONTRIBUTING.md

License: MIT
