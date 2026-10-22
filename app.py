# app.py
# A web interface for the agent. Run locally with:  streamlit run app.py
import os
import time
import streamlit as st

from src.agent import run_agent

st.set_page_config(page_title="EDGAR Analyst", layout="centered")

MAX_QUESTIONS = 20                        # per visitor, to protect your API credits
APP_PASSWORD = os.getenv("APP_PASSWORD")  # from .env locally, or the host's secrets online

# ---- The page's memory for this visitor; it survives every click and redraw ----
if "unlocked" not in st.session_state:
    st.session_state.unlocked = False
if "history" not in st.session_state:
    st.session_state.history = []

# ---- Password gate: nothing below this shows until the password is right ----
if not st.session_state.unlocked:
    st.title("EDGAR Analyst")
    entered = st.text_input("Password", type="password")   # type="password" hides the typing
    if st.button("Enter"):
        # If no password is set at all, stay locked rather than open
        if APP_PASSWORD and entered == APP_PASSWORD:
            st.session_state.unlocked = True
            st.rerun()   # redraw the page, now unlocked
        else:
            st.error("Incorrect password.")
    st.stop()   # stop drawing here until unlocked


def show_trace(trace, seconds):
    # A fold-out section showing which tools the agent used, and with what inputs
    with st.expander(f"How this was answered: {len(trace)} tool calls, {seconds:.1f} seconds"):
        if not trace:
            st.write("Answered without using any tools.")
        for t in trace:
            st.write(f"**Step {t['step']}: {t['tool']}**")
            if t["tool"] == "query_financials":
                st.code(t["input"]["sql"], language="sql")   # show the SQL the agent wrote
            else:
                st.code(t["input"]["query"], language=None)  # show the search phrase


def safe_markdown(text):
    # Streamlit treats text between two $ signs as math formatting, so
    # "$245 billion and $88 billion" would display wrongly. Escaping each $ prevents that.
    return text.replace("$", "\\$")


# ---- Sidebar: description, example questions, and a reset button ----
with st.sidebar:
    st.header("About")
    st.write(
        "Answers questions about five enterprise software companies using SEC data. "
        "Figures come from XBRL filings through SQL; explanations come from each company's "
        "latest 10-K, with citations."
    )
    st.header("Try an example")
    examples = [
        "Which company had the highest operating margin in fiscal 2024?",
        "How did Microsoft's revenue grow from fiscal 2022 to 2024?",
        "What does Oracle describe as its main business risks?",
        "How did Oracle's operating margin change in its most recent fiscal year, and what drove it?",
    ]
    clicked = None
    for example in examples:
        if st.button(example):
            clicked = example
    if st.button("Clear conversation"):
        st.session_state.history = []
        st.rerun()

# ---- Main page ----
st.title("EDGAR Analyst")
st.caption(
    "Covers ORCL, MSFT, CRM, ADBE, and NOW. Each question is answered on its own; "
    "the agent doesn't remember earlier questions."
)

# Redraw the conversation so far (remember: the whole script reruns on every click)
for item in st.session_state.history:
    with st.chat_message("user"):
        st.write(item["question"])
    with st.chat_message("assistant"):
        st.markdown(safe_markdown(item["answer"]))
        show_trace(item["trace"], item["seconds"])

# A new question: typed in the box at the bottom, or clicked from the examples.
# 'typed or clicked' means: use the typed question if there is one, otherwise the clicked one.
typed = st.chat_input("Ask about revenue, margins, growth, or any information from the 10-K's")
question = typed or clicked

if question:
    if len(st.session_state.history) >= MAX_QUESTIONS:
        st.warning("Question limit reached for this session.")
        st.stop()

    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Researching..."):   # a loading indicator while the agent works
            start = time.perf_counter()
            try:
                answer, trace = run_agent(question)
            except Exception as e:
                answer, trace = f"Something went wrong: {e}", []
            seconds = time.perf_counter() - start
        st.markdown(safe_markdown(answer))
        show_trace(trace, seconds)

    # Save this exchange so it's redrawn on the next click
    st.session_state.history.append(
        {"question": question, "answer": answer, "trace": trace, "seconds": seconds}
    )