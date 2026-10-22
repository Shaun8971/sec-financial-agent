# src/analysis.py
# SQL helper, per-company figures, and LLM summaries checked against the database.
import json
import duckdb

from src.config import DB_PATH, TICKERS, MODEL, client


def run_sql(sql, params=None):
    # Open the database read-only, run one query, return a pandas table, then close it.
    # 'params or []' means: use the params if given, otherwise an empty list.
    with duckdb.connect(DB_PATH, read_only=True) as con:
        return con.execute(sql, params or []).df()


def get_company_data(ticker):
    # The same query as the notebook, now using run_sql
    df = run_sql("""
        SELECT fiscal_year,
               ROUND(revenue / 1e9, 1)                    AS revenue_b,
               ROUND(operating_income / 1e9, 1)           AS operating_income_b,
               ROUND(net_income / 1e9, 1)                 AS net_income_b,
               ROUND(operating_income / revenue * 100, 1) AS operating_margin_pct,
               ROUND((revenue - LAG(revenue) OVER (ORDER BY fiscal_year))
                     / LAG(revenue) OVER (ORDER BY fiscal_year) * 100, 1) AS revenue_growth_pct
        FROM financials
        WHERE ticker = ?
        ORDER BY fiscal_year
    """, [ticker])
    return df.tail(5)


# ---- Paste SYSTEM_PROMPT, summarize_company, and check_summary from your notebook here ----
# Standing instructions for the summaries: the exact JSON format, plus the grounding rules

SYSTEM_PROMPT = """You are a financial analyst. You will receive a company's annual figures.

Respond with ONLY a JSON object, with no other text before or after it, in exactly this format:
{
  "ticker": "the ticker symbol",
  "revenue_trend": "growing" or "flat" or "declining",
  "latest_revenue_growth_pct": the most recent year's revenue growth, as a number,
  "margin_trend": "expanding" or "stable" or "contracting",
  "summary": "two sentences at most, citing specific numbers",
  "watch_items": ["up to 3 short points worth watching"]
}

Rules:
- Use only the figures provided. Do not use outside knowledge.
- Copy numbers exactly as given. Do not round them differently."""


def summarize_company(ticker):
    # 1. Get the numbers and turn the table into plain text the model can read
    data = get_company_data(ticker)
    data_text = data.to_string(index=False)

    # 2. Send the instructions (system) and the data (user message)
    message = client.messages.create(
        model=MODEL,
        max_tokens=10000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Company: {ticker}\n\nAnnual figures (USD billions and percentages):\n{data_text}",
        }],
    )

    # 3. Collect the reply's text
    text = ""
    for block in message.content:
        if block.type == "text":
            text += block.text

    # 4. Strip ```json markers if the model added them, then turn the JSON text into a dictionary
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def check_summary(result, data):
    # Collect any problems found; an empty list means everything passed
    problems = []

    # Check 1: are all the expected fields present?
    required = {"ticker", "revenue_trend", "latest_revenue_growth_pct",
                "margin_trend", "summary", "watch_items"}
    missing = required - result.keys()
    if missing:
        problems.append(f"Missing fields: {missing}")

    # Check 2: are the category fields one of the allowed choices?
    if result.get("revenue_trend") not in {"growing", "flat", "declining"}:
        problems.append(f"Unexpected revenue_trend: {result.get('revenue_trend')}")
    if result.get("margin_trend") not in {"expanding", "stable", "contracting"}:
        problems.append(f"Unexpected margin_trend: {result.get('margin_trend')}")

    # Check 3: does the model's growth number match our data?
    actual = data["revenue_growth_pct"].iloc[-1]
    reported = result.get("latest_revenue_growth_pct")
    if not isinstance(reported, (int, float)):
        problems.append(f"Growth is not a number: {reported}")
    elif abs(reported - actual) > 0.1:
        problems.append(f"Growth mismatch: model said {reported}, data says {actual}")

    return problems




def summarize_all(path="data/summaries.json"):
    # Your Steps 46 and 47 in one function: summarize, check, and save every company
    all_summaries = []
    for ticker in TICKERS:
        data = get_company_data(ticker)
        result = summarize_company(ticker)
        problems = check_summary(result, data)
        result["checks_passed"] = len(problems) == 0
        result["problems"] = problems
        all_summaries.append(result)

    with open(path, "w") as f:
        json.dump(all_summaries, f, indent=2)
    return all_summaries