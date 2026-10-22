# app.py
# A web interface for the agent. Run locally with:  streamlit run app.py
import os
import time
import streamlit as st

from src.agent import run_agent, estimate_cost

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
    entered = st.text_input("Password", type="password")
    if st.button("Enter"):
        if APP_PASSWORD and entered == APP_PASSWORD:
            st.session_state.unlocked = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


def show_trace(trace, seconds, usage):
    # A fold-out section: which tools were used, plus time, tokens, and estimated cost
    cost = estimate_cost(usage)
    title = f"How this was answered: {len(trace)} tool calls, {seconds:.1f} s, ${cost:.4f}"
    with st.expander(title):
        st.caption(
            f"{usage['model_calls']} model calls, "
            f"{usage['input_tokens']:,} tokens in, {usage['output_tokens']:,} tokens out"
        )
        if not trace:
            st.write("Answered without using any tools.")
        for t in trace:
            st.write(f"**Step {t['step']}: {t['tool']}**")
            if t["tool"] == "query_financials":
                st.code(t["input"]["sql"], language="sql")
            else:
                st.code(f"{t['input']['ticker']}: {t['input']['query']}", language=None)


def safe_markdown(text):
    # Escape $ signs so Streamlit doesn't treat figures like "$245 billion" as math formatting
    return text.replace("$", "\\$")


# ---- Sidebar: description, examples, session cost, and reset ----
with st.sidebar:
    st.header("About")
    st.write(
        "Answers questions about five enterprise software companies using SEC data. "
        "Figures come from XBRL filings through SQL; explanations come from each "
        "company's latest 10-K, with citations."
    )
    st.header("Try an example")
    examples = [
        "Which company had the highest operating margin in fiscal 2024?",
        "How did Oracle's operating margin change in its most recent fiscal year, and what drove it?",
        "Compare how Salesforce and ServiceNow describe their AI strategy.",
        "What was Workday's revenue in fiscal 2024?",
    ]
    clicked = None
    for example in examples:
        if st.button(example):
            clicked = example

    # Running total for this visit, so the cost of a session is always visible
    session_cost = 0.0
    for item in st.session_state.history:
        session_cost += estimate_cost(item["usage"])
    st.header("This session")
    st.write(f"{len(st.session_state.history)} questions, estimated cost ${session_cost:.4f}")

    if st.button("Clear conversation"):
        st.session_state.history = []
        st.rerun()

# ---- Main page ----
st.title("EDGAR Analyst")
st.caption(
    "Covers ORCL, MSFT, CRM, ADBE, and NOW. Each question is answered on its own; "
    "the agent doesn't remember earlier questions."
)

for item in st.session_state.history:
    with st.chat_message("user"):
        st.write(item["question"])
    with st.chat_message("assistant"):
        st.markdown(safe_markdown(item["answer"]))
        show_trace(item["trace"], item["seconds"], item["usage"])

typed = st.chat_input("Ask about revenue, margins, growth, or the companies' 10-Ks")
question = typed or clicked

if question:
    if len(st.session_state.history) >= MAX_QUESTIONS:
        st.warning("Question limit reached for this session.")
        st.stop()

    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Researching..."):
            start = time.perf_counter()
            try:
                answer, trace, usage = run_agent(question)
            except Exception as e:
                answer, trace = f"Something went wrong: {e}", []
                usage = {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}
            seconds = time.perf_counter() - start
        st.markdown(safe_markdown(answer))
        show_trace(trace, seconds, usage)

    st.session_state.history.append(
        {"question": question, "answer": answer, "trace": trace,
         "seconds": seconds, "usage": usage}
    )