# src/agent.py
# The tool-using agent: two tools, the rules, and the loop.
from src.config import MODEL, client
from src.analysis import run_sql
from src.rag import search_filing


def query_financials(sql):
    # The model writes this SQL, so allow only a single read query
    cleaned = sql.strip().rstrip(";")
    if ";" in cleaned or not cleaned.lower().startswith(("select", "with")):
        return "Error: only a single SELECT query is allowed."

    # run_sql opens the database read-only, so writing is impossible either way.
    # If the query fails, send the error back so the model can fix it and retry.
    try:
        df = run_sql(cleaned)
    except Exception as e:
        return f"SQL error: {e}"
    return df.head(50).to_string(index=False)


# The tool menu the model reads
tools = [
    {
        "name": "query_financials",
        "description": (
            "Run a SQL SELECT query on the DuckDB table 'financials'. "
            "One row per company per fiscal year. Columns: "
            "ticker (text: ORCL, MSFT, CRM, ADBE, NOW), fiscal_year (integer), "
            "revenue, operating_income, net_income (in US dollars, not billions), "
            "operating_margin (a percentage, e.g. 45.2). "
            "Use this for every financial figure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SQL SELECT query"},
            },
            "required": ["sql"],
        },
    },
        {
        "name": "search_filing",
        "description": (
            "Search one company's most recent 10-K for passages about a topic, such as "
            "reasons behind results, strategy, or risks. Returns excerpts labeled with the "
            "company and chunk number. To compare companies, call it once per company."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for, in plain words"},
                "ticker": {
                    "type": "string",
                    "enum": ["ORCL", "MSFT", "CRM", "ADBE", "NOW"],   # the only allowed values
                    "description": "Which company's 10-K to search",
                },
            },
            "required": ["query", "ticker"],
        },
    },
]


AGENT_PROMPT = """- Use search_filing for explanations, strategy, or risks, from each company's latest 10-K.
- Cite filing excerpts by company and chunk number, like [ORCL chunk 412].

Rules:
- Get every financial figure with query_financials. Never state figures from memory.
- Use search_filing for explanations, strategy, or risks. Only Oracle's 10-K is available.
- Cite filing excerpts by chunk number, like [chunk 412].
- Database amounts are in US dollars; convert to billions in your answer.
- If the tools don't provide what's needed, say so plainly instead of guessing."""


def run_tool(name, inputs):
    # Match the tool name the model asked for to the real Python function
    if name == "query_financials":
        return query_financials(inputs["sql"])
    if name == "search_filing":
        return search_filing(inputs["query"], inputs["ticker"])
    return f"Unknown tool: {name}"


def run_agent(question, max_steps=6):
    # Returns two things: the answer, and a trace of every tool call.
    # The notebook version printed the trace; an app can't see printed text,
    # so now the trace is returned, and the app can display it.
    messages = [{"role": "user", "content": question}]
    trace = []

    for step in range(max_steps):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=AGENT_PROMPT,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        # No tool requested: the model is done
        if response.stop_reason != "tool_use":
            answer = ""
            for block in response.content:
                if block.type == "text":
                    answer += block.text
            return answer, trace

        # Run every tool the model asked for, and record each one in the trace
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                output = run_tool(block.name, block.input)
                trace.append({"step": step + 1, "tool": block.name, "input": block.input})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
        messages.append({"role": "user", "content": tool_results})

    return "Stopped: reached the step limit without a final answer.", trace