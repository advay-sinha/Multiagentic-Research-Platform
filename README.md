# Autonomous Multi-Agentic Research Platform

An evidence-grounded AI research assistant that uses a multi-agent pipeline to answer queries with citations, claim-level verification, and full execution traces.

**How it works:** You submit a research question. The system decomposes it into a retrieval plan, fetches evidence from indexed documents or the web, writes a grounded answer, critiques it for gaps, and verifies each claim against the evidence. Every step is traced, timed, and returned to the frontend for inspection.

**Pipeline:** Planner → Retriever → Writer → Critic → Verifier

**What it produces:**
- Grounded answer with inline citations
- Citation list with source metadata (title, URL, snippet, date)
- Claim-evidence verification table with verdicts (supported / unsupported / partial)
- Confidence score and refusal flag
- Per-stage latency metrics
- Full agent execution trace

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Frontend  (Next.js · Tailwind · SSE streaming)     │
│  Chat · Sources · Agent Trace · Verification · Metrics│
└────────────────────┬────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────────┐
│  FastAPI  backend/app/main.py  (port 8000)          │
│  /v1/health  /v1/query  /v1/query/stream            │
│  /v1/search  /v1/documents  /v1/traces/{id}         │
└────────┬────────────────────┬───────────────────────┘
         │                    │
┌────────▼──────┐   ┌────────▼──────────────────────┐
│  langgraph_   │   │  pgvector_store.py             │
│  stub.py      │   │  PostgreSQL + pgvector         │
│  Planner      │   │  embeddings.py → Gemini API    │
│  Retriever    │   │  (gemini-embedding-001, 768d)  │
│  Writer       │   └───────────────────────────────┘
│  Critic       │
│  Verifier     │   ┌───────────────────────────────┐
└───────────────┘   │  trace_store.py (SQLite)       │
         │          │  data/traces.db                │
┌────────▼──────┐   └───────────────────────────────┘
│  llm_client   │
│  Gemini REST  │
│  (gemini-2.0- │
│   flash)      │
└───────────────┘
```

---

## Project Structure

```
Multiagentic-Research-Platform/
├── backend/
│   ├── app/
│   │   ├── data/                  # SQLite trace store
│   │   ├── search_providers/      # bing.py, serpapi.py
│   │   ├── doc_store.py           # In-memory fallback (unused)
│   │   ├── embeddings.py          # Gemini embedContent REST (batch)
│   │   ├── extraction.py          # trafilatura + readability-lxml
│   │   ├── langgraph_stub.py      # Planner→Retriever→Writer→Critic→Verifier
│   │   ├── llm_client.py          # Gemini / OpenAI / stub LLM client
│   │   ├── logging_utils.py       # Structured JSON logging
│   │   ├── main.py                # FastAPI app + routes
│   │   ├── pgvector_store.py      # PostgreSQL + pgvector vector store
│   │   ├── schemas.py             # Pydantic request/response models
│   │   ├── settings.py            # Environment-driven config
│   │   └── trace_store.py         # SQLite trace persistence
│   ├── evals/                     # Evaluation harness + baseline dataset
│   ├── tests/                     # pytest test suite
│   └── requirements.txt
├── frontend/
│   ├── src/app/
│   │   ├── page.tsx               # Main UI (Chat / Sources / Metrics)
│   │   └── layout.tsx             # App shell + dark theme
│   └── src/design/                # Stitch exports + theme tokens
├── docs/                          # Architecture and planning docs
├── scripts/                       # Dev helper scripts (.bat)
├── .env.example                   # Environment variable template
├── docker-compose.yml             # One-command full stack setup
├── Dockerfile                     # Backend container
├── pytest.ini
└── README.md
```

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- (Optional) Docker & Docker Compose
- (Optional) PostgreSQL with pgvector extension

### Option A: Docker Compose (recommended)

The easiest way to run the full stack with PostgreSQL + pgvector:

```bash
cp .env.example .env
# Edit .env — at minimum set GEMINI_API_KEY for real LLM responses

docker compose up --build
```

This starts:
- **postgres** on port 5432 (pgvector/pgvector:pg16)
- **backend** on port 8000 (FastAPI)
- **frontend** on port 3000 (Next.js)

Visit [http://localhost:3000](http://localhost:3000).

### Option B: Local Development

#### 1. Backend

```bash
python -m venv venv
# Linux/Mac: source venv/bin/activate
# Windows: venv\Scripts\activate
pip install -r backend/requirements.txt

cp .env.example .env
# Edit .env with your API keys

uvicorn backend.app.main:app --reload --port 8000
```

The backend starts without any keys — LLM falls back to stub responses, vector search returns empty results.

#### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Visit [http://localhost:3000](http://localhost:3000).

#### 3. PostgreSQL + pgvector (optional)

For document indexing and vector search:

```bash
docker run --name research-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=research \
  -p 5432:5432 \
  -d pgvector/pgvector:pg16
```

Set in `.env`:
```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/research
```

The pgvector extension is created automatically at startup. If using an existing Postgres, run `CREATE EXTENSION vector;` as superuser.

---

## Environment Variables

Only the active variables (ones the code actually reads):

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini`, `openai`, or `stub` |
| `GEMINI_API_KEY` | — | Google AI API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model for generation |
| `OPENAI_API_KEY` | — | Used when `LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model for generation |
| `EMBEDDING_MODEL` | `models/gemini-embedding-001` | Embedding model |
| `EMBEDDING_DIM` | `768` | Embedding vector dimension |
| `DATABASE_URL` | — | PostgreSQL connection string |
| `BING_API_KEY` | — | Bing Search API v7 key |
| `SERPAPI_KEY` | — | SerpAPI key (Google/Bing engine) |
| `CORS_ALLOW_ORIGIN` | `http://localhost:3000` | Allowed CORS origin |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000` | Frontend → backend URL |
| `MAX_AGENT_ITERATIONS` | `5` | Max Writer→Critic→Verifier loops |
| `LOG_LEVEL` | `info` | Logging level |

See `.env.example` for the full list including reserved/future variables.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check |
| `POST` | `/v1/query` | Research query (blocking) |
| `POST` | `/v1/query/stream` | Research query (SSE streaming) |
| `POST` | `/v1/search` | Web search + document indexing |
| `POST` | `/v1/documents` | Upload and index a document |
| `GET` | `/v1/documents/{id}` | Document metadata |
| `GET` | `/v1/traces/{id}` | Agent trace by ID |

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Example Requests

```bash
# Health check
curl http://localhost:8000/v1/health

# Research query
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the key findings on transformer attention mechanisms?"}'

# Streamed query (SSE)
curl -N -X POST http://localhost:8000/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "Summarise recent advances in RAG architectures."}'

# Upload document
curl -X POST http://localhost:8000/v1/documents \
  -F "file=@sample.txt"

# Web search + index
curl -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "latest guidance on X", "max_results": 5}'
```

### Response Shape

`POST /v1/query` returns:

```json
{
  "answer_id": "ans-a1b2c3d4",
  "query": "...",
  "answer": "Grounded answer text...",
  "citations": [
    {
      "citation_id": "cit-000",
      "source_id": "doc-...",
      "title": "Source title",
      "url": "https://...",
      "published_at": "2024-01-01",
      "snippet": "...",
      "chunk_start": 0,
      "chunk_end": 500,
      "answer_span_start": null,
      "answer_span_end": null
    }
  ],
  "claim_verifications": [
    {
      "claim_id": "clm-001",
      "claim_text": "...",
      "verdict": "supported",
      "evidence_chunk_ids": ["chunk-id"],
      "confidence": 0.66,
      "notes": "..."
    }
  ],
  "confidence_score": 0.82,
  "refusal": false,
  "trace_id": "trace-a1b2c3d4",
  "metrics": {
    "total_duration_ms": 1240.5,
    "stages": [
      {"stage": "planner", "duration_ms": 320.1},
      {"stage": "retriever", "duration_ms": 45.2},
      {"stage": "writer", "duration_ms": 610.8},
      {"stage": "critic", "duration_ms": 180.4},
      {"stage": "verifier", "duration_ms": 84.0}
    ],
    "evidence_count": 4,
    "citation_count": 4,
    "claim_count": 1
  }
}
```

---

## Tests

```bash
python -m pytest backend/tests/ -v
```

| Test | Condition |
|---|---|
| `test_health` | Always runs |
| `test_query_stub_mode` | Always runs (validates full pipeline in stub mode) |
| `test_upload_query_trace_flow` | Skipped without pgvector |
| `test_web_search_indexes_results` | Skipped without pgvector + search API key |

---

## Evaluation Harness

Run baseline evaluations against a running backend:

```bash
python -m backend.evals.run
```

Metrics reported:
- **Faithfulness** — expected facts found in answer (substring match)
- **Citation coverage** — expected citations found in response
- **Hallucination score** — fraction of answer sentences grounded in evidence
- **Latency** — round-trip time per query

Override dataset or API base:

```bash
python -m backend.evals.run backend/evals/baseline.jsonl http://localhost:8000
```

---

## Docker

### Backend only

```bash
docker build -t research-platform .
docker run -p 8000:8000 --env-file .env research-platform
```

### Full stack (Docker Compose)

```bash
docker compose up --build
```

Starts PostgreSQL (pgvector), backend (port 8000), and frontend (port 3000).
