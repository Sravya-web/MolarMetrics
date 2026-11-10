"""'Ask MolarMetrics' tab: chat with the local model, which calls real tools.

Beginner notes
--------------
* Conversation history lives in ``st.session_state``, which Streamlit keeps
  separately for each browser session, so users never see each other's chats.
* The model is called ONLY when a new question is submitted (chat box or
  example button). Other clicks (downloads, expanders) just redraw the saved
  answers from session state; they never re-run the model.
* Tables and charts come from the tools' structured results, not from the
  model's prose. The tool-activity panel shows exactly what the model sent and
  what it received; there is no hidden reasoning to show.
"""

from __future__ import annotations

import json

import streamlit as st

from molarmetrics.agent.agent import AgentReply, MolarMetricsAgent
from molarmetrics.agent.ollama_status import OllamaStatus
from molarmetrics.ui.components import render_result

PRIORITY_QUESTIONS = [
    "What was billed revenue in 2025?",
    "Compare monthly billed revenue and collections in 2025.",
    "Which five procedures generated the most billed revenue in 2025?",
    "What was the no-show rate by month in 2025?",
    "How much was outstanding as of 31 December 2025?",
]
MORE_QUESTIONS = [
    "Which dentist completed the most appointments in 2025?",
    "How many returning patients were seen in 2025?",
    "Compare root canal and extraction procedure counts in 2025.",
    "Which treatment works best?",
]


@st.cache_resource(show_spinner=False)
def get_agent() -> MolarMetricsAgent:
    """One stateless agent object shared by all sessions (history is passed in per call)."""
    return MolarMetricsAgent()


def _escape_md(text: str) -> str:
    return text.replace("$", r"\$")  # '$' would otherwise start LaTeX in st.markdown


def _render_reply(reply: AgentReply, idx: int, model_name: str) -> None:
    if reply.error:
        st.error(reply.error)
        return
    if reply.answer:
        has_facts = any(a.result is not None and a.result.facts for a in reply.activities)
        st.caption(f":material/smart_toy: **Model commentary** · {model_name}"
                   + (" · may paraphrase; the calculated summary below is authoritative" if has_facts else ""))
        st.markdown(_escape_md(reply.answer))
    if reply.grounding is not None:
        icon = ":material/check_circle:" if reply.grounding.ok else ":material/warning:"
        st.caption(f"{icon} Number check: {reply.grounding.message}")
    for note in reply.notes:
        st.caption(f":material/info: {note}")
    for j, act in enumerate(reply.activities):
        if act.result is not None and act.result.status in ("ok", "empty"):
            render_result(act.result, key=f"msg{idx}_res{j}", table_expanded=False, label_facts=True)
    label = f"Tool activity ({len(reply.activities)} call{'s' if len(reply.activities) != 1 else ''}"
    label += f", {reply.seconds}s)"
    with st.expander(label, icon=":material/build:"):
        if not reply.activities:
            st.write("No tools were called for this reply.")
        for n, act in enumerate(reply.activities, start=1):
            st.markdown(f"**{n}. `{act.name}`**, status: `{act.status}`")
            cols = st.columns(2)
            cols[0].caption("Arguments sent by the model")
            cols[0].json(act.model_args, expanded=True)
            cols[1].caption("Validated arguments used for the calculation")
            cols[1].json(act.result.arguments if act.result else {"note": "not validated (see result)"},
                         expanded=True)
            st.caption("Result returned to the model")
            try:
                st.json(json.loads(act.content), expanded=False)
            except (json.JSONDecodeError, TypeError):
                st.code(act.content or "(empty)", language=None)


def _history_pairs(messages: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for m in messages:
        if m["role"] == "user":
            pairs.append(("user", m["content"]))
        elif m.get("reply") and m["reply"].answer and not m["reply"].error:
            pairs.append(("assistant", m["reply"].answer))
    return pairs


def render_chat(status: OllamaStatus) -> None:
    st.session_state.setdefault("messages", [])
    ready = status.ready

    top = st.columns([5, 1], vertical_alignment="center")
    top[0].markdown("Ask a question in plain English. The local model chooses a tool; Python and SQL "
                    "calculate every number from the synthetic database.")
    if top[1].button("Clear chat", icon=":material/delete:", width="stretch",
                     disabled=not st.session_state["messages"]):
        st.session_state["messages"] = []
    if not ready:
        st.warning(f"Chat is unavailable: {status.message}\n\nThe Dashboard and Data Explorer tabs still work.",
                   icon=":material/cloud_off:")
        st.code("ollama serve          # start the local server (or open the Ollama app)\n"
                f"ollama list           # check that {status.model} is listed", language="bash")

    pending: str | None = None
    with st.expander("Example questions", expanded=not st.session_state["messages"], icon=":material/lightbulb:"):
        st.caption("Priority questions (verified end-to-end against the real local model)")
        cols = st.columns(len(PRIORITY_QUESTIONS))
        for i, q in enumerate(PRIORITY_QUESTIONS):
            if cols[i].button(q, key=f"ex_p{i}", disabled=not ready, width="stretch"):
                pending = q
        st.caption("More examples")
        cols = st.columns(len(MORE_QUESTIONS))
        for i, q in enumerate(MORE_QUESTIONS):
            if cols[i].button(q, key=f"ex_m{i}", disabled=not ready, width="stretch"):
                pending = q

    for idx, message in enumerate(st.session_state["messages"]):
        if message["role"] == "user":
            with st.chat_message("user"):
                st.markdown(_escape_md(message["content"]))
        else:
            with st.chat_message("assistant", avatar=":material/dentistry:"):
                _render_reply(message["reply"], idx, status.model)

    typed = st.chat_input("Ask about appointments, procedures, revenue or payments…", disabled=not ready,
                          key="chat_box", max_chars=500)
    question = (typed or pending or "").strip()
    if not question:
        return
    history = _history_pairs(st.session_state["messages"])
    st.session_state["messages"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(_escape_md(question))
    with st.chat_message("assistant", avatar=":material/dentistry:"):
        with st.spinner("Asking the local model and running analytics tools…"):
            reply = get_agent().ask(question, history=history)
    st.session_state["messages"].append({"role": "assistant", "reply": reply})
    st.rerun()  # redraw everything from session state (no second model call)
