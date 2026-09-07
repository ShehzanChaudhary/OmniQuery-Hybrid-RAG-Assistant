# OmniQuery — Hybrid RAG Assistant

OmniQuery is a chatbot that doesn't just answer from one type of knowledge — it intelligently routes every question to the right source: unstructured documents (PDFs), structured data (Excel/SQL tables), live web search, or plain conversation. It streams answers in real time, remembers past conversations, cites its sources, suggests follow-up questions, and caches repeated queries to save cost and latency.

Built as a hands-on learning project to understand production RAG patterns end-to-end — from a basic single-file script to an async, multi-source, cached, streaming system.

---

## What it can do

- **Multi-source intelligent routing** — a single query is automatically classified and routed to the right pipeline:
  - `greeting` — small talk, handled directly
  - `document_question` — answered via semantic retrieval over uploaded PDFs (RAG)
  - `sql_question` — answered by generating and running SQL against uploaded Excel data
  - `web_search_question` — answered using live web search (Tavily) for current events / general knowledge
- **Streaming responses** (Server-Sent Events) — tokens appear as they're generated instead of one blocking response
- **Fully async pipeline** — all LLM, vector-DB, and SQL calls are non-blocking, so the server can serve multiple users concurrently
- **Session-based chat history** — persisted to disk as JSON, with a sidebar to browse and resume past conversations
- **Document & table management** — upload/list/delete PDFs and Excel files from the UI; both are indexed automatically
- **Scalable SQL retrieval** — table/column schemas are embedded and retrieved semantically, so the system stays fast and within context limits even with hundreds of tables or very wide tables. Query results are row- and column-truncated with a "partial results" note when they'd otherwise overflow the context window
- **Source citations** — document answers cite the exact PDF page(s) used; web search answers cite the source URLs
- **AI-generated follow-up questions** — after every non-greeting answer, 3 relevant follow-ups are suggested. A hybrid system also learns from real usage: once a question→follow-up pattern has been seen often enough, it's served instantly without an LLM call
- **Semantic response caching** — near-duplicate questions (different wording, same meaning) hit a cache instead of re-running the full pipeline; cache is invalidated whenever documents/tables change
- **Voice input** (Web Speech API) and math rendering (KaTeX) in the frontend
- **LLM call tracing/observability** — every LLM call (intent classification, SQL generation, follow-ups, final answers) is traced for debugging and monitoring pipeline behavior
- **Containerized deployment** — Dockerfile + entrypoint script for running the backend as a container, independent of local Python/venv setup

---

## Architecture overview

```
User question
     │
     ▼
Intent Classification (LLM) ──► uses embedded schema of available tables
     │
     ├── greeting ─────────────► direct LLM response
     │
     ├── document_question ───► rephrase (using history) → semantic retrieval (ChromaDB)
     │                          → LLM answer → citations (page numbers) appended
     │
     ├── sql_question ────────► retrieve relevant table/column schema (embeddings)
     │                          → LLM generates SQL → executed (SELECT-only, row/column capped)
     │                          → LLM turns results into a natural-language answer
     │
     └── web_search_question ─► Tavily web search → LLM synthesizes answer → source URLs appended

     │
     ▼
Follow-up questions (hybrid: historical patterns first, LLM fallback)
     │
     ▼
Response cached (semantic) + saved to session history
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI (async), Uvicorn |
| LLM access | OpenRouter (OpenAI-compatible SDK), streaming + JSON-mode calls |
| Vector store | ChromaDB — used for document chunks, table schema retrieval, follow-up pattern tracking, and semantic response cache |
| Structured data | SQLite (via pandas ingestion from Excel) |
| Web search | Tavily API |
| Prompting | Jinja2 templates (one template per pipeline stage) |
| PDF processing | pypdf (page-wise text extraction + chunking) |
| Observability | LLM call tracing across the pipeline |
| Deployment | Docker (Dockerfile + entrypoint script) |
| Frontend | Vanilla JavaScript, HTML/CSS, marked.js + DOMPurify (markdown), KaTeX (math), Web Speech API (voice input) |
| Streaming protocol | Server-Sent Events (SSE) over `fetch` + `ReadableStream` |

---

## Project structure

```
├── config/
│   └── config.py                 # env-based configuration (API keys, model names)
├── data/
│   ├── sessions/                 # one JSON file per chat session
│   └── uploads/                  # uploaded PDFs and Excel files
├── frontend/
│   ├── index.html
│   ├── script.js
│   └── style.css
├── notebooks/                    # exploratory ingestion notebooks
├── src/
│   ├── adapters/
│   │   ├── openrouter.py         # LLM chat/embedding client (sync + async + streaming)
│   │   ├── chroma_db.py          # document chunk storage & retrieval
│   │   ├── sqlite_db.py          # Excel → SQLite table management & query execution
│   │   ├── schema_index.py       # embeds table/column schemas for scalable SQL retrieval
│   │   ├── followup_tracker.py   # tracks real question→follow-up transitions
│   │   ├── response_cache.py     # semantic cache for final answers
│   │   ├── tavily_search.py      # web search client
│   │   ├── tracing.py            # LLM call tracing / observability
│   │   └── logger.py
│   ├── prompts/                  # Jinja2 templates for each pipeline stage
│   │   ├── intent_check.Jinja2
│   │   ├── rephrase_query.Jinja2
│   │   ├── final_response.jinja2
│   │   ├── sql_generation.jinja2
│   │   ├── sql_response.jinja2
│   │   ├── web_search_response.jinja2
│   │   ├── followup_questions.jinja2
│   │   └── greeting.Jinja2
│   ├── ingestion.py               # PDF ingestion (extract → chunk → embed → store)
│   ├── model.py                  # dataclasses/pydantic models (Message, Conversation, Chunk, etc.)
│   └── utils.py                   # core orchestration — routing, retrieval, generation, caching
├── main.py                        # FastAPI app & routes
├── Dockerfile
├── docker-entrypoint.sh
└── requirements.txt
```

---

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate.bat        # Windows
source venv/bin/activate         # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables (create a .env file or set in your shell)
OPENROUTER_API_KEY=your_key_here
TAVILY_API_KEY=your_key_here
MODEL=openai/gpt-4o-mini
EMBED_MODEL=openai/text-embedding-3-small
LANGFUSE_SECRET_KEY = your_key_here
LANGFUSE_PUBLIC_KEY = your_key_here
LANGFUSE_BASE_URL = "https://us.cloud.langfuse.com"

# 4. Run the backend
uvicorn main:app --reload

# 5. Serve the frontend (separate terminal, must be on a different port)
cd frontend
python -m http.server 5173
```

Open `http://127.0.0.1:5173` in your browser. Upload a PDF or Excel file from the **Documents** section to start querying it.

### Running with Docker (alternative)

```bash
docker build -t polymath .
docker run -p 8000:8000 --env-file .env polymath
```

The frontend still needs to be served separately (step 5 above) since it isn't bundled into the container.

---

## API reference (key endpoints)

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/query` | Non-streaming chat — full JSON response |
| `POST` | `/query/stream` | Streaming chat (SSE) |
| `GET` | `/sessions` | List all saved chat sessions |
| `GET` | `/sessions/{id}` | Full message history for one session |
| `GET` / `POST` / `DELETE` | `/documents` | List / upload / delete PDF documents |
| `GET` / `POST` / `DELETE` | `/tables` | List / upload / delete Excel-backed tables |

---

## Notes on design decisions

- **Why semantic (embedding-based) schema retrieval for SQL?** Dumping every table's full schema into the prompt breaks down at scale — hundreds of tables or very wide tables overflow the context window and confuse the model about which table to use. Instead, table and column descriptions are embedded once at upload time; at query time, only the top-k most relevant tables/columns are retrieved and injected into the SQL-generation prompt.
- **Why cap query results?** Even with the right table selected, a `SELECT *` on a large table can return more rows/columns than fit comfortably in context. Results are truncated (rows and, for very wide tables, columns) with an explicit note so the model doesn't silently present partial data as complete.
- **Why a hybrid follow-up system?** Pure LLM-generated follow-ups cost a call every time. Once a question→follow-up pattern has occurred often enough across real usage, it's served directly from history — no LLM call needed. New or rare questions still fall back to LLM generation.
- **Why a strict distance threshold for caching?** A cache hit that's actually wrong is worse than a cache miss (the user gets a subtly incorrect answer with no indication it was cached). The similarity threshold is tuned conservatively to avoid false-positive hits.

---

## Roadmap

- [x] Web search integration (Tavily) for current events / general knowledge
- [x] LLM call tracing / observability
- [x] Containerized deployment (Docker)
- [x] Multi-user authentication with per-user data isolation
- [ ] Guardrails against prompt injection and unsafe/out-of-scope queries
- [ ] Multi-step ("agentic") SQL for questions that need more than one query
- [ ] Migration path to a production vector DB / Redis cache for multi-instance deployments
