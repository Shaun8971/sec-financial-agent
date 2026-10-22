# eval_agent.py
# Quiz the agent on questions with known answers, score it automatically, and save the results.
# Run with:  python eval_agent.py
import os
import re
import time
import pandas as pd

from src.agent import run_agent, estimate_cost
from src.analysis import run_sql

NAMES = {"ORCL": "Oracle", "MSFT": "Microsoft", "CRM": "Salesforce", "ADBE": "Adobe", "NOW": "ServiceNow"}


def figure(ticker, year, column):
    # The correct answer, straight from the database.
    # .iloc[0, 0] means "first row, first column" of the result.
    value = run_sql(
        f"SELECT {column} FROM financials WHERE ticker = ? AND fiscal_year = ?", [ticker, year]
    ).iloc[0, 0]
    # Margins are already percentages; dollar amounts get converted to billions
    if column == "operating_margin":
        return value
    return value / 1e9


# ---- The quiz ----
cases = []

# Figures: one revenue question per company, with the answer taken from the database
for ticker in NAMES:
    cases.append({
        "question": f"What was {NAMES[ticker]}'s revenue in fiscal 2024?",
        "type": "figure",
        "expected": figure(ticker, 2024, "revenue"),
    })

cases += [
    {"question": "What was Microsoft's net income in fiscal 2023?",
     "type": "figure", "expected": figure("MSFT", 2023, "net_income")},
    {"question": "What was Adobe's operating margin in fiscal 2024?",
     "type": "figure", "expected": figure("ADBE", 2024, "operating_margin")},
    {"question": "Which of the five companies had the highest revenue in fiscal 2024?",
     "type": "comparison", "expected": "Microsoft"},
    {"question": "What does ServiceNow describe as its main business risks?",
     "type": "filing"},
    {"question": "What drove Oracle's cloud revenue growth in its most recent fiscal year?",
     "type": "filing"},
    {"question": "What was Workday's revenue in fiscal 2024?",
     "type": "out_of_scope"},
    {"question": "What is Microsoft's stock price today?",
     "type": "out_of_scope"},
]


# ---- Scoring ----
def numbers_in(text):
    # Pull every number out of the answer, e.g. "$245.1 billion" gives 245.1.
    # The pattern means: one or more digits, optionally followed by a decimal point and more digits.
    found = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return [float(n) for n in found]


def score(case, answer):
    kind = case["type"]
    lowered = answer.lower()

    if kind == "figure":
        # Pass if any number in the answer is within 1% of the correct value
        expected = case["expected"]
        for n in numbers_in(answer):
            if abs(n - expected) <= 0.01 * abs(expected):
                return True
        return False

    if kind == "comparison":
        return case["expected"].lower() in lowered

    if kind == "filing":
        # Pass if the answer cites at least one chunk, like [chunk 412]
        return re.search(r"\[[A-Z]+ chunk \d+\]", answer) is not None

    if kind == "out_of_scope":
        # Pass if the answer says the data isn't available (a rough check; review failures by hand)
        phrases = ["not available", "don't have", "do not have", "isn't available", "not in",
                   "unable", "doesn't include", "does not include", "only covers", "not covered", 
                   "cannot answer", "cannot", "out of scope", "only covers", "does not include", 
                   "can't"]
        for p in phrases:
            if p in lowered:
                return True
        return False

    return False


# ---- Run the quiz ----
rows = []
for case in cases:
    start = time.perf_counter()
    try:
        answer, trace, usage = run_agent(case["question"])
        error = ""
    except Exception as e:
        answer, trace, error = "", [], str(e)
        usage = {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}
    seconds = time.perf_counter() - start

    passed = score(case, answer) if not error else False
    rows.append({
        "question": case["question"],
        "type": case["type"],
        "passed": passed,
        "seconds": round(seconds, 1),
        "tool_calls": len(trace),
        "model_calls": usage["model_calls"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost_usd": round(estimate_cost(usage), 5),
        "tools_used": ", ".join(t["tool"] for t in trace),
        "answer": answer,
        "error": error,
    })
    print(("PASS  " if passed else "FAIL  ") + case["question"])

# ---- Save and summarize ----
os.makedirs("results", exist_ok=True)
results = pd.DataFrame(rows)
results.to_csv("results/agent_eval.csv", index=False)

print()
print(f"Overall: {results['passed'].sum()} of {len(results)} passed")
print("Pass rate by type (1.0 = all passed):")
print(results.groupby("type")["passed"].mean())
print(f"Median time per question: {results['seconds'].median():.1f} seconds")
print(f"Average cost per question: ${results['cost_usd'].mean():.4f}")
print(f"Average model calls per question: {results['model_calls'].mean():.1f}")
print(f"Total cost of this eval run: ${results['cost_usd'].sum():.4f}")