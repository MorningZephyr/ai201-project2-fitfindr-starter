"""
FitFindr — Gradio chat UI.

A simple web front-end over the Agent planning loop. Each browser session gets
its own Agent (its own state), so the wardrobe and conversation persist across
turns within a session.

Run:
    python app.py
then open the printed local URL.
"""

from __future__ import annotations

import os

import gradio as gr
from dotenv import load_dotenv

from agent import Agent
from utils.data_loader import get_example_wardrobe

load_dotenv()


EXAMPLES = [
    "I'm looking for a vintage graphic tee under $30. I wear baggy jeans and chunky sneakers. What's out there and how would I style it?",
    "Find me cozy cottagecore knitwear under $40 and style it.",
    "I want some y2k platform shoes. How would I wear them?",
    "Show me a denim jacket under $45 and build an outfit around it.",
]


def _wardrobe_markdown(wardrobe: dict) -> str:
    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []
    if not items:
        return "_Your wardrobe is empty._"
    lines = ["**Your wardrobe (used for styling):**"]
    for it in items:
        lines.append(f"- {it.get('name', 'item')} ({it.get('category', '?')})")
    return "\n".join(lines)


def respond(message: str, history: list, state: dict):
    """Gradio chat handler. `state` carries the per-session Agent."""
    agent: Agent = state.get("agent")
    if agent is None:
        agent = Agent(wardrobe=get_example_wardrobe())
        state["agent"] = agent

    if not message or not message.strip():
        return history, state, ""

    history = history + [{"role": "user", "content": message}]
    try:
        reply = agent.chat(message)
    except RuntimeError as e:
        # Most likely a missing GROQ_API_KEY.
        reply = f"Configuration error: {e}"
    except Exception as e:  # noqa: BLE001 - surface any runtime error to the UI
        reply = f"Something went wrong: {e}"

    history = history + [{"role": "assistant", "content": reply}]
    return history, state, ""


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="FitFindr", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# FitFindr\n"
            "Tell me what secondhand piece you're after and how you dress — "
            "I'll find a listing, style it with your closet, and make a fit card."
        )

        session = gr.State({"agent": None})

        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(type="messages", height=460, label="FitFindr")
                msg = gr.Textbox(
                    placeholder="e.g. vintage graphic tee under $30, I wear baggy jeans...",
                    label="Your request",
                    autofocus=True,
                )
                with gr.Row():
                    send = gr.Button("Send", variant="primary")
                    clear = gr.Button("Reset session")
                gr.Examples(examples=EXAMPLES, inputs=msg, label="Try one")
            with gr.Column(scale=1):
                gr.Markdown(_wardrobe_markdown(get_example_wardrobe()))

        if not os.getenv("GROQ_API_KEY"):
            gr.Markdown(
                "> **Heads up:** `GROQ_API_KEY` isn't set. Add it to a `.env` file "
                "to enable the assistant. Get a free key at console.groq.com."
            )

        send.click(respond, [msg, chatbot, session], [chatbot, session, msg])
        msg.submit(respond, [msg, chatbot, session], [chatbot, session, msg])

        def _reset():
            return [], {"agent": None}, ""

        clear.click(_reset, outputs=[chatbot, session, msg])

    return demo


if __name__ == "__main__":
    build_ui().launch()
