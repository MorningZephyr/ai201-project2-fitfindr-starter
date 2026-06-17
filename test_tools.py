"""
Tests for the three FitFindr tools.

These cover the happy path plus each documented failure mode (no matches,
empty wardrobe, incomplete outfit). No API key is required — the tools are
deterministic.

Run:
    pytest -q
"""

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# --- search_listings ------------------------------------------------------

def test_search_returns_matches_sorted_by_score():
    results = search_listings("vintage graphic tee")
    assert len(results) > 0
    # Every result has a match_score and they are sorted best-first.
    scores = [r["match_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all("match_score" in r for r in results)


def test_search_respects_max_price():
    results = search_listings("jacket", max_price=40)
    assert all(r["price"] <= 40 for r in results)
    assert len(results) > 0


def test_search_respects_size_filter():
    results = search_listings("tee", size="L")
    assert all("l" in str(r["size"]).lower() for r in results)


def test_search_no_match_returns_empty_list():
    # A nonsense keyword with no possible match.
    assert search_listings("zzzqqqwxyz") == []


def test_search_invalid_max_price_is_ignored_not_crash():
    results = search_listings("tee", max_price="not-a-number")  # type: ignore[arg-type]
    assert isinstance(results, list)
    assert len(results) > 0


# --- suggest_outfit -------------------------------------------------------

def test_suggest_outfit_fills_slots():
    item = search_listings("vintage graphic tee", max_price=30)[0]
    outfit = suggest_outfit(item, get_example_wardrobe())
    assert outfit["new_item"]["id"] == item["id"]
    assert len(outfit["pairings"]) > 0
    # The new item's own category should not appear as a missing slot.
    assert item["category"] not in outfit["missing_slots"]
    for p in outfit["pairings"]:
        assert p.get("reason")


def test_suggest_outfit_empty_wardrobe():
    item = search_listings("vintage graphic tee")[0]
    outfit = suggest_outfit(item, get_empty_wardrobe())
    assert outfit["pairings"] == []
    assert "empty" in outfit["notes"].lower()


def test_suggest_outfit_malformed_item():
    outfit = suggest_outfit({"title": "no category"}, get_example_wardrobe())
    assert "error" in outfit
    assert outfit["pairings"] == []


# --- create_fit_card ------------------------------------------------------

def test_create_fit_card_happy_path():
    item = search_listings("denim jacket", max_price=45)[0]
    outfit = suggest_outfit(item, get_example_wardrobe())
    card = create_fit_card(outfit, item)
    assert isinstance(card, str)
    assert "FIT CARD" in card
    assert item["title"] in card
    assert "Pairs with" in card


def test_create_fit_card_incomplete_outfit_does_not_crash():
    item = search_listings("tee")[0]
    card = create_fit_card({}, item)
    assert isinstance(card, str)
    assert "incomplete" in card.lower()


def test_create_fit_card_with_error_outfit():
    outfit = suggest_outfit({"title": "no category"}, get_example_wardrobe())
    card = create_fit_card(outfit, {})
    assert isinstance(card, str)
    assert "FIT CARD" in card
