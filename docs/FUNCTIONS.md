# Function Reference: SEC Financial Agent

**Repository:** `sec-financial-agent`
**Status:** Data layer, SQL analysis, LLM summaries, document retrieval for all five companies, agent (hand-written and LangGraph), automated evaluation, and a local web app complete. Online deployment and cost tracking in progress.

## Overview

This project is an AI research assistant covering five enterprise software companies: Oracle, Microsoft, Salesforce, Adobe, and ServiceNow. It draws on two sources. Financial figures come from the SEC's XBRL company facts, cleaned into a SQL table with one verified figure per company, metric, and fiscal year. Explanations come from each company's most recent 10-K, split into chunks, labeled by company, and indexed for search. An agent decides which source a question needs, queries it, and answers with figures from the database and citations to the filings.

The design follows one principle: figures come from code and the database, and the language model explains them. Wherever a model output can be compared against source data, it is.

## Architecture

![Architecture](pipeline.svg)

## Code layout

| File | Contents |
|---|---|
| `src/config.py` | Shared settings: keys, model, tickers, file paths, and the LLM client |
| `src/data.py` | SEC fetch, cleaning rules, and building the `financials` table |
| `src/analysis.py` | Read-only SQL helper, per-company figures, and LLM summaries with checks |
| `src/rag.py` | 10-K download, chunking, the Chroma index, search, and cited answers |
| `src/agent.py` | Tool descriptions, rules, and the hand-written agent loop |
| `src/agent_langgraph.py` | The same agent built as a LangGraph graph |
| `build.py` | Rebuilds every generated file with one command |
| `eval_agent.py` | Automated quiz with known answers; saves scores to `results/` |
| `app.py` | Streamlit web app with a password, question limit, and visible trace |
| `notebooks/01_edgar_api.ipynb` | Step-by-step record of how the pipeline was built |

## Component tracker

### Data layer (`src/data.py`)

| Component | Type | Purpose | Status |
|---|---|---|---|
| `get_ciks(tickers)` | Function | Maps tickers to SEC company IDs (CIKs) | Complete |
| `get_facts(cik)` | Function | Fetches a company's raw XBRL facts | Complete |
| `get_annual(facts, tag)` | Function | Cleans one line item into annual figures | Complete |
| `get_revenue(company)` | Function | Merges three revenue tags by priority | Complete |
| `build_financials()` | Function | Runs the full data layer and saves the `financials` table | Complete |

### SQL analysis and summaries (`src/analysis.py`)

| Component | Type | Purpose | Status |
|---|---|---|---|
| `run_sql(sql, params)` | Function | Runs one query on a read-only connection | Complete |
| `get_company_data(ticker)` | Function | Five most recent years, with revenue growth | Complete |
| `summarize_company(ticker)` | Function | Structured JSON summary from the LLM | Complete |
| `check_summary(result, data)` | Function | Validates a summary against the database | Complete |
| `summarize_all()` | Function | Summarizes and checks every company; records failures | Complete |

### Document retrieval (`src/rag.py`)

| Component | Type | Purpose | Status |
|---|---|---|---|
| `download_10k_text(ticker, cik)` | Function | Downloads a company's latest 10-K and saves it as text | Complete |
| `chunk_text(text, chunk_size, overlap)` | Function | Splits text into overlapping chunks | Complete |
| `build_index()` | Function | Rebuilds the index with all five 10-Ks, labeled by ticker | Complete |
| `retrieve(query, ticker, n_results)` | Function | Finds the closest chunks, optionally within one company | Complete |
| `search_filing(query, ticker)` | Agent tool | Returns labeled excerpts | Complete |
| `ask_filing(question, ticker)` | Function | Answers from retrieved chunks, with citations | Complete |
| `get_chunk(ticker, chunk_number)` | Function | Returns one chunk's text, for checking a citation | Complete |

### Agent (`src/agent.py`, `src/agent_langgraph.py`)

| Component | Type | Purpose | Status |
|---|---|---|---|
| `query_financials(sql)` | Agent tool | Read-only SQL on `financials`, with a query guard | Complete |
| `tools`, `AGENT_PROMPT` | Configuration | The tool menu and the agent's standing rules | Complete |
| `run_tool(name, inputs)` | Dispatcher | Routes a tool request to its function | Complete |
| `run_agent(question)` | Agent loop | Multi-step tool use; returns the answer and a trace | Complete |
| `run_graph(question)` | Agent loop | LangGraph version; same inputs and outputs | Complete |

### Scripts and interface

| Component | Type | Purpose | Status |
|---|---|---|---|
| `build.py` | Script | One-command rebuild of all generated data | Complete |
| `eval_agent.py` | Script | Automated evaluation with known answers | Complete |
| `app.py` | Web app | Streamlit interface with access control | Complete, local |
| Online deployment | Hosting | Public URL with secrets and a password | In progress |
| Cost and latency tracking | Monitoring | Tokens and time per question | Planned |

## Configuration

| Variable (in `.env`) | Purpose |
|---|---|
| `SEC_USER_AGENT` | Name and email sent with every SEC request, as the SEC's fair access policy requires |
| `OPENWEBUI_API_KEY` | API key for the LLM gateway |
| `OPENWEBUI_BASE_URL` | Gateway address, ending in `/api` |
| `APP_PASSWORD` | Password for the web app; the app stays locked if this is not set |

`src/config.py` loads these with `load_dotenv()` and `os.getenv()`, and also holds `MODEL`, `TICKERS`, the file paths (`DB_PATH`, `CHROMA_PATH`, `FILINGS_DIR`), and a shared `client` for the LLM. When deployed, the same values are entered as secrets in the hosting service, and the code does not change.

Requests use the Anthropic Messages API format through an Open WebUI gateway. Any endpoint that accepts this format works by changing `OPENWEBUI_BASE_URL`.

## Data layer (`src/data.py`)

### `get_ciks(tickers)` and `get_facts(cik)`

`get_ciks` reads the SEC's public ticker file and returns a dictionary such as `{"MSFT": 789019}`. `get_facts` pads a CIK to 10 digits, calls the company facts API (`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`) with the required User-Agent header and a 10-second timeout, and returns every figure the company has reported in XBRL form.

### `get_annual(facts, tag)`

Turns the full history of one line item into one figure per fiscal year. The raw data mixes annual and quarterly figures, and each year appears in up to three annual reports, because every 10-K repeats the two prior years for comparison.

| Step | Rule | What it removes or fixes |
|---|---|---|
| 1 | Keep figures from 10-K annual reports (`form` is `10-K`, `fp` is `FY`) | Quarterly 10-Q figures |
| 2 | Keep periods longer than 300 days | Quarterly tables included inside 10-Ks |
| 3 | Sort by filing date and keep the most recent figure for each period | Repeated comparison years; restated figures replace originals |
| 4 | Add `fiscal_year` from the period end date | Labels each row for reporting |

Returns columns `end`, `fiscal_year`, and `val` (USD).

### `get_revenue(company)`

All five companies have reported revenue under three XBRL tags at different times, largely because revenue accounting standards changed around 2018. Using one tag would miss years, and adding them would double count. The function runs `get_annual` for each available tag, stacks the results in priority order, and keeps the first value for each period.

| Priority | Tag | Typical use |
|---|---|---|
| 1 | `RevenueFromContractWithCustomerExcludingAssessedTax` | Current standard, roughly 2018 onward |
| 2 | `Revenues` | General revenue tag |
| 3 | `SalesRevenueNet` | Older standard, mostly before 2018 |

### `build_financials()`

Runs the whole data layer: looks up CIKs, fetches each company once, checks that every ticker holds a different company's data (the duplicate-data guard), cleans net income, operating income, and revenue, pivots to one row per company per year, adds operating margin, and saves the `financials` table to `data/financials.duckdb` with `CREATE OR REPLACE`.

The duplicate-data guard was added after a hard-coded CIK caused every ticker to return Microsoft's data. The downstream sanity checks did not catch that bug, because Microsoft's data was internally consistent, so the guard targets this failure directly.

| Column | Type | Description |
|---|---|---|
| `ticker` | VARCHAR | ORCL, MSFT, CRM, ADBE, or NOW |
| `fiscal_year` | INTEGER | Year of the fiscal year end date |
| `revenue` | DOUBLE | US dollars |
| `operating_income` | DOUBLE | US dollars |
| `net_income` | DOUBLE | US dollars |
| `operating_margin` | DOUBLE | Operating income divided by revenue, as a percentage |

## SQL analysis and summaries (`src/analysis.py`)

### `run_sql(sql, params=None)`

Opens the database with `read_only=True`, runs one query, returns a pandas table, and closes the connection. Every query in the project, including the agent's, goes through this function, so nothing can modify the data through the application.

### `get_company_data(ticker)`

Returns the five most recent fiscal years in billions, with operating margin and year-over-year revenue growth calculated with the `LAG` window function. The ticker is passed as a `?` parameter, and the last five rows are selected after growth is calculated, so the earliest year still has a prior year to compare against.

### `summarize_company(ticker)` and `check_summary(result, data)`

`summarize_company` sends the five-year table with a system prompt specifying the JSON format and two grounding rules (use only the figures provided, copy numbers exactly), with a limit of 1,000 tokens. It raises a clear error if the reply is cut off or is not valid JSON.

| Field | Content |
|---|---|
| `ticker` | Ticker symbol |
| `revenue_trend` | `growing`, `flat`, or `declining` |
| `latest_revenue_growth_pct` | Most recent year's revenue growth |
| `margin_trend` | `expanding`, `stable`, or `contracting` |
| `summary` | Two sentences at most, citing specific figures |
| `watch_items` | Up to three points worth watching |

`check_summary` confirms all six fields are present, the trend fields use permitted labels, and the reported growth figure matches the database within 0.1 points. It returns a list of problems; an empty list means it passed.

### `summarize_all()`

Summarizes and checks every company, and saves the results to `data/summaries.json` with `checks_passed` and `problems` fields. If one company fails, the failure is recorded as that company's problem and the run continues.

## Document retrieval (`src/rag.py`)

### `download_10k_text(ticker, cik)`

Finds the company's most recent 10-K through the submissions API, builds the document URL from the CIK, the accession number without dashes, and the file name, then parses the HTML with BeautifulSoup, removes the hidden XBRL header block, and saves the visible text to `data/filings/{ticker}_10K.txt`. Narrative sections convert cleanly; financial tables do not, which is acceptable because figures come from the database.

### `chunk_text(text, chunk_size=1200, overlap=200)`

Splits text into pieces of about 1,200 characters, each repeating the last 200 characters of the previous one, so a sentence on a boundary is not lost.

### `build_index()`

Deletes and rebuilds the `filings_10k` collection in `data/chroma`, so changing chunk settings never leaves stale chunks behind. Each chunk has an ID such as `ADBE_10k_87` and metadata `{"ticker": "ADBE", "source": "ADBE 10-K", "chunk": 87}`. Chunks are embedded with Chroma's default embedding model, which runs locally.

### `retrieve(query, ticker=None, n_results=4)`, `search_filing`, and `ask_filing`

`retrieve` returns the closest chunks as labeled text and a list of labels such as `ADBE chunk 87`. When a ticker is given, it filters with `where={"ticker": ticker}`, so a search stays inside that company's filing. This matters because software companies describe risks and strategy in similar language, and an unfiltered search could return another company's passage.

`search_filing` is the agent's tool and returns only the excerpts. `ask_filing` sends the excerpts to the model with rules: use only the excerpts, cite each claim as `[TICKER chunk N]`, and reply with a fixed refusal line when the excerpts do not answer the question. `get_chunk(ticker, chunk_number)` returns any chunk's text, so a citation can be checked.

## Agent (`src/agent.py`, `src/agent_langgraph.py`)

### Tools

| Tool | Inputs | What the model is told |
|---|---|---|
| `query_financials` | `sql` | The table, exact columns, units, and that it must be used for every figure |
| `search_filing` | `query`, `ticker` (one of the five, enforced with an `enum`) | That it searches one company's latest 10-K, and to call it once per company when comparing |

### `query_financials(sql)`

Removes a trailing semicolon, rejects any query containing another semicolon or not starting with `SELECT` or `WITH`, runs the query through the read-only `run_sql`, and returns at most 50 rows as text. Errors are returned as messages, so the model can correct its query and retry.

### `AGENT_PROMPT`

The five companies covered; every figure must come from `query_financials` and never from memory; explanations come from `search_filing`; filing content is cited by company and chunk number; amounts are converted to billions; and the agent says so plainly when its tools do not provide an answer.

### `run_agent(question, max_steps=6)`

Each round sends the full conversation, the rules, and the tool menu. Tool requests are run through `run_tool`, recorded in a trace (step, tool, inputs), and returned to the model as `tool_result` blocks linked by ID. When the model stops requesting tools, the function returns the answer and the trace. The loop stops after six steps, which prevents endless loops and caps cost.

### `run_graph(question)`

The same agent as a LangGraph `StateGraph`: an agent node (the model with tools bound), a `ToolNode`, and `tools_condition` routing between them, with a recursion limit of 12 (about six rounds). It reuses the rules and tool functions from `agent.py` and returns the same answer-and-trace shape.

## Scripts and interface

### `build.py`

Runs `build_financials`, downloads all five 10-Ks, rebuilds the index, and runs `summarize_all`, printing progress for each step. Anyone who clones the repository and fills in `.env` can rebuild every generated file with `python build.py`.

### `eval_agent.py`

Runs the agent on 12 questions with known answers and scores each automatically. Expected figures are read from the database at run time, so the answer key always matches the data.

| Question type | Count | How it is scored |
|---|---|---|
| Figures | 7 | A number in the answer is within 1% of the database value |
| Comparison | 1 | The answer names the correct company |
| Filing | 2 | The answer includes at least one citation in `[TICKER chunk N]` form |
| Out of scope | 2 | The answer says the data is not available |

Results, including each answer, time taken, and tools used, are saved to `results/agent_eval.csv`. The filing and out-of-scope checks confirm the answer's form, not every claim, so failures and a sample of passes are reviewed by hand.

### `app.py`

A Streamlit app. It stays locked until the visitor enters `APP_PASSWORD`, limits each session to 20 questions to protect API credits, shows example questions in the sidebar, and displays a fold-out trace under every answer with the exact SQL or search the agent used and the time taken. Dollar signs are escaped so Streamlit does not treat figures as math formatting. Each question is answered independently; the agent does not remember earlier questions.

## Data quality controls

| Control | Where | Risk it addresses |
|---|---|---|
| Annual filings only | `get_annual`, step 1 | Quarterly figures mistaken for annual ones |
| Full-year periods only | `get_annual`, step 2 | Partial periods reported inside annual filings |
| Latest filing wins | `get_annual`, step 3 | Duplicate years, and outdated figures after a restatement |
| Revenue tag priority | `get_revenue` | Missing years, or double counted revenue |
| Duplicate-data guard | `build_financials` | One company's data stored under several tickers |
| Format and figure checks | `check_summary` | Malformed output, or a growth figure that does not match the database |
| Failure recording | `summarize_all` | One bad model reply stopping the whole build |
| Company-filtered search | `retrieve` | Another company's passage answering the question |
| Grounded answers with citations | `ask_filing`, `AGENT_PROMPT` | Answers drawn from the model's memory instead of the filings |
| Read-only connection and SQL guard | `run_sql`, `query_financials` | Model-written SQL that changes or deletes data |
| Step limit | `run_agent`, `run_graph` | Endless loops and runaway cost |
| Automated evaluation | `eval_agent.py` | Regressions after changing prompts, models, or chunking |

## Security and compliance

Credentials live only in the local `.env` file, which Git ignores. Generated data in `data/` is also excluded and rebuilt with `build.py`. Every SEC request carries the User-Agent header required by the SEC's fair access policy and uses a timeout. All database access is read-only from the application, and the agent's queries pass an additional guard. The web app requires a password, stays locked if none is configured, and caps questions per session.

## Validation log

| Date | Check | Expected | Result | Status |
|---|---|---|---|---|
| Oct 2026 | Microsoft FY2024 revenue | $245.1B, as reported | $245.1B | Pass |
| Oct 2026 | Each ticker holds its own company's data | 5 distinct companies | 5 | Pass, after fixing a hard-coded CIK |
| Oct 2026 | Revenue tag coverage by company and year | Tags mapped without double counting | Priority mapping applied | Reviewed |
| Oct 2026 | LLM summary checks, all five companies | No problems reported | Recorded in `data/summaries.json` | Recorded |
| Oct 2026 | Tool calling through the LLM gateway | Correct tool and inputs | As expected | Pass |
| Oct 2026 | RAG on Oracle's 10-K: answerable question, citation spot check, and unanswerable question | Cited answer; citation supports claim; refusal | As expected | Pass |
| Oct 2026 | SQL guard | `DROP` rejected; invalid column returns an error | As expected | Pass |
| Oct 2026 | Agent: figures-only, filing-only, combined, and out-of-scope questions | Correct tools; no figure for Workday | As expected | Pass |
| Oct 2026 | Agent eval, 12 questions (before the multi-company change) | All pass | 12 of 12; median 3.4 seconds per question | Pass |

## Known limitations

**Data.** Fiscal years end on different dates by company: Oracle's in May, Microsoft's in June, and the others in January, November, or December, so figures labeled with the same fiscal year can cover different months. The pipeline covers US GAAP filers and income statement items only, and does not handle a company changing its fiscal year end.

**LLM summaries.** The model assigns trend labels that rules could compute. A planned improvement moves labels and growth figures into code and limits the model to the narrative. The checks do not verify the narrative itself; planned additions are a number-grounding check and a contradiction check against computed labels.

**Retrieval.** Chunks are split by character count rather than by 10-K section, embeddings use Chroma's small default model, and search is meaning-based only, without keyword search or re-ranking. Only each company's latest 10-K is indexed. Retrieval quality has been spot-checked but not measured; a hit-rate test set is planned.

**Evaluation.** The quiz is small (12 questions) and passed in full, which suggests it should include harder cases, such as multi-year calculations, years outside the data, and attempts to override the agent's rules. Filing and out-of-scope checks are keyword-based.

**App.** Each question is answered independently, without memory of earlier questions in the session.

## How to extend

To add a company, add its ticker to `TICKERS` in `src/config.py`, add it to the `enum` list and descriptions in `src/agent.py`, and run `python build.py`; the duplicate-data guard confirms the new company's data is distinct. To add an income statement metric, add its XBRL tag to `METRICS` in `src/data.py`. A `KeyError` naming a tag means the company does not report under it, which signals the metric needs a priority mapping like revenue's. After any change to prompts, models, or chunking, run `python eval_agent.py` and compare against the previous results.

## Change log

| Date | Change |
|---|---|
| Oct 2026 | Project setup: repository, Python 3.13 virtual environment, folder structure |
| Oct 2026 | SEC ticker lookup and `get_facts` |
| Oct 2026 | `get_annual` with four cleaning rules; `get_revenue` with three-tag priority mapping |
| Oct 2026 | Fixed a hard-coded CIK that returned Microsoft's data for every ticker; added the duplicate-data guard |
| Oct 2026 | `financials` table in DuckDB; window-function growth in `get_company_data` |
| Oct 2026 | `summarize_company` and `check_summary`; summaries saved to `data/summaries.json` |
| Oct 2026 | Oracle 10-K retrieval, chunking, Chroma index, and `ask_filing` |
| Oct 2026 | Agent tools, `run_tool`, and `run_agent` with trace and step limit |
| Oct 2026 | LangGraph version of the agent, compared with the hand-written loop |
| Oct 2026 | Notebook code moved into `src/` modules; read-only `run_sql`; one-command `build.py` |
| Oct 2026 | Raised the summary token limit to 1,000; `summarize_all` records a failed company instead of stopping |
| Oct 2026 | `eval_agent.py`: 12-question automated evaluation, results saved to `results/` |
| Oct 2026 | Streamlit app with password, question limit, and visible trace |
| Oct 2026 | All five companies' 10-Ks indexed, with company-filtered search and `[TICKER chunk N]` citations |
