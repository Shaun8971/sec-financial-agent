# src/agent_langgraph.py
# The same agent built as a LangGraph flowchart, for comparison with agent.py.
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition

from src.config import MODEL, LLM_API_KEY, LLM_BASE_URL
from src.agent import AGENT_PROMPT, query_financials
from src.rag import search_filing


@tool("query_financials")
def lc_query_financials(sql: str) -> str:
    """Run a SQL SELECT query on the DuckDB table 'financials'.
    One row per company per fiscal year. Columns: ticker (ORCL, MSFT, CRM, ADBE, NOW),
    fiscal_year (integer), revenue, operating_income, net_income (US dollars, not billions),
    operating_margin (a percentage). Use this for every financial figure."""
    return query_financials(sql)


@tool("search_filing")
def lc_search_filing(query: str, ticker: str) -> str:
    """Search one company's most recent 10-K for passages about a topic, such as reasons
    behind results, strategy, or risks. ticker must be one of ORCL, MSFT, CRM, ADBE, NOW.
    Returns excerpts labeled with the company and chunk number.
    To compare companies, call it once per company."""
    return search_filing(query, ticker)


lc_tools = [lc_query_financials, lc_search_filing]

llm = ChatAnthropic(model=MODEL, api_key=LLM_API_KEY, base_url=LLM_BASE_URL, max_tokens=1000)
llm_with_tools = llm.bind_tools(lc_tools)


def agent_node(state: MessagesState):
    # Box 1: put the rules in front of the conversation and ask the model what to do next
    response = llm_with_tools.invoke([SystemMessage(AGENT_PROMPT)] + state["messages"])
    return {"messages": [response]}


# Draw the flowchart: agent → (tool requested?) → tools → back to agent, or finish
builder = StateGraph(MessagesState)
builder.add_node("agent", agent_node)
builder.add_node("tools", ToolNode(lc_tools))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
graph = builder.compile()


def run_graph(question):
    # Returns the answer and a trace, the same shape as run_agent
    result = graph.invoke(
        {"messages": [{"role": "user", "content": question}]},
        {"recursion_limit": 12},
    )

    trace = []
    for msg in result["messages"]:
        calls = getattr(msg, "tool_calls", None) or []
        for call in calls:
            trace.append({"tool": call["name"], "input": call["args"]})

    final = result["messages"][-1].content
    if isinstance(final, list):   # sometimes the answer comes as a list of blocks
        text = ""
        for block in final:
            if isinstance(block, dict):
                text += block.get("text", "")
        final = text
    return final, trace