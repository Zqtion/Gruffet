"""Research Mode offline tests. Provider calls and page fetches are never live in CI."""
import json
from dataclasses import asdict

import pytest

from gruffet.research import (
    evidence_passages, extract_people, osm_category, page_links,
    parse_reach_urls, plan_query, safe_url, summarize_fit, write_report,
)


def test_intent_routes_specialist_firms_to_search_not_osm():
    p = plan_query("Find UK immigration law firms and their heads of immigration")
    assert p.mode == "prospects"
    assert p.sources == ["agent-reach"]
    assert len(p.searches) == 2


def test_local_firm_near_uses_both():
    p = plan_query("Find dentists", near="Leeds, United Kingdom")
    assert p.mode == "prospects"
    assert p.sources == ["agent-reach", "osm"]
    assert osm_category("Find dentists") == "dentist"


def test_general_research():
    p = plan_query("Explain geothermal energy advantages")
    assert p.mode == "research"
    assert p.sources == ["agent-reach"]
    assert asdict(p)["question"]


def test_override_with_urls():
    p = plan_query("Find companies in Riyadh", source="urls")
    assert p.sources == []


def test_reach_structured_json_and_text():
    output = json.dumps({"content": [{"type": "text", "text": "Result: https://example.org/about"}],
                         "results": [{"url": "https://firm.example/team"}]})
    assert parse_reach_urls(output) == ["https://example.org/about", "https://firm.example/team"]
    assert parse_reach_urls("1. Site (https://example.org) and https://example.org") == ["https://example.org"]


def test_exa_error_is_not_treated_as_search_success():
    with pytest.raises(RuntimeError):
        parse_reach_urls('{"error":"Unknown MCP server exa"}')


def test_nonpublic_urls_blocked():
    assert safe_url("http://localhost/admin") is None
    assert safe_url("http://127.0.0.1/secrets") is None
    assert safe_url("http://192.168.1.10/") is None
    assert safe_url("file:///etc/passwd") is None
    assert safe_url("https://example.com/team") == "https://example.com/team"


def test_internal_links_are_relevant_and_same_domain():
    html = '''<a href="/about/our-team">Our team</a>
              <a href="/contact">Contact us</a>
              <a href="https://external.example/team">External team</a>
              <a href="/privacy">Privacy policy</a>'''
    got = page_links(html, "https://example.org/", max_links=3)
    assert "https://example.org/about/our-team" in got
    assert "https://example.org/contact" in got
    assert all("external.example" not in u for u in got)


def test_person_has_verbatim_same_page_evidence():
    html = "<html><body><p>Jane Smith — Head of Immigration</p><p>General enquiry page.</p></body></html>"
    got = extract_people(html, "https://firm.example/team")
    assert any(p["name"] == "Jane Smith" and p["role"] == "Head of Immigration" for p in got)
    assert any(p["evidence"] == "Jane Smith — Head of Immigration" for p in got)
    assert extract_people("<p>Jane Smith</p><p>Head of Immigration</p>", "https://firm.example") == []


def test_person_role_filter():
    html = "<div><p>Jane Smith, Partner</p><p>John Doe, Director</p></div>"
    got = extract_people(html, "https://example.org", roles=["partner"])
    assert len(got) == 1
    assert got[0]["name"] == "Jane Smith"


def test_extract_relevant_passages_no_invented_quotes():
    html = "<p>Our team handles Skilled Worker visa applications.</p><p>Cookie settings</p>"
    got = evidence_passages(html, "Skilled Worker visa specialist", ["Skilled Worker"])
    assert got == ["Our team handles Skilled Worker visa applications."]


def test_fit_labels_evidence_not_false_confidence():
    p = [{"passages": ["We provide Skilled Worker visa support."]}]
    fit = summarize_fit("Find law firms", p, ["Skilled Worker", "Conveyancing"])
    assert fit["matched"] == ["Skilled Worker"]
    assert fit["unconfirmed"] == ["Conveyancing"]
    assert fit["status"] == "evidence-found"


def test_reports_have_sources(tmp_path):
    report = {
        "plan": {"question": "Find legal professionals", "mode": "prospects"},
        "warnings": [], "results": [{
            "url": "https://firm.example", "status": "researched", "discovery": "provided",
            "fit": {"matched": ["legal"]},
            "people": [{"name": "Jane Smith", "role": "Partner",
                        "evidence": "Jane Smith — Partner",
                        "source_url": "https://firm.example/team"}],
            "contacts": [],
            "pages": [{"url": "https://firm.example/team",
                       "passages": ["Jane Smith — Partner"]}],
        }],
    }
    paths = write_report(report, tmp_path)
    assert "Jane Smith" in (tmp_path / "research.md").read_text(encoding="utf-8")
    assert (tmp_path / "research.xlsx").exists()
    assert json.loads((tmp_path / "research.json").read_text())["results"][0]["url"] == "https://firm.example"


def test_lowercase_words_are_not_accepted_as_people():
    # A role next to an ordinary lower-case phrase must not become a named person.
    html = "<p>our process, director</p><p>Jane Smith — Head of Immigration</p>"
    found = extract_people(html, "https://firm.example/team")
    assert all(p["name"] != "our process" for p in found)
    assert len(found) == 1


def test_research_pipeline_with_mock_search_and_fetcher(monkeypatch, tmp_path):
    """End-to-end research path without network or external AI providers."""
    import asyncio
    from types import SimpleNamespace
    import gruffet.research as research_mod
    from gruffet.store import Store

    html = """<html><body>
      <h1>Immigration Lawyers</h1>
      <a href="/team">Meet our team</a>
      <a href="/privacy">Privacy</a>
      </body></html>"""
    team = """<html><body>
      <p>Jane Smith — Head of Immigration</p>
      <p>Our team supports Skilled Worker visa applications.</p>
      <a href="mailto:info@firm.example">Contact us</a>
      </body></html>"""

    class FakeFetcher:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, url):
            return SimpleNamespace(url=url, final_url=url, status=200, error=None,
                                   rendered=False, ok=True,
                                   html=team if "/team" in url else html)

    monkeypatch.setattr(research_mod, "Fetcher", FakeFetcher)
    monkeypatch.setattr(research_mod, "search_agent_reach",
                        lambda query, limit: ["https://firm.example"])
    plan = plan_query("UK immigration firms", roles="head of immigration",
                      keywords="Skilled Worker")
    db = Store(tmp_path)
    try:
        report = asyncio.run(research_mod.research(plan, db, [], limit=3, max_pages=3))
        assert report["coverage"] == {"targets": 1, "researched": 1, "people": 1}
        item = report["results"][0]
        assert item["people"][0]["name"] == "Jane Smith"
        assert item["people"][0]["source_url"].endswith("/team")
        assert item["fit"]["matched"] == ["Skilled Worker"]
        assert any(c["value"] == "info@firm.example" for c in item["contacts"])
        saved = db.db.execute("SELECT result_json FROM research_history").fetchone()
        assert json.loads(saved[0])["coverage"]["people"] == 1
        assert (tmp_path / "gruffet.db").exists()
    finally:
        db.close()


def test_provider_not_installed_reports_warning_without_inventing_leads(monkeypatch, tmp_path):
    import asyncio
    import gruffet.research as research_mod
    from gruffet.store import Store

    monkeypatch.setattr(research_mod.shutil, "which", lambda name: None)
    plan = plan_query("Find UK law firms")
    db = Store(tmp_path)
    try:
        report = asyncio.run(research_mod.research(plan, db, [], limit=5))
        assert report["coverage"]["researched"] == 0
        assert report["coverage"]["targets"] == 0
        assert any("unavailable" in w.lower() for w in report["warnings"])
    finally:
        db.close()
