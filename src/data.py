# src/data.py
# Pulls SEC financial data, cleans it, and saves the financials table to DuckDB.
import requests
import pandas as pd
import duckdb

from src.config import SEC_HEADERS, TICKERS, DB_PATH

# Your notebook functions use the name 'headers', so point it at the shared setting
headers = SEC_HEADERS

# Revenue tags in priority order, and the metrics that use a single tag
revenue_tags = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]
METRICS = ["NetIncomeLoss", "OperatingIncomeLoss"]


# ---- Paste get_facts, get_annual, and get_revenue from your notebook here ----
def get_facts(cik):
    padded = str(cik).zfill(10)
    facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json"
    response_company_facts = requests.get(facts_url, headers=headers,timeout=100)
    facts = response_company_facts.json()
    return facts


def get_annual(facts, tag):
    if tag not in facts["facts"]["us-gaap"]:
        return pd.DataFrame(columns = ["end", "fiscal_year", "val"])  # Return an empty DataFrame if the tag is not found
    else:
        usd_list = facts["facts"]["us-gaap"][tag]["units"]["USD"]
        df = pd.DataFrame(usd_list)
        annual = df[(df["form"] == "10-K") & (df["fp"] == "FY")].copy()
        annual["start"] = pd.to_datetime(annual["start"])
        annual["end"] = pd.to_datetime(annual["end"])
        annual["days"] = (annual["end"] - annual["start"]).dt.days
        annual["fiscal_year"] = annual["end"].dt.year
        annual = annual[annual["days"] > 300]
        annual = annual.sort_values("filed").drop_duplicates(subset="end", keep="last")
        return(annual[["end", "fiscal_year","val"]])


def get_revenue(company):
    us_gaap = company["facts"]["us-gaap"]
    tables = []
    for tag in revenue_tags:
        if tag in us_gaap:
            tables.append(get_annual(company, tag))
    revenue = pd.concat(tables)
    revenue = revenue.drop_duplicates(subset="fiscal_year", keep="first")
    return revenue.sort_values("fiscal_year")


def get_ciks(tickers):
    # Look up each ticker's CIK in the SEC's public ticker file
    response = requests.get(
        "https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=10
    )
    response.raise_for_status()   # stop with an error if the request didn't succeed

    ciks = {}
    for entry in response.json().values():
        if entry["ticker"] in tickers:
            ciks[entry["ticker"]] = entry["cik_str"]
    return ciks


def build_financials():
    # Run the whole data layer in one go, and save the result to DuckDB.

    # 1. Look up CIKs, then fetch each company's raw data once
    ciks = get_ciks(TICKERS)
    all_facts = {}
    for ticker, cik in ciks.items():
        all_facts[ticker] = get_facts(cik)

    # 2. Guard: every ticker must hold a different company's data
    names = []
    for company in all_facts.values():
        names.append(company["entityName"])
    assert len(set(names)) == len(names), f"Duplicate company data: {names}"

    # 3. Clean each metric for each company, label it, and collect the tables
    all_tables = []
    for ticker, company in all_facts.items():
        for metric in METRICS:
            table = get_annual(company, metric)
            table["ticker"] = ticker
            table["metric"] = metric
            all_tables.append(table)

        revenue = get_revenue(company)
        revenue["ticker"] = ticker
        revenue["metric"] = "Revenue"
        all_tables.append(revenue)

    # 4. Stack, pivot to one row per company per year, and rename for SQL
    combined = pd.concat(all_tables)
    summary = combined.pivot_table(index=["ticker", "fiscal_year"], columns="metric", values="val")
    summary["OperatingMargin"] = summary["OperatingIncomeLoss"] / summary["Revenue"] * 100

    financials_df = summary.reset_index().rename(columns={
        "NetIncomeLoss": "net_income",
        "OperatingIncomeLoss": "operating_income",
        "Revenue": "revenue",
        "OperatingMargin": "operating_margin",
    })

    # 5. Save to DuckDB. register() gives the pandas table a name SQL can see.
    con = duckdb.connect(DB_PATH)
    con.register("financials_df", financials_df)
    con.execute("CREATE OR REPLACE TABLE financials AS SELECT * FROM financials_df")
    con.close()   # close the file so other parts of the project can open it

    return financials_df
