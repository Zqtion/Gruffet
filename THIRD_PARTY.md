# Third-party projects and credits

Gruffet was **written from scratch**. Its design was informed by reading the public READMEs and file
layouts of the projects below (the source code itself was not copied). Where an idea clearly came from
one of them it is credited here. Licenses are as reported by the GitHub API on 2026-10-09.

| Project | License | What informed Gruffet |
|---|---|---|
| [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) | MIT | Ordered fallback backends per channel; a `doctor` that probes backends for real; shipping a SKILL.md for coding agents; safe-by-default setup; local-only secrets |
| [unclecode/crawl4ai](https://github.com/unclecode/crawl4ai) | Apache-2.0 | Optional browser fallback for JS-only sites (a real dependency via the `browser` extra); deterministic CSS/regex extraction before any LLM; sitemap/URL discovery and caching ideas |
| [ScrapeGraphAI/Scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai) | MIT | Pipeline of separate stages (fetch → clean → extract); structured output; per-call token budgets |
| [ozhehkovski/geoleadscraper](https://github.com/ozhehkovski/geoleadscraper) | MIT | The place-lead field schema; extracting email/phone/social from a business's own website as a separate enrichment step |
| [kiryano/Scout](https://github.com/kiryano/Scout) | MIT | Per-lead confidence scoring and bulk input. **Not adopted:** personal-profile scraping and SMTP-probing of guessed emails |
| [omkarcloud/amazon-scraper](https://github.com/omkarcloud/amazon-scraper) | MIT | Planned: the product/offer/review/bestseller data model for the marketplace module (not yet built) |
| [mahmutovichana/Google-Image-Scraper](https://github.com/mahmutovichana/Google-Image-Scraper) | none (all rights reserved) | **Nothing used.** No license, so it is reference-only; gruffet's image extraction is original and limited to a business's own site |

Also: the EXTRACTED / INFERRED / AMBIGUOUS provenance labels follow the audit-trail idea from the
`graphify` skill.

Runtime dependencies (all permissively licensed): httpx, beautifulsoup4, lxml, dnspython, openpyxl,
phonenumbers, rapidfuzz, tldextract, Pillow. Data: © OpenStreetMap contributors (ODbL); Nominatim and Overpass
public servers are used under their usage policies: low volume, identifying User-Agent, caching.
**If you publish OpenStreetMap-derived data, attribute OpenStreetMap and comply with the ODbL.**
