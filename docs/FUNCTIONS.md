# Function Reference: SEC Financial Agent

**Repository:** `sec-financial-agent`
**Notebook:** `notebooks/01_edgar_api.ipynb`
**Status:** Data layer, SQL analysis, LLM summaries, document retrieval, and agent complete. Evaluation and deployment planned.

## Overview

This project is an AI research assistant covering five enterprise software companies: Oracle, Microsoft, Salesforce, Adobe, and ServiceNow. It draws on two sources. Financial figures come from the SEC's XBRL company facts, cleaned into a SQL table with one verified figure per company, metric, and fiscal year. Explanations come from Oracle's most recent 10-K, split into chunks and indexed for search. An agent decides which source a question needs, queries it, and answers with figures from the database and citations to the filing.

The design follows one principle: figures come from code and the database, and the language model explains them. Wherever a model output can be compared against source data, it is.

## Architecture

![Architecture](pipeline.svg)

## Component tracker

### Data layer

| Component | Type | Purpose | Status |
|---|---|---|---|
| `headers` | Configuration | SEC User-Agent loaded from `.env` | Complete |
| `ciks` | Lookup table | Maps each ticker to its SEC company ID (CIK) | Complete |
| `get_facts(cik)` | Function | Fetches a company's raw XBRL facts | Complete |
| `all_facts` | Cache | Holds each company's raw data after a single fetch | Complete |
| Duplicate-data guard | Check | Stops the run if two tickers hold the same company's data | Complete |
| `get_annual(facts, tag)` | Function | Cleans one line item into annual figures | Complete |
| `get_revenue(company)` | Function | Merges three revenue tags by priority | Complete |
| `combined`, `summary` | Assembly | Stacks all results and pivots to one row per company per year | Complete |
| `financials` | DuckDB table | Final table used by SQL analysis and the agent | Complete |

### SQL analysis and LLM summaries

| Component | Type | Purpose | Status |
|---|---|---|---|
| `q(sql)` | Helper | Runs a query and returns a pandas table | Complete |
| `get_company_data(ticker)` | Function | Five most recent years, with revenue growth | Complete |
| `summarize_company(ticker)` | Function | Structured JSON summary from the LLM | Complete |
| `check_summary(result, data)` | Function | Validates a summary against the database | Complete |

### Document retrieval and agent

| Component | Type | Purpose | Status |
|---|---|---|---|
| 10-K retrieval | Notebook steps | Downloads Oracle's latest 10-K and converts it to text | Complete |
| `chunk_text(text, chunk_size, overlap)` | Function | Splits text into overlapping chunks | Complete |
| `orcl_10k` | Chroma collection | Searchable chunks with metadata for citations | Complete |
| `ask_filing(question)` | Function | Answers from retrieved chunks, with citations | Complete |
| `query_financials(sql)` | Agent tool | Read-only SQL on `financials` | Complete |
| `search_filing(query)` | Agent tool | Returns labeled 10-K excerpts | Complete |
| `run_tool(name, inputs)` | Dispatcher | Routes a tool request to its function | Complete |
| `run_agent(question)` | Agent loop | Multi-step tool use, with a printed trace | Complete |

### Planned

| Component | Type | Purpose | Status |
|---|---|---|---|
| LangGraph agent | Agent | The same agent rebuilt in LangGraph, for comparison | Planned |
| `src/` modules | Packaging | Notebook code moved into importable files | Planned |
| Evaluation suite | Testing | Answer accuracy and retrieval hit rate | Planned |
| Streamlit app | Interface | Deployed demo with access control | Planned |

## Configuration

| Variable | Purpose |
|---|---|
| `SEC_USER_AGENT` | Name and email sent with every SEC request, as the SEC's fair access policy requires |
| `OPENWEBUI_API_KEY` | API key for the LLM gateway |
| `OPENWEBUI_BASE_URL` | Gateway address, ending in `/api` |

All three live in `.env`, which is listed in `.gitignore`, and are loaded at runtime with `load_dotenv()` and `os.getenv()`. When the project is deployed, the same values are entered as secrets in the hosting service, and the code does not change.

The LLM client is `anthropic.Anthropic(api_key=..., base_url=...)`. Requests use the Anthropic Messages API format and are sent through an Open WebUI gateway. Any endpoint that accepts this format works by changing `base_url`. The model ID is stored in `MODEL`.

## Part 1: Data layer

### `get_facts(cik)`

**Purpose:** Fetches every financial figure a company has reported to the SEC in tagged (XBRL) form.

| Input | Type | Description |
|---|---|---|
| `cik` | int | The company's SEC ID, taken from `ciks` |

| Returns | Description |
|---|---|
| dict | Raw company facts: company name, CIK, and every reported line item with its full history |

The function pads the CIK to the 10 digits the API expects, builds the company facts URL (`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`), sends a GET request with the required User-Agent header and a 10-second timeout, and returns the parsed JSON. Each company is fetched once per run and stored in `all_facts`.

### Duplicate-data guard

After the fetch, the pipeline collects each company's `entityName` and asserts that all five are different. If two tickers hold the same company's data, the run stops with a message naming the duplicates. The guard was added after a hard-coded CIK caused every ticker to return Microsoft's data. The downstream sanity checks did not catch that bug, because Microsoft's data was internally consistent, so this check targets that failure directly.

### `get_annual(facts, tag)`

**Purpose:** Turns the full history of one line item into a clean table with one figure per fiscal year.

| Input | Type | Description |
|---|---|---|
| `facts` | dict | Raw company data from `get_facts` |
| `tag` | str | XBRL line item, such as `"NetIncomeLoss"` or `"OperatingIncomeLoss"` |

| Returns | Description |
|---|---|
| DataFrame | Columns `end` (fiscal year end date), `fiscal_year`, and `val` (amount in USD) |

The raw data for one line item mixes annual and quarterly figures, and each year appears in up to three annual reports, because every 10-K repeats the two prior years for comparison. The function applies four rules in order:

| Step | Rule | What it removes or fixes |
|---|---|---|
| 1 | Keep figures from 10-K annual reports (`form` is `10-K`, `fp` is `FY`) | Quarterly 10-Q figures |
| 2 | Keep periods longer than 300 days | Quarterly tables included inside 10-Ks |
| 3 | Sort by filing date and keep the most recent figure for each period | Repeated comparison years; restated figures replace originals |
| 4 | Add `fiscal_year` from the period end date | Labels each row for reporting |

### `get_revenue(company)`

**Purpose:** Produces one revenue series per company, even though companies have reported revenue under different XBRL tags over time.

All five companies have used three revenue tags at different points, largely because revenue accounting standards changed around 2018. Using one tag would miss years, and adding the tags together would double count any year reported under two of them. The function runs `get_annual` for each tag the company has, stacks the results in priority order, and keeps the first value for each period.

| Priority | Tag | Typical use |
|---|---|---|
| 1 | `RevenueFromContractWithCustomerExcludingAssessedTax` | Current standard, roughly 2018 onward |
| 2 | `Revenues` | General revenue tag |
| 3 | `SalesRevenueNet` | Older standard, mostly before 2018 |

### `financials` table

Stored in `data/financials.duckdb` and rebuilt with `CREATE OR REPLACE`, so re-running is safe.

| Column | Type | Description |
|---|---|---|
| `ticker` | VARCHAR | ORCL, MSFT, CRM, ADBE, or NOW |
| `fiscal_year` | INTEGER | Year of the fiscal year end date |
| `revenue` | DOUBLE | US dollars |
| `operating_income` | DOUBLE | US dollars |
| `net_income` | DOUBLE | US dollars |
| `operating_margin` | DOUBLE | Operating income divided by revenue, as a percentage |

## Part 2: SQL analysis

### `q(sql)`

A helper that runs a query through the DuckDB connection and returns the result as a pandas table, so query results display cleanly in the notebook.

### `get_company_data(ticker)`

**Purpose:** Returns the five most recent fiscal years for one company, in billions, with operating margin and year-over-year revenue growth.

Growth is calculated with the `LAG` window function, which places the prior year's revenue beside each row. The ticker is passed through a `?` placeholder rather than pasted into the query text. The last five rows are selected after growth is calculated, so the earliest of the five years still has a prior year to compare against.

| Returns | Columns |
|---|---|
| DataFrame | `fiscal_year`, `revenue_b`, `operating_income_b`, `net_income_b`, `operating_margin_pct`, `revenue_growth_pct` |

## Part 3: LLM summaries

### `summarize_company(ticker)`

**Purpose:** Produces a structured summary of a company's recent performance that code can read, display, and check.

The function sends the five-year table as text, along with a system prompt that specifies the exact JSON format and two grounding rules: use only the figures provided, and copy numbers exactly. It removes code fences if the model adds them, then parses the reply with `json.loads`.

| Field | Content |
|---|---|
| `ticker` | Ticker symbol |
| `revenue_trend` | `growing`, `flat`, or `declining` |
| `latest_revenue_growth_pct` | Most recent year's revenue growth |
| `margin_trend` | `expanding`, `stable`, or `contracting` |
| `summary` | Two sentences at most, citing specific figures |
| `watch_items` | Up to three points worth watching |

### `check_summary(result, data)`

**Purpose:** Validates a summary before it is used. Returns a list of problems; an empty list means it passed.

| Check | What it confirms |
|---|---|
| Required fields | All six fields are present |
| Allowed values | Trend fields use one of the permitted labels |
| Figure match | The reported growth figure is a number and matches the database within 0.1 points |

Results for all five companies are saved to `data/summaries.json`, each with `checks_passed` and `problems` fields. These checks confirm the output's structure and one figure. They do not verify the trend labels or the narrative; see Known limitations.

## Part 4: Document retrieval (RAG)

### 10-K retrieval

The notebook retrieves Oracle's filing list from the SEC submissions API, filters to 10-Ks, and selects the most recent. The document URL is built from the CIK, the accession number without dashes, and the primary document file name. BeautifulSoup parses the HTML, removes the hidden XBRL header block, and extracts the visible text, which is trimmed line by line and saved to `data/ORCL_10K.txt`. Narrative sections convert cleanly; financial tables do not, which is acceptable because figures come from the database.

### `chunk_text(text, chunk_size=1200, overlap=200)`

Splits text into pieces of about 1,200 characters. Each piece repeats the last 200 characters of the previous one, so a sentence that falls on a boundary is not lost.

### `orcl_10k` collection

A Chroma collection saved in `data/chroma`. Each chunk has an ID (`orcl_10k_0`, `orcl_10k_1`, and so on) and metadata (`{"source": "ORCL 10-K", "chunk": i}`) used for citations and future filtering. Chunks are written with `upsert`, so re-running is safe, and embedded with Chroma's default embedding model, which runs locally. Because `upsert` never deletes, changing the chunk size requires deleting the collection before rebuilding it.

### `ask_filing(question, n_results=4)`

**Purpose:** Answers a question from the four most relevant chunks, with citations.

The function retrieves the chunks closest in meaning to the question, labels each with its chunk number, and sends them to the model with rules: use only the excerpts, cite chunk numbers after each claim, and reply with a fixed refusal line if the excerpts do not answer the question. It returns the answer and the list of chunk numbers that were sent, so citations can be checked against `chunks[n]`.

## Part 5: Agent

### Tools

| Tool | Input | What the model is told |
|---|---|---|
| `query_financials` | `sql` | The table name, exact columns, units, and that it must be used for every figure |
| `search_filing` | `query` | That it searches Oracle's latest 10-K for explanations, strategy, or risks, and that only Oracle's filing is available |

### `query_financials(sql)`

Runs model-written SQL with safeguards. It removes a trailing semicolon, rejects any query containing another semicolon or not starting with `SELECT` or `WITH`, and returns at most 50 rows as text. Errors are caught and returned as messages, so the model can correct its query and try again instead of the run failing.

### `search_filing(query, n_results=4)`

The retrieval half of `ask_filing`. It returns labeled excerpts, and the agent writes the answer itself.

### `AGENT_PROMPT`

Standing rules for the agent: the five companies it covers, that every figure must come from `query_financials` and never from memory, that explanations come from `search_filing`, that filing content is cited by chunk number, that amounts are converted to billions, and that it says so plainly when the tools do not provide an answer.

### `run_tool(name, inputs)`

Matches the tool name in the model's request to the corresponding Python function and returns its output.

### `run_agent(question, max_steps=6)`

**Purpose:** Lets the model choose and use tools over several steps, then answer.

The conversation starts with the question. Each round, the full conversation, the rules, and the tool descriptions are sent to the model. If the model requests tools, each request is printed as a trace, run through `run_tool`, and returned as a `tool_result` linked to the request by its ID. When the model stops requesting tools, its text reply is returned. The loop stops after six steps, which prevents endless loops and caps cost, since each round re-sends the growing conversation.

## Data quality controls

| Control | Where | Risk it addresses |
|---|---|---|
| Annual filings only | `get_annual`, step 1 | Quarterly figures mistaken for annual ones |
| Full-year periods only | `get_annual`, step 2 | Partial periods reported inside annual filings |
| Latest filing wins | `get_annual`, step 3 | Duplicate years, and outdated figures after a restatement |
| Revenue tag priority | `get_revenue` | Missing years, or double counted revenue |
| Duplicate-data guard | After the fetch | One company's data stored under several tickers |
| Format and figure checks | `check_summary` | Malformed output, or a growth figure that does not match the database |
| Grounded answers with citations | `ask_filing`, `AGENT_PROMPT` | Answers drawn from the model's memory instead of the filing |
| Fixed refusal line | `ask_filing` | Guessing when the excerpts do not answer the question |
| Read-only SQL guard | `query_financials` | Model-written SQL that changes or deletes data |
| Step limit | `run_agent` | Endless loops and runaway cost |
| Spot checks against reported figures | Validation log | Logic errors the rules above would not catch |

## Security and compliance

Credentials and contact details live only in the local `.env` file, which Git ignores. Generated data in `data/` (the DuckDB file, the Chroma index, the 10-K text, and the summaries) is also excluded and can be rebuilt by running the notebook. Every SEC request carries the User-Agent header required by the SEC's fair access policy and uses a timeout. The agent's SQL access is limited to single read queries, and its loop is capped at six steps.

## Validation log

| Date | Check | Expected | Result | Status |
|---|---|---|---|---|
| Oct 2026 | Microsoft FY2024 revenue | $245.1B, as reported | $245.1B | Pass |
| Oct 2026 | Each ticker holds its own company's data | 5 distinct companies | 5 | Pass, after fixing a hard-coded CIK |
| Oct 2026 | Revenue tag coverage by company and year | Tags mapped without double counting | Priority mapping applied | Reviewed |
| Oct 2026 | LLM summary checks, all five companies | No problems reported | Recorded in `data/summaries.json` | Recorded |
| Oct 2026 | Tool calling through the LLM gateway | Model requests the tool with correct inputs | Correct tool and inputs | Pass |
| Oct 2026 | RAG, answerable question on cloud revenue growth | Grounded answer with citations | Answer cited supporting chunks | Pass |
| Oct 2026 | RAG, citation spot check | Cited chunk contains the claim | Confirmed | Pass |
| Oct 2026 | RAG, unanswerable question (FY2012 revenue) | Refusal line, no figure | Refused | Pass |
| Oct 2026 | SQL guard | `DROP` rejected; invalid column returns an error message | As expected | Pass |
| Oct 2026 | Agent, figures-only question | Uses `query_financials` | Correct tool | Pass |
| Oct 2026 | Agent, filing-only question | Uses `search_filing` | Correct tool | Pass |
| Oct 2026 | Agent, question needing both sources | Uses both tools and combines them | Both used | Pass |
| Oct 2026 | Agent, company outside the data (Workday) | States the data is unavailable | No figure given | Pass |

## Known limitations

**Data.** Fiscal years end on different dates by company: Oracle's in May and Microsoft's in June, while the others end in January, November, or December. Figures labeled with the same fiscal year can therefore cover different months; the `end` column records the exact date. The pipeline covers US GAAP filers only, supports income statement items but not balance sheet items, and does not handle a company changing its fiscal year end.

**LLM summaries.** The model currently assigns the trend labels, even though they follow rules that code could compute. A planned improvement moves labels and growth figures into code and limits the model to the narrative. The checks also do not verify the narrative itself; planned additions are a number-grounding check (every figure in the summary must appear in the source data) and a contradiction check against the computed labels.

**Retrieval.** Chunks are split by character count rather than by 10-K section, embeddings use Chroma's small default model, and search is meaning-based only, without keyword search or re-ranking. Only Oracle's latest 10-K is indexed. Retrieval quality has not yet been measured; a hit-rate test set is planned.

**Agent.** The SQL guard is a string check. A production deployment would use a read-only database connection, so writes are impossible regardless of the query.

## How to extend

To add a company, add its ticker to the `tickers` list and re-run the notebook from the top; the duplicate-data guard confirms the new company's data is distinct. To add an income statement metric, add its XBRL tag to `metrics`. A `KeyError` naming a tag means the company does not report under it, which signals the metric needs a priority mapping like revenue's. To add another company's filing, run the 10-K steps for that company, upsert its chunks with its own `source` metadata, update the `search_filing` description, and filter searches by source with Chroma's `where` option.

## Change log

| Date | Change |
|---|---|
| Oct 2026 | Project setup: repository, Python 3.13 virtual environment, folder structure |
| Oct 2026 | SEC ticker lookup (`ciks`) and `get_facts` |
| Oct 2026 | `get_annual` with four cleaning rules |
| Oct 2026 | `get_revenue` with three-tag priority mapping |
| Oct 2026 | `fiscal_year` added to cleaned outputs |
| Oct 2026 | Fixed a hard-coded CIK that returned Microsoft's data for every ticker; added the duplicate-data guard |
| Oct 2026 | `financials` table in DuckDB; `q`, `get_company_data` with window-function growth |
| Oct 2026 | `summarize_company` and `check_summary`; summaries saved to `data/summaries.json` |
| Oct 2026 | Oracle 10-K retrieval, `chunk_text`, Chroma index, and `ask_filing` |
| Oct 2026 | Agent tools, `run_tool`, and `run_agent` with trace and step limit |
