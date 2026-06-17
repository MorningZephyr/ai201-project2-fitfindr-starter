"""
FitFindr — Tool implementations.

Three deterministic tools the agent's planning loop can call:

    1. search_listings(description, size=None, max_price=None) -> list[dict]
    2. suggest_outfit(new_item, wardrobe)                      -> dict
    3. create_fit_card(outfit, new_item)                       -> str

The tools never raise on "expected" failures (no matches, empty wardrobe,
incomplete outfit). Instead they return empty/explanatory results so the
planning loop can recover and respond to the user gracefully.
"""

from __future__ import annotations

from typing import Optional

from utils.data_loader import load_listings


# Outfit "slots" we try to fill, in display order. The new item fills its own
# slot; the rest are pulled from the wardrobe.
_SLOT_ORDER = ["tops", "bottoms", "outerwear", "shoes", "accessories"]

# Words that aren't useful as search keywords.
_STOPWORDS = {
    "a", "an", "the", "for", "with", "and", "or", "of", "to", "in", "on",
    "i", "im", "i'm", "me", "my", "want", "looking", "look", "some", "something",
    "that", "this", "is", "are", "be", "would", "like", "under", "over",
    "find", "show", "need", "got", "get", "any", "please", "really",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split it into clean alphanumeric keyword tokens."""
    if not text:
        return []
    cleaned = []
    word = []
    for ch in text.lower():
        if ch.isalnum():
            word.append(ch)
        else:
            if word:
                cleaned.append("".join(word))
                word = []
    if word:
        cleaned.append("".join(word))
    return [w for w in cleaned if w and w not in _STOPWORDS]


def _listing_haystack(listing: dict) -> str:
    """Build one searchable lowercase string from a listing's text fields."""
    parts: list[str] = [
        str(listing.get("title", "")),
        str(listing.get("description", "")),
        str(listing.get("category", "")),
        str(listing.get("brand") or ""),
    ]
    parts.extend(str(t) for t in listing.get("style_tags", []) or [])
    parts.extend(str(c) for c in listing.get("colors", []) or [])
    return " ".join(parts).lower()


def search_listings(
    description: str,
    size: Optional[str] = None,
    max_price: Optional[float] = None,
) -> list[dict]:
    """
    Search the mock listings for items matching a free-text description,
    optionally filtered by size and a maximum price.

    Args:
        description: Free-text query, e.g. "vintage graphic tee". Each word
            becomes a keyword matched against the listing's text fields.
        size: Optional size filter (case-insensitive substring match), because
            the dataset uses mixed size formats (e.g. "M", "W30", "US 8").
        max_price: Optional maximum price; listings above it are excluded.

    Returns:
        A list of matching listing dicts (best match first). Each dict is a copy
        of the listing with an added integer `match_score`. Returns [] if nothing
        matches.
    """
    listings = load_listings()
    keywords = _tokenize(description or "")

    # Normalize / validate the price filter without crashing on bad input.
    price_cap: Optional[float] = None
    if max_price is not None:
        try:
            price_cap = float(max_price)
        except (TypeError, ValueError):
            price_cap = None  # ignore an unparseable budget rather than fail

    size_query = size.strip().lower() if isinstance(size, str) and size.strip() else None

    results: list[dict] = []
    for listing in listings:
        # Price filter
        if price_cap is not None:
            try:
                if float(listing.get("price", 0)) > price_cap:
                    continue
            except (TypeError, ValueError):
                pass  # listing with a bad price still shows if it matches text

        # Size filter (loose substring match in either direction)
        if size_query is not None:
            listing_size = str(listing.get("size", "")).lower()
            if size_query not in listing_size and listing_size not in size_query:
                continue

        # Keyword scoring
        if keywords:
            haystack = _listing_haystack(listing)
            score = sum(1 for kw in keywords if kw in haystack)
            if score == 0:
                continue
        else:
            # No keywords given: every listing passing the filters is a result.
            score = 0

        match = dict(listing)
        match["match_score"] = score
        results.append(match)

    # Best score first; tiebreak by lower price for value.
    results.sort(key=lambda r: (-r["match_score"], float(r.get("price", 0))))
    return results


def _color_overlap(colors_a, colors_b) -> bool:
    """True if two color lists share a color (case-insensitive)."""
    a = {str(c).lower() for c in (colors_a or [])}
    b = {str(c).lower() for c in (colors_b or [])}
    return bool(a & b)


# Neutrals pair with anything — used to reward versatile basics.
_NEUTRALS = {"black", "white", "grey", "gray", "charcoal", "cream", "off-white",
             "tan", "beige", "khaki", "navy", "denim", "brown", "indigo"}


def _is_neutral(colors) -> bool:
    return any(str(c).lower() in _NEUTRALS for c in (colors or []))


def _pair_score(new_item: dict, candidate: dict) -> tuple[int, str]:
    """
    Score how well a wardrobe candidate pairs with the new item.
    Returns (score, reason).
    """
    new_tags = {str(t).lower() for t in new_item.get("style_tags", []) or []}
    cand_tags = {str(t).lower() for t in candidate.get("style_tags", []) or []}
    shared = new_tags & cand_tags

    score = 0
    reasons: list[str] = []

    if shared:
        score += 2 * len(shared)
        reasons.append(f"shares the {'/'.join(sorted(shared))} vibe")

    if _color_overlap(new_item.get("colors"), candidate.get("colors")):
        score += 2
        reasons.append("colors tie together")
    elif _is_neutral(candidate.get("colors")):
        score += 1
        reasons.append("neutral that grounds the look")

    if not reasons:
        reasons.append("rounds out the outfit")

    return score, ", ".join(reasons)


def suggest_outfit(new_item: dict, wardrobe: dict) -> dict:
    """
    Build a head-to-toe outfit around `new_item` using pieces from `wardrobe`.

    For every outfit slot the new item does NOT fill, pick the best-matching
    wardrobe item (by shared style tags + color harmony). Slots with no suitable
    wardrobe piece are reported in `missing_slots`.

    Args:
        new_item: The listing being styled (needs at least category, style_tags,
            colors).
        wardrobe: User's wardrobe in schema format: {"items": [ ... ]}.

    Returns:
        {
            "new_item": dict,
            "pairings": [ {<wardrobe item>, "reason": str}, ... ],
            "missing_slots": [str, ...],
            "notes": str,
        }
        On malformed `new_item`, returns {"error": str, ... } with empty pairings.
    """
    if not isinstance(new_item, dict) or not new_item.get("category"):
        return {
            "new_item": new_item if isinstance(new_item, dict) else {},
            "pairings": [],
            "missing_slots": [],
            "notes": "",
            "error": "new_item is missing or has no category, so I can't style it.",
        }

    items = []
    if isinstance(wardrobe, dict):
        items = wardrobe.get("items", []) or []

    new_category = str(new_item.get("category", "")).lower()

    if not items:
        return {
            "new_item": new_item,
            "pairings": [],
            "missing_slots": [s for s in _SLOT_ORDER if s != new_category],
            "notes": "Your wardrobe is empty, so I can't build a full outfit yet. "
                     "Add a few staples (a bottom, shoes) and I'll style around this piece.",
        }

    # Group wardrobe items by category.
    by_category: dict[str, list[dict]] = {}
    for it in items:
        cat = str(it.get("category", "")).lower()
        by_category.setdefault(cat, []).append(it)

    pairings: list[dict] = []
    missing: list[str] = []

    for slot in _SLOT_ORDER:
        if slot == new_category:
            continue  # the new item already fills this slot
        candidates = by_category.get(slot, [])
        if not candidates:
            missing.append(slot)
            continue
        # Pick the highest-scoring candidate for this slot.
        scored = [(*_pair_score(new_item, c), c) for c in candidates]
        scored.sort(key=lambda x: -x[0])
        best_score, best_reason, best_item = scored[0]
        entry = dict(best_item)
        entry["reason"] = best_reason
        entry["pair_score"] = best_score
        pairings.append(entry)

    if pairings:
        notes = (f"Styled around the {new_item.get('title', new_item.get('name', 'new piece'))} "
                 f"by matching style tags and colors from your closet.")
    else:
        notes = ("I couldn't find wardrobe pieces that pair well with this item. "
                 "Try adding more staples in other categories.")

    return {
        "new_item": new_item,
        "pairings": pairings,
        "missing_slots": missing,
        "notes": notes,
    }


def create_fit_card(outfit: dict, new_item: dict) -> str:
    """
    Format a styled outfit into a human-readable markdown "fit card".

    Args:
        outfit: The dict returned by suggest_outfit (new_item, pairings,
            missing_slots, notes).
        new_item: The featured listing (used for price/condition/platform header).

    Returns:
        A multi-line markdown string. If the outfit is missing/incomplete, returns
        a minimal card explaining that styling info was incomplete instead of
        raising.
    """
    if not isinstance(new_item, dict) or not new_item:
        # Fall back to whatever the outfit carried.
        new_item = (outfit or {}).get("new_item", {}) if isinstance(outfit, dict) else {}

    title = new_item.get("title") or new_item.get("name") or "Featured piece"

    lines: list[str] = []
    lines.append(f"**FIT CARD — {title}**")

    # Header meta line (price · condition · platform), omitting missing fields.
    meta: list[str] = []
    price = new_item.get("price")
    if isinstance(price, (int, float)):
        meta.append(f"${price:.2f}")
    if new_item.get("condition"):
        meta.append(f"{new_item['condition']} condition")
    if new_item.get("brand"):
        meta.append(str(new_item["brand"]))
    if new_item.get("platform"):
        meta.append(str(new_item["platform"]))
    if meta:
        lines.append(" · ".join(meta))

    if not isinstance(outfit, dict) or not outfit:
        lines.append("")
        lines.append("_Styling info was incomplete, so here's just the piece itself._")
        return "\n".join(lines)

    if outfit.get("error"):
        lines.append("")
        lines.append(f"_{outfit['error']}_")
        return "\n".join(lines)

    pairings = outfit.get("pairings", []) or []
    if pairings:
        lines.append("")
        lines.append("**Pairs with (from your closet):**")
        for p in pairings:
            name = p.get("name") or p.get("title") or "item"
            reason = p.get("reason")
            if reason:
                lines.append(f"- {name} — {reason}")
            else:
                lines.append(f"- {name}")
    else:
        lines.append("")
        lines.append("_No closet pieces paired with this yet._")

    missing = outfit.get("missing_slots", []) or []
    if missing:
        lines.append("")
        lines.append(f"**To complete the look, consider adding:** {', '.join(missing)}")

    notes = outfit.get("notes")
    if notes:
        lines.append("")
        lines.append(f"**Styling note:** {notes}")

    return "\n".join(lines)


# --- Quick manual smoke test ---
if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe

    found = search_listings("vintage graphic tee", max_price=30)
    print(f"search_listings -> {len(found)} results")
    if found:
        top = found[0]
        print(f"  top match: {top['title']} (${top['price']}, score {top['match_score']})")
        outfit = suggest_outfit(top, get_example_wardrobe())
        print(f"suggest_outfit -> {len(outfit['pairings'])} pairings, "
              f"missing {outfit['missing_slots']}")
        print("\n" + create_fit_card(outfit, top))
