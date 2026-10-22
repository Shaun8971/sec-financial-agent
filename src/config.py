# src/config.py
# Settings every part of the project shares. Change them here, and everything uses the new values.
import os
from dotenv import load_dotenv
import anthropic

load_dotenv()   # read the .env file in the project folder

# The SEC requires a name and email on every request
SEC_HEADERS = {"User-Agent": os.getenv("SEC_USER_AGENT")}

# LLM gateway settings
LLM_API_KEY = os.getenv("OPENWEBUI_API_KEY")
LLM_BASE_URL = os.getenv("OPENWEBUI_BASE_URL")
MODEL = "anthropic.claude-haiku-5-5"

# Which companies we cover, and where generated files are saved
TICKERS = ["ORCL", "MSFT", "CRM", "ADBE", "NOW"]
DB_PATH = "data/financials.duckdb"
CHROMA_PATH = "data/chroma"
FILINGS_DIR = "data/filings"    # one text file per company's 10-K

# One shared connection to the LLM, used by every file that calls the model
client = anthropic.Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)