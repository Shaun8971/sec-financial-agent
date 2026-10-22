# SEC Financial Agent

An AI research assistant that answers questions about public companies using official SEC data. Financial figures come from a cleaned SQL table built from the SEC's XBRL data. Explanations come from each company's latest 10-K, retrieved and cited by passage. An agent decides which source each question needs, and a web app shows exactly how every answer was produced.

![Architecture](docs/pipeline.svg)

## What it can answer

| Question | How the agent answers it |
|---|---|
| "Which company had the highest operating margin in fiscal 2024?" | Writes and runs a SQL query on the financials table |
| "What does Adobe describe as its main business risks?" | Searches Adobe's 10-K only, and cites the passages it used |
| "Compare how Salesforce and ServiceNow describe their AI strategy." | Searches each company's 10-K separately, then compares them |
| "How did Oracle's operating margin change last year, and what drove it?" | Pulls the figures with SQL, finds the explanation in Oracle's 10-K, and combines them |
| "What was Workday's revenue in fiscal 2024?" | States that Workday is outside its data instead of guessing |

Every answer in the app comes with a trace showing which tools the agent used, the exact SQL or search it ran, and how long it took.

## Design principles

**Figures come from code, not the model.** Every number is pulled from a database built with documented cleaning rules. The language model explains figures; it does not produce them.

**Model output is checked against the source.** Structured summaries are validated against the database, filing answers cite the passages they draw on, and an automated quiz with known answers measures the agent.

**Safe by default.** The application can only read the database, the agent's SQL passes an extra guard, its loop is capped at six steps, and the web app requires a password and limits questions per session.

## Coverage

Five enterprise software companies (Oracle, Microsoft, Salesforce, Adobe, and ServiceNow), with annual revenue, operating income, net income, and operating margin from each company's XBRL history, plus document search across each company's most recent 10-K.

## How it works

**1. Structured data.** Each company's XBRL facts are pulled from the SEC's company facts API and cleaned with four rules: annual 10-K figures only, full-year periods only, the latest filing for each period (which captures restatements), and a priority mapping across the three tags companies have used for revenue. The result is a DuckDB table with one row per company per fiscal year.

**2. SQL analysis and summaries.** Window functions compute year-over-year growth. An LLM produces a structured JSON summary for each company, which is checked against the database before it is saved.

**3. Document retrieval (RAG).** Each company's latest 10-K is downloaded from EDGAR, converted to text, split into overlapping chunks, labeled by company, and indexed in Chroma with a local embedding model. Searches are filtered to one company, so a question about Adobe never draws on Oracle's filing, and answers cite passages as `[TICKER chunk N]`.

**4. Agent.** The model receives two tools, `query_financials` (SQL) and `search_filing` (10-K search for a chosen company). It decides which to call, the code runs them, and the results go back until the model can answer. The same agent is also implemented in LangGraph for comparison.

Full details, including every function, the cleaning rules, and the validation log, are in [docs/FUNCTIONS.md](docs/FUNCTIONS.md).

## Evaluation

`eval_agent.py` runs the agent on 12 questions with known answers, read from the database at run time, and scores each automatically.

| Question type | What it checks | Result |
|---|---|---|
| Figures (7) | A number in the answer is within 1% of the database value | 7 of 7 |
| Comparison (1) | The answer names the correct company | 1 of 1 |
| Filing (2) | The answer cites the filing | 2 of 2 |
| Out of scope (2) | The answer says the data is not available | 2 of 2 |

Median time per question was 3.4 seconds. Results for each question are saved in `results/agent_eval.csv`. A full pass on a small quiz mostly shows the basics work; the next version adds harder cases (see Limitations).

## Tech stack

| Area | Tools |
|---|---|
| Language | Python 3.13 |
| Data | pandas, DuckDB (SQL, window functions) |
| SEC data | EDGAR company facts and submissions APIs, BeautifulSoup |
| Retrieval | Chroma with metadata filtering, local embedding model |
| LLM | Anthropic Python SDK (Messages API, tool use, structured JSON), via an Open WebUI gateway |
| Agents | Hand-written tool-use loop, LangGraph |
| Interface | Streamlit |
| Workflow | Jupyter in VS Code, Git, GitHub |

## Repository structure

```
sec-financial-agent/
├── src/
│   ├── config.py            # shared settings and the LLM client
│   ├── data.py              # SEC fetch, cleaning, financials table
│   ├── analysis.py          # read-only SQL, figures, LLM summaries
│   ├── rag.py               # 10-K download, chunking, search, citations
│   ├── agent.py             # tools, rules, and the agent loop
│   └── agent_langgraph.py   # the same agent in LangGraph
├── docs/
│   ├── FUNCTIONS.md         # function reference, controls, validation log
│   └── pipeline.svg         # architecture diagram
├── notebooks/
│   └── 01_edgar_api.ipynb   # step-by-step build record
├── results/
│   └── agent_eval.csv       # latest evaluation results
├── build.py                 # rebuild all data in one command
├── eval_agent.py            # automated evaluation
├── app.py                   # Streamlit web app
├── data/                    # generated locally, not committed
├── .env                     # credentials, not committed
├── requirements.txt
└── README.md
```

## Running it locally

Clone the repository and set up a virtual environment:

```bash
git clone https://github.com/<your-username>/sec-financial-agent.git
cd sec-financial-agent
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project folder:

```
SEC_USER_AGENT="Your Name your@email.com"
OPENWEBUI_API_KEY="your-key"
OPENWEBUI_BASE_URL="https://your-gateway-address/api"
APP_PASSWORD="choose-a-password"
```

The SEC requires a name and email with every request. The LLM settings point to any endpoint that accepts the Anthropic Messages API format.

Then build the data, run the evaluation, and start the app:

```bash
python build.py          # fetches SEC data and 10-Ks, builds the database and index
python eval_agent.py     # scores the agent on questions with known answers
streamlit run app.py     # opens the app in your browser
```

The first build downloads the SEC data and the embedding model, and indexes all five 10-Ks, so it takes several minutes.

## Limitations

Fiscal years end in different months by company, so figures labeled with the same year can cover different periods. The pipeline covers US GAAP filers and income statement items only. Retrieval uses character-based chunks and meaning-based search without re-ranking, and its quality has been spot-checked but not measured. The LLM assigns trend labels that could be computed by rules, and the evaluation set is small. Each of these is documented, with a planned fix, in [docs/FUNCTIONS.md](docs/FUNCTIONS.md#known-limitations).

## Roadmap

The next steps are deploying the app online, tracking cost and latency per question, adding harder evaluation cases, measuring retrieval with a hit-rate test (including a before-and-after comparison of section-based chunking), and moving trend labels from the model into code.

## Data source

All data comes from SEC EDGAR (data.sec.gov and sec.gov), accessed in line with the SEC's fair access policy. This project is for research and learning, not investment advice.

## Author

Shaunak Dhekane, Master of Engineering Management, Thayer School of Engineering at Dartmouth
