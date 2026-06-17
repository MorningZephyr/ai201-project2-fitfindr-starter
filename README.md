# FitFindr — Starter Kit

This starter kit contains everything you need to begin Project 2.

## What's Included

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe
├── utils/
│   └── data_loader.py         # Helper functions for loading the data
├── planning.md                # Your planning template — fill this out first
└── requirements.txt           # Python dependencies
```

## Setup

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (get a free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

## The Mock Listings Dataset

`data/listings.json` contains 40 mock secondhand listings across categories (tops, bottoms, outerwear, shoes, accessories) and styles (vintage, y2k, grunge, cottagecore, streetwear, and more).

Each listing has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`.

Load it with:
```python
from utils.data_loader import load_listings
listings = load_listings()
```

## The Wardrobe Schema

`data/wardrobe_schema.json` defines the format your agent uses to represent a user's existing wardrobe. It includes:

- `schema`: field definitions for a wardrobe item
- `example_wardrobe`: a sample wardrobe with 10 items you can use for testing
- `empty_wardrobe`: a starting template for a new user

Load an example wardrobe with:
```python
from utils.data_loader import get_example_wardrobe
wardrobe = get_example_wardrobe()
```

## Tool Inventory

Your README submission must document each tool's name, inputs, and return value. **These must exactly match your actual function signatures in `tools.py`.** Your documented interfaces will be checked against your actual function signatures in `tools.py` — if the parameter count or types contradict what's in the code, you may not receive full credit for that tool.

All three tools live in `tools.py`. Signatures below match the code exactly.

### `search_listings(description, size=None, max_price=None) -> list[dict]`

- **What it does:** Searches the 40 mock listings for items matching a free-text description, optionally filtered by size and a maximum price. Keywords from `description` are matched against each listing's title, description, category, brand, style tags, and colors; results are scored and returned best-first.
- **Inputs:**
  - `description` (`str`): free-text query, e.g. `"vintage graphic tee"`.
  - `size` (`str`, optional, default `None`): loose, case-insensitive size filter (the dataset uses mixed formats like `"M"`, `"W30"`, `"US 8"`).
  - `max_price` (`float`, optional, default `None`): exclude listings priced above this.
- **Returns:** `list[dict]` — copies of matching listings, best match first. Each dict has the standard listing fields (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`) plus an added `match_score` (`int`). Returns `[]` when nothing matches.

### `suggest_outfit(new_item, wardrobe) -> dict`

- **What it does:** Builds a head-to-toe outfit around `new_item` by filling each empty outfit slot (top / bottom / outerwear / shoes / accessory) with the best-matching wardrobe piece, scored on shared style tags and color harmony.
- **Inputs:**
  - `new_item` (`dict`): the listing being styled (needs at least `category`, `style_tags`, `colors`).
  - `wardrobe` (`dict`): wardrobe in schema format — `{"items": [ ... ]}`.
- **Returns:** `dict` with keys `new_item` (dict), `pairings` (`list[dict]`, each a wardrobe item plus a `reason` and `pair_score`), `missing_slots` (`list[str]`), and `notes` (`str`). On a malformed `new_item` it returns the same shape with an extra `error` key and empty `pairings`.

### `create_fit_card(outfit, new_item) -> str`

- **What it does:** Formats the styled outfit into the final, human-readable markdown "fit card" the user sees.
- **Inputs:**
  - `outfit` (`dict`): the dict returned by `suggest_outfit`.
  - `new_item` (`dict`): the featured listing (used for the price/condition/brand/platform header).
- **Returns:** `str` — a multi-line markdown fit card. If `outfit` is empty or incomplete it returns a minimal card noting that styling info was incomplete instead of raising.

---

## How to Run

1. Install dependencies (see **Setup** above) and create a `.env` from `.env.example` with your `GROQ_API_KEY`.
2. Verify the data + tools:
   ```bash
   python utils/data_loader.py   # sanity-check the dataset loads
   python tools.py               # smoke-test the three tools
   pytest -q                     # run the tool tests
   ```
3. Run the agent from the command line:
   ```bash
   python agent.py "vintage graphic tee under $30, I wear baggy jeans and chunky sneakers"
   ```
4. Or launch the web UI:
   ```bash
   python app.py
   ```

**Project files**

| File | Purpose |
|------|---------|
| `tools.py` | The three tools (`search_listings`, `suggest_outfit`, `create_fit_card`). |
| `agent.py` | The `Agent` class: Groq tool-calling planning loop + session state. |
| `app.py` | Gradio chat UI over the agent. |
| `test_tools.py` | Pytest coverage for the tools, including every failure mode. |

---

## Interaction Walkthrough

<!-- Walk through a complete interaction step by step: natural language query → each tool call (and why) → final fit card.
     Walk through this carefully — it's how graders follow your agent's reasoning without a live demo.
     Use a specific example — do not leave this as a template. -->

**User query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Tool called:**
- Tool: `search_listings`
- Input: `description="vintage graphic tee"`, `size=None`, `max_price=30`
- Why this tool: The user is asking what's available, so the agent must first find real listings that match the request and budget before it can style anything.
- Output: A ranked list of matching tops under $30, e.g. `lst_006` "Graphic Tee — 2003 Tour Bootleg Style" ($24, score 3) and `lst_002` "Y2K Baby Tee — Butterfly Print" ($18, score 3), each with a `match_score`. Results are stored in session state (`last_search_results`).

**Step 2 — Tool called:**
- Tool: `suggest_outfit`
- Input: `item_id="lst_006"` (the agent resolves this to the full listing from state) plus the session `wardrobe`
- Why this tool: With a concrete listing chosen, the agent styles it against the user's closet — pairing the tee with bottoms, shoes, and outerwear by matching style tags and colors.
- Output: An outfit dict pairing the tee with `w_001` "Baggy straight-leg jeans" (vibe + denim grounds it), `w_007` "Chunky white sneakers" (streetwear match), and `w_006` "Vintage black denim jacket" (layer); `missing_slots` lists anything the closet couldn't fill; `notes` summarizes the logic. Stored as `last_outfit`.

**Step 3 — Tool called:**
- Tool: `create_fit_card`
- Input: `item_id="lst_006"` (resolved to the listing) and the `last_outfit` dict
- Why this tool: The styling data now needs to be turned into the clean, final deliverable the user actually reads.
- Output: A markdown fit card with the featured tee's price/condition/platform header, a "Pairs with" list (each with a reason), and a closing styling note.

**Final output to user:**

```
FIT CARD — Graphic Tee — 2003 Tour Bootleg Style
$24.00 · good condition · depop

Pairs with (from your closet):
- Baggy straight-leg jeans, dark wash — shares the vintage/streetwear vibe, denim grounds the graphic
- Chunky white sneakers — streetwear staple that matches the vibe
- Vintage black denim jacket — neutral layer that adds structure

Styling note: Keep it tonal and worn-in — tuck the tee loosely into the baggy
jeans and let the sneakers do the talking.
```

---

## Error Handling and Fail Points

<!-- For each tool, describe the specific failure mode and what your agent does in response.
     This maps to the error handling section of the rubric (F5-C1). -->

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No listing matches the query/filters (returns `[]`), or `max_price` is non-numeric. | The tool returns an empty list (never raises) and silently ignores an unparseable budget. The agent detects the empty result and tells the user nothing matched, suggesting they raise the budget, drop the size filter, or try different style words — it does not loop on a dead query. |
| `suggest_outfit` | Wardrobe is empty / no pairings found, or `new_item` is malformed (no `category`). | For an empty wardrobe it returns empty `pairings` with an explanatory `notes`; for a malformed item it returns an `error` key instead of raising. The agent relays that it can't build a full outfit yet and suggests what staple to add. |
| `create_fit_card` | `outfit` is missing required keys / empty, or carries an `error`. | The tool returns a minimal "styling info was incomplete" card (or surfaces the error line) rather than crashing, so the agent can still give the user a coherent response. |

---

## Spec Reflection

<!-- Answer both questions with at least 2–3 sentences each. -->

**One way planning.md helped during implementation:** Writing the four fields for each tool *before* coding locked the function signatures and return shapes early, so `tools.py`, the LLM tool schemas in `agent.py`, and the tests all agreed from the start. In particular, deciding up front that every tool would degrade gracefully (return `[]`, an `error` key, or a minimal card) instead of raising meant the planning loop's error handling was a natural consequence of the spec rather than something bolted on afterward. It also made the README's Tool Inventory trivial to keep consistent with the code.

**One divergence from your spec, and why:** The spec describes `suggest_outfit(new_item, wardrobe)` and `create_fit_card(outfit, new_item)` taking full dicts, and the functions in `tools.py` keep exactly those signatures. But at the *agent* layer I exposed those tools to the LLM with an `item_id` parameter instead of a full listing dict, and the agent resolves the id against `last_search_results` and injects the wardrobe from session state. I diverged because asking a language model to copy an entire listing JSON verbatim between tool calls is error-prone and wastes context; passing a short id and rehydrating from state is more reliable and is exactly what the State Management plan called for. The underlying tool contracts are unchanged.

---

## Where to Start

1. **Read `planning.md` and fill it out before writing any code.**
2. Verify the data loads correctly by running `python utils/data_loader.py`.
3. Build and test each tool individually before connecting them through your planning loop.

Your implementation files go in this same directory. There's no required file structure for your agent code — organize it however makes sense for your design.
