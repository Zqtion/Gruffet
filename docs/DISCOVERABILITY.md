# Gruffet repository search visibility checklist

This is a **maintainer checklist**, not a claim that search engines have indexed Gruffet.

## GitHub repository About metadata

GitHub's About fields are **repository settings**, not README frontmatter. Editing `README.md` alone does not populate the sidebar.

Set these values using the gear icon beside **About** on https://github.com/Zqtion/Gruffet :

**Description** (keep concise):

> Gruffet is an open-source Python CLI for local business discovery, evidence-backed contact research, and competitor intelligence.

**Website**:

> https://www.zqtion.com/

Use the organization site until a dedicated Gruffet landing page is genuinely live. Do not create a dead project URL.

**Topics** (all lowercase, hyphenated, choose up to 20 from GitHub's suggestions):

`lead-generation`, `lead-research`, `business-intelligence`, `competitor-analysis`, `web-research`, `openstreetmap`, `python`, `cli`, `open-source`, `ai-agents`

Do **not** add `mcp-server`, `crm`, `autonomous-agents`, or `agent-reach` as shipped-feature topics unless release capabilities change.

## Search and answer-engine hygiene

1. Keep the exact canonical URL `https://github.com/Zqtion/Gruffet` on the README, releases, Zqtion website, and public posts.
2. On `zqtion.com`, publish a concise, crawlable Gruffet project page with a real one-sentence description, version/status, a screenshot or demo, install example, GitHub canonical link, and the limitations. Add to the public sitemap if the site supports it. Publishing on the domain requires separate website access.
3. Use the same truthful language across sources: **early-preview open-source CLI**; evidence-backed research, **not** guaranteed verified sales leads.
4. Maintain a discoverable [FAQ](FAQ.md) with unambiguous answers for users and search/answer engines; do not claim any search-engine "AI Overview" placement.
5. Add real example output and later reproducible benchmarks once tested. Never use the marketing video's illustrative counts as performance proof.
6. Link from relevant first-party organization profiles and real project announcements. Avoid spam backlinks.
7. After publication, search for `"Gruffet" "Zqtion"` and `site:github.com/Zqtion/Gruffet` periodically. A zero-result search is not definitive proof of deindexing.
8. Do not promise a Google indexing timeline. Crawling, ranking, and knowledge-graph inclusion are outside repository control.

## Release versus unreleased work

- Current: v0.1.0, local business discovery, website enrichment, rule-based checks, reviewed Excel exports, early competitor research.
- Experimental: [research mode PR #2](https://github.com/Zqtion/Gruffet/pull/2).
- Not released: MCP, CRM integrations, automated scheduling, closed-loop deep research.

## Quality before promotion

Before stronger launch claims, run CI and real-location smoke tests, publish a redacted sample workbook, document failure rates and provenance coverage, and explicitly label example/demo footage as illustrative where appropriate.
