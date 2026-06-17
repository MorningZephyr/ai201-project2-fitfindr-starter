"""
FitFindr — Agent / planning loop.

An `Agent` wraps a Groq LLM in a bounded tool-calling loop. The LLM decides
which of the three tools to call based on the conversation; the agent executes
the tool, feeds the JSON result back, and repeats until the LLM returns a plain
text answer (the fit card / summary).

State (chat history, wardrobe, last search/outfit results) lives on the Agent
instance for the duration of a session.

Run a one-shot demo:
    python agent.py "vintage graphic tee under $30, I wear baggy jeans"
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Optional

from dotenv import load_dotenv

import tools as fit_tools
from utils.data_loader import get_example_wardrobe

load_dotenv()

MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_ITERATIONS = 6

SYSTEM_PROMPT = """You are FitFindr, a secondhand-fashion styling assistant.

Your job: given what the user wants, find a real secondhand listing from the
catalog, style it with pieces from their wardrobe, and present a final fit card.

You have three tools. Use them in this order for a normal request:
  1. search_listings — find candidate listings matching the user's request.
  2. suggest_outfit — pick the SINGLE best listing from the search results and
     style it against the user's wardrobe. Pass the chosen listing's id as
     `item_id` (the wardrobe is supplied automatically).
  3. create_fit_card — turn the outfit into the final card. Pass the same
     `item_id`.

Rules:
- Always search before styling, and style before making a fit card.
- Respect the user's constraints: pass their stated budget as `max_price` and
  their stated size as `size`. Never recommend an item that exceeds the budget
  they gave.
- If search_listings returns no results, do NOT keep retrying blindly and do NOT
  invent or substitute an over-budget item — tell the user nothing matched and
  suggest loosening the budget, size, or style words.
- If the wardrobe is empty or nothing pairs, say so and suggest what to add.
- After create_fit_card returns, present that card to the user in your final
  reply along with one short sentence of friendly context. Keep it concise.
"""


# --- Tool JSON schemas exposed to the LLM ---------------------------------
# Note: suggest_outfit/create_fit_card take an `item_id` here (not a full dict).
# The agent resolves the id against the last search results and injects the
# wardrobe, so the LLM never has to copy large objects around.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_listings",
            "description": "Search secondhand listings by a free-text description, "
                           "with optional size and max price filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Free-text of what to look for, e.g. 'vintage graphic tee'.",
                    },
                    "size": {
                        "type": "string",
                        "description": "Optional size filter, e.g. 'M' or 'W30'.",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Optional maximum price in dollars.",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_outfit",
            "description": "Style a chosen listing against the user's wardrobe. "
                           "Call after search_listings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The `id` of the chosen listing from the search results.",
                    },
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_fit_card",
            "description": "Create the final markdown fit card for a styled listing. "
                           "Call after suggest_outfit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The `id` of the listing that was styled.",
                    },
                },
                "required": ["item_id"],
            },
        },
    },
]


class Agent:
    """A single FitFindr session: holds state and runs the planning loop."""

    def __init__(self, wardrobe: Optional[dict] = None, client: Any = None):
        # Session state
        self.wardrobe: dict = wardrobe if wardrobe is not None else get_example_wardrobe()
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.last_search_results: list[dict] = []
        self.last_outfit: Optional[dict] = None
        self.last_fit_card: Optional[str] = None

        # LLM client (lazy so the tools can be tested without an API key)
        self._client = client

    # -- client ------------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            from groq import Groq

            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "GROQ_API_KEY is not set. Add it to a .env file "
                    "(GROQ_API_KEY=your_key_here). Get a free key at console.groq.com."
                )
            self._client = Groq(api_key=api_key)
        return self._client

    # -- helpers -----------------------------------------------------------
    def _find_listing(self, item_id: str) -> Optional[dict]:
        """Resolve a listing id against the most recent search results."""
        for listing in self.last_search_results:
            if str(listing.get("id")) == str(item_id):
                return listing
        return None

    # -- tool dispatch -----------------------------------------------------
    def _run_tool(self, name: str, args: dict) -> Any:
        """Execute a tool by name, threading session state in and out."""
        if name == "search_listings":
            results = fit_tools.search_listings(
                description=args.get("description", ""),
                size=args.get("size"),
                max_price=args.get("max_price"),
            )
            self.last_search_results = results
            # Return a trimmed view to keep the LLM context small.
            return {
                "count": len(results),
                "results": [
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "category": r["category"],
                        "price": r["price"],
                        "size": r["size"],
                        "condition": r["condition"],
                        "style_tags": r["style_tags"],
                        "colors": r["colors"],
                        "match_score": r["match_score"],
                    }
                    for r in results[:8]
                ],
            }

        if name == "suggest_outfit":
            item = self._find_listing(args.get("item_id", ""))
            if item is None:
                return {"error": f"No listing with id '{args.get('item_id')}' in the "
                                 f"latest search results. Search first, then pass a valid id."}
            outfit = fit_tools.suggest_outfit(item, self.wardrobe)
            self.last_outfit = outfit
            return outfit

        if name == "create_fit_card":
            item = self._find_listing(args.get("item_id", ""))
            outfit = self.last_outfit
            if outfit is None:
                return {"error": "Call suggest_outfit before create_fit_card."}
            if item is None:
                item = outfit.get("new_item", {})
            card = fit_tools.create_fit_card(outfit, item)
            self.last_fit_card = card
            return {"fit_card": card}

        return {"error": f"Unknown tool '{name}'."}

    # -- planning loop -----------------------------------------------------
    def chat(self, user_message: str) -> str:
        """Run one user turn through the bounded tool-calling loop."""
        self.messages.append({"role": "user", "content": user_message})
        self.last_fit_card = None  # reset per turn so we don't show a stale card

        for _ in range(MAX_ITERATIONS):
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=self.messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.4,
            )
            choice = response.choices[0].message

            # Record the assistant turn (content + any tool calls).
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            assistant_msg["content"] = choice.content or ""
            if choice.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in choice.tool_calls
                ]
            self.messages.append(assistant_msg)

            # No tool calls -> the model is done.
            if not choice.tool_calls:
                text = choice.content or ""
                # Always surface the real fit card. The LLM tends to summarize
                # tool output, so append the card it generated this turn if its
                # final text didn't already include it.
                if self.last_fit_card and self.last_fit_card not in text:
                    text = (f"{text}\n\n{self.last_fit_card}" if text.strip()
                            else self.last_fit_card)
                return text

            # Execute each requested tool and feed results back.
            for tc in choice.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._run_tool(tc.function.name, args)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "content": json.dumps(result, default=str),
                    }
                )

        # Loop budget exhausted — return whatever the last fit card / text was.
        if self.last_outfit is not None:
            item = self.last_outfit.get("new_item", {})
            return fit_tools.create_fit_card(self.last_outfit, item)
        return ("I wasn't able to finish styling within the step limit. "
                "Try narrowing your request a bit.")


def _demo(query: str) -> None:
    agent = Agent()
    print(f"User: {query}\n")
    reply = agent.chat(query)
    print("FitFindr:\n")
    print(reply)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or (
        "I'm looking for a vintage graphic tee under $30. I wear baggy jeans "
        "and chunky sneakers. What's out there and how would I style it?"
    )
    _demo(q)
