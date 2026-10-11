"""Tests for the opt-in Google Maps plugin.

NOTE: the card dicts below are synthetic (hand-written to mirror the shape the page script returns). They test OUR
parsing and safety guards, not Google's live page, which can change at any time."""
from gruffet import cli
from gruffet.plugins.gmaps import parse_card
from gruffet.store import Store

RAW = {
    "name": "Smile Dental Clinic",
    "href": "https://www.google.com/maps/place/Smile+Dental/data=!4m7!3m6!1s0x0:0x1!8m2!3d53.7974!4d-1.5438",
    "text": "Smile Dental Clinic\n4.8\n(120)\nDentist · 21 Wharf Street, Leeds\nOpen ⋅ Closes 5 pm · 0113 245 8066",
    "links": ["https://www.google.com/maps/place/x", "https://smile-dental.example.org/?utm=maps", "https://www.google.com/aclk"],
    "imgs": ["4.8 stars 120 Reviews"],
}


def test_parse_card_extracts_the_business_fields():
    p = parse_card(RAW, "GB")
    assert p["name"] == "Smile Dental Clinic"
    assert (p["lat"], p["lon"]) == (53.7974, -1.5438)
    assert p["website"] == "https://smile-dental.example.org/?utm=maps"          # first non-Google link
    assert p["phone"] == "+441132458066"
    assert p["rating"] == "4.8 (120 reviews)"
    assert p["category"] == "Dentist" and p["address"] == "21 Wharf Street, Leeds"
    assert p["closed"] is None


def test_parse_card_flags_closed_places_and_skips_nameless_cards():
    closed = dict(RAW, text=RAW["text"] + "\nPermanently closed")
    assert parse_card(closed, "GB")["closed"] == "permanently closed"
    assert parse_card({"name": "", "text": ""}, "GB") is None


def test_fuzzy_merge_joins_the_same_business_across_sources(tmp_path):
    s = Store(tmp_path)
    a, _ = s.upsert_lead("Smile Dental", "dentist", 53.7974, -1.5438, "GB")                      # from OSM
    b, new = s.upsert_lead("Smile Dental Clinic", "dentist", 53.7975, -1.5438, "GB", fuzzy=True)  # from Maps
    assert b == a and not new
    c, new_c = s.upsert_lead("Smile Dental Clinic", "dentist", 53.7975, -1.5438, "GB", fuzzy=False)
    assert new_c and c != a                                                                       # off by default
    d, new_d = s.upsert_lead("Totally Different Vets", "vet", 53.7975, -1.5438, "GB", fuzzy=True)
    assert new_d and d != a                                                                       # nearby but different name


def test_gmaps_refuses_without_the_explicit_risk_flag(tmp_path, capsys):
    rc = cli.main(["discover", "dentist", "--near", "Leeds", "--source", "gmaps", "--workdir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 1 and "--accept-google-tos-risk" in err and "Terms of Service" in err
    assert Store(tmp_path).leads() == []                                                          # nothing was fetched or stored


def test_rating_without_a_review_count_and_detail_page_fields():
    # What the live list view really returned: "4.9 stars" with no review count, and no phone/website.
    card = {"name": "UrgentCare Dental Leeds", "href": "https://www.google.com/maps/place/U/data=!3d53.8!4d-1.5",
            "text": "UrgentCare Dental Leeds\n4.9\nDentist · Unit 2 Ashfield Way", "links": [], "imgs": ["4.9 stars"]}
    p = parse_card(card, "GB")
    assert p["rating"] == "4.9" and p["website"] is None and p["phone"] is None
    # Detail-page fields (data-item-id attributes) fill the gaps and win over guesses.
    card.update(website_detail="https://urgentcare-dental.example.org/", phone_detail="01132458066",
                address_detail="Address: Unit 2 Ashfield Way, Leeds LS12 1AA")
    p = parse_card(card, "GB")
    assert p["website"] == "https://urgentcare-dental.example.org/" and p["phone"] == "+441132458066"
    assert p["address"] == "Unit 2 Ashfield Way, Leeds LS12 1AA"
    # A Google-hosted "website" (e.g. a booking redirect) is not the business website.
    card["website_detail"] = "https://www.google.com/aclk?x=1"
    assert parse_card(card, "GB")["website"] is None
