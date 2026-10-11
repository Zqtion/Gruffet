# Contributing to Gruffet

Thanks for trying Gruffet. This is an early release, so bug reports and "it didn't work for my search" reports
are as valuable as code.

## Reporting a problem

Open an issue with:

- the command you ran (`gruffet run ...`) and the place and keyword you searched;
- what you expected and what happened (paste the terminal output; redact anything personal);
- your OS and Python version, and the output of `gruffet doctor`.

Please do not paste real people's personal data into issues.

## Running the tests

```bash
git clone https://github.com/t4j44/Gruffet.git && cd Gruffet
uv venv && uv pip install -e ".[dev]"      # or: python -m venv .venv && pip install -e ".[dev]"
pytest
```

The tests need no network and no API keys.

## Ground rules (these keep the project safe to use and to sell around)

1. **Gates must be honest.** A cross-check gate says `unknown` when evidence is missing. It must never say `pass` on a guess.
2. **Pure and tested.** Extractors and gates are pure functions with unit tests; add a test with every behaviour change.
3. **No API keys.** Don't add dependencies that need a paid key. The agent running Gruffet is the only LLM.
4. **Respect the web.** Keep robots.txt handling and rate limits. Do not add ways around CAPTCHAs, bot walls or HTTP 403/429
   responses. A site that refuses automated access is reported as blocked, not worked around.
5. **Business data only in the core.** No scraping of personal social profiles and no guessing of personal email addresses
   in the core. Anything that touches a site's terms (for example the Google Maps plugin) lives under
   `src/gruffet/plugins/`, is opt-in, local-only, and must say so loudly.
6. **Sources stay attached.** Every fact keeps its source and an `EXTRACTED` / `INFERRED` / `AMBIGUOUS` label.

## Pull requests

Small, focused PRs with tests are easiest to review. Run `pytest` first. By contributing you agree your work is
released under the project's MIT license.
