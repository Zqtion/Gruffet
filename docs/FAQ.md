# Gruffet FAQ — open-source lead research and competitor intelligence

Gruffet is an MIT-licensed Python CLI for **local business discovery**, **public business contact research**, **source-aware verification**, **competitor research**, and **Excel exports**. This page describes the **v0.1.0 early preview**, not the experimental research branch.

**Project:** https://github.com/Zqtion/Gruffet  
**Organization:** https://github.com/Zqtion  
**Early release:** https://github.com/Zqtion/Gruffet/releases/tag/v0.1.0  
**License:** MIT

## What problem does Gruffet solve?

A raw business list usually does not explain where a phone, email, website, or identity claim came from. Gruffet helps builders start with public business data, investigate the business's own site, check available evidence, and produce a workbook that separates supported results from records requiring more review. It is **research assistance**, not a guarantee of contact accuracy, sales interest, or marketing consent.

## Who is Gruffet for?

Independent builders, agencies, sales researchers, AI coding-agent users, and developers who want to investigate **local businesses and competitor websites** using a reproducible Python workflow. It is not a turnkey cloud-based prospecting SaaS or bulk unsolicited-email product.

## How do I install Gruffet?

Install Python 3.10+, then use:

```bash
uv tool install git+https://github.com/Zqtion/Gruffet.git@v0.1.0
gruffet doctor
gruffet run "dentist" --near "Leeds, United Kingdom" --limit 40
```

This runs the local v0.1.0 command-line program and creates a structured workbook under `gruffet-out/`. Source coverage and execution success depend on network and environment.

## Is Gruffet free? Does it require an API key?

Gruffet's code is free and MIT-licensed. The **default** OpenStreetMap and public-website research route does not require a separate paid data or language-model API key. It still needs internet access and is subject to providers' usage policies. External hosting, optional providers, and third-party services can carry costs.

## What sources does it use?

The released local-discovery flow uses OpenStreetMap for geographic business discovery and publicly accessible company web pages for enrichment. OpenStreetMap data has attribution and share-alike considerations under the ODbL; see [third-party notices](../THIRD_PARTY.md). Coverage differs substantially between locations and industries.

## Does Gruffet provide verified emails and phone numbers?

Gruffet attempts to find **published business contact details** and check whether evidence supports them. Its four current verification checks include website availability, identity matching, absence of closure signals, and contact corroboration. A passed check **does not prove** that an address belongs to the correct branch, that a contact currently works, or that the information is suitable for outreach.

## Is Gruffet a lead generator or a full sales platform?

It is a **lead discovery and research** tool. It does not promise high-quality prospects, determine purchase intent, send email campaigns, book meetings, or handle a CRM in v0.1.

## What does the Excel output contain?

The export separates research records, tiers, verification gates, sources, and competitor findings. Users should inspect uncertain records before contacting any company.

## How does competitor research work?

The `gruffet compete` workflow analyzes publicly visible competitor websites for positioning, pricing signals, technologies, and content clues. Some interpretations are heuristics; they should not be stated as validated commercial facts.

## Can I use it with Claude Code, Codex, or Cursor?

Yes, insofar as your shell-capable coding assistant can install or execute the CLI. [Agent instructions](../AGENTS.md) and a [Claude Code skill](../skills/gruffet/SKILL.md) are included. Claude Code is the principal tested workflow; do not infer fully validated support for other assistants.

## Are Agent Reach, Crawl4AI deep research, MCP, and automated contact enrichment released?

**No** for Agent Reach research mode and MCP. Agent Reach/Exa-assisted research and deeper website investigation are experimental in [draft PR #2](https://github.com/Zqtion/Gruffet/pull/2), which is not included in the v0.1.0 release. **Optional Crawl4AI rendering** for JavaScript-heavy sites is available separately in v0.1; this is distinct from the unreleased research mode. MCP, recurring monitoring, and CRM integrations remain roadmap work.

## Does Gruffet scrape Google Maps?

The default route uses OpenStreetMap. The repository includes an experimental opt-in Google Maps browser plugin, but use may conflict with Google's terms. Do not deploy it as a commercial or hosted scraping service.

## Can I use the data for cold outreach?

The presence of a public business email or phone does **not** establish permission to market to that person. Check applicable privacy, consent, direct marketing, website and source-license requirements for your jurisdiction and use case.

## Is Gruffet production-ready?

No. v0.1.0 is an early preview, with offline unit tests and important real-world accuracy limitations. Validate coverage, identity, freshness, legal use, and reliability before making consequential decisions.

## Where can I report bugs or contribute?

- [Issues / feedback](https://github.com/Zqtion/Gruffet/issues)
- [Contribution guide](../CONTRIBUTING.md)
- [Release notes](RELEASE_NOTES_v0.1.0.md)
- [Demo explainer (illustrative, not a live benchmark)](https://github.com/Zqtion/Gruffet/releases/download/v0.1.0/Gruffet_GitHub_Under_10MB.mp4)
