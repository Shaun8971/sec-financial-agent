# src/rag.py
# Each company's latest 10-K: download, chunk, index in Chroma, search, and answer with citations.
import os
import requests
import pandas as pd
import chromadb
from bs4 import BeautifulSoup

from src.config import SEC_HEADERS, FILINGS_DIR, CHROMA_PATH, TICKERS, MODEL, client

COLLECTION_NAME = "filings_10k"
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)


def get_collection():
    # Return the 10-K collection, creating it if it doesn't exist yet
    return chroma_client.get_or_create_collection(name=COLLECTION_NAME)


def filing_path(ticker):
    # Where each company's 10-K text is saved, e.g. data/filings/ORCL_10K.txt
    return os.path.join(FILINGS_DIR, f"{ticker}_10K.txt")


def chunk_text(text, chunk_size=1200, overlap=200):
    # Split text into pieces of about chunk_size characters, each repeating the
    # last 'overlap' characters of the previous one, so no sentence is lost at a boundary
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


RAG_PROMPT = """You answer questions about companies' 10-K filings.

Use ONLY the excerpts provided. Each excerpt is labeled with its company and chunk number.
After each claim, cite the excerpt it came from, like [ORCL chunk 412].
If the excerpts don't contain the answer, reply exactly:
"The provided excerpts don't answer this question."
Do not use outside knowledge, and do not guess."""


def download_10k_text(ticker, cik):
    # Find a company's latest 10-K, download it, convert it to plain text, and save it
    padded = str(cik).zfill(10)
    sub = requests.get(f"https://data.sec.gov/submissions/CIK{padded}.json",
                       headers=SEC_HEADERS, timeout=10)
    sub.raise_for_status()

    filings = pd.DataFrame(sub.json()["filings"]["recent"])
    latest = filings[filings["form"] == "10-K"].sort_values("filingDate", ascending=False).iloc[0]

    accession = latest["accessionNumber"].replace("-", "")
    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{latest['primaryDocument']}"
    doc = requests.get(doc_url, headers=SEC_HEADERS, timeout=30)
    doc.raise_for_status()

    soup = BeautifulSoup(doc.text, "html.parser")
    for hidden_block in soup.find_all("ix:header"):   # remove the hidden data tags
        hidden_block.decompose()

    clean_lines = []
    for line in soup.get_text(separator="\n").splitlines():
        line = line.strip()
        if line:
            clean_lines.append(line)
    text = "\n".join(clean_lines)

    os.makedirs(FILINGS_DIR, exist_ok=True)   # create data/filings if it doesn't exist
    with open(filing_path(ticker), "w", encoding="utf-8") as f:
        f.write(text)
    return text


def build_index():
    # Rebuild the index from scratch, with every company's 10-K
    try:
        chroma_client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass   # nothing to delete the first time; that's fine
    collection = get_collection()

    for ticker in TICKERS:
        with open(filing_path(ticker), encoding="utf-8") as f:
            chunks = chunk_text(f.read())

        ids = []
        metadatas = []
        for i in range(len(chunks)):
            ids.append(f"{ticker}_10k_{i}")
            # The 'ticker' label is what lets a search stay inside one company's filing
            metadatas.append({"ticker": ticker, "source": f"{ticker} 10-K", "chunk": i})
        collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)

    return collection.count()


def retrieve(query, ticker=None, n_results=4):
    # Find the closest chunks. If a ticker is given, only search that company's chunks.
    collection = get_collection()
    if ticker:
        results = collection.query(query_texts=[query], n_results=n_results,
                                   where={"ticker": ticker})   # the filter: this company only
    else:
        results = collection.query(query_texts=[query], n_results=n_results)

    excerpts = ""
    used_chunks = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        label = f"{meta['ticker']} chunk {meta['chunk']}"   # e.g. "ADBE chunk 87"
        excerpts += f"[{label}]\n{doc}\n\n"
        used_chunks.append(label)
    return excerpts, used_chunks


def search_filing(query, ticker=None, n_results=4):
    # The agent's tool: only needs the excerpts. '_' means "ignore this value."
    excerpts, _ = retrieve(query, ticker, n_results)
    return excerpts


def ask_filing(question, ticker=None, n_results=4):
    # Retrieve, then have the model answer from the excerpts only, with citations
    excerpts, used_chunks = retrieve(question, ticker, n_results)
    message = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=RAG_PROMPT,
        messages=[{"role": "user", "content": f"Question: {question}\n\nExcerpts:\n\n{excerpts}"}],
    )
    answer = ""
    for block in message.content:
        if block.type == "text":
            answer += block.text
    return answer, used_chunks


def get_chunk(ticker, chunk_number):
    # Look up one chunk's text, to check a citation like [ADBE chunk 87]
    result = get_collection().get(ids=[f"{ticker}_10k_{chunk_number}"])
    if result["documents"]:
        return result["documents"][0]
    return None