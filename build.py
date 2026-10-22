# build.py
# Rebuild every generated file from scratch with one command:  python build.py
from src.config import TICKERS
from src.data import build_financials, get_ciks
from src.rag import download_10k_text, build_index
from src.analysis import summarize_all

print("1/4 Building the financials table from SEC data...")
financials = build_financials()
print(f"    {len(financials)} company-year rows saved")

print("2/4 Downloading each company's latest 10-K...")
ciks = get_ciks(TICKERS)
for ticker in TICKERS:
    text = download_10k_text(ticker, ciks[ticker])
    print(f"    {ticker}: {len(text):,} characters")

print("3/4 Indexing all 10-Ks for search (this takes a few minutes)...")
count = build_index()
print(f"    {count:,} chunks indexed")

print("4/4 Generating and checking LLM summaries...")
summaries = summarize_all()
passed = 0
for s in summaries:
    if s["checks_passed"]:
        passed += 1
print(f"    {passed} of {len(summaries)} summaries passed all checks")

print("Done.")