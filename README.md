# Autonomous Multi-Agentic Research Platform

An evidence-grounded AI research assistant that uses a five-stage agent pipeline to answer queries with citations, claim-level verification, and full execution traces.

---

## How It Works

You submit a research question. The system runs it through five specialized agents in sequence. Each agent has a single responsibility, and the pipeline iterates until the answer meets a confidence threshold or hits the iteration cap. Every step is traced, timed, and returned for inspection.

---

## The Five-Stage Pipeline

```
  Query
    │
    ▼
┌──────────┐   ┌────────────┐   ┌──────────┐   ┌──────────┐   ┌────────────┐
│ 1.Planner│──▶│2.Retriever │──▶│ 3.Writer │──▶│ 4.Critic │──▶│5.Verifier  │
└──────────┘   └────────────┘   └──────────┘   └──────────┘   └────────────┘
                                      ▲               │
                                      └───────────────┘
                                     (loop until confident)
```

### Step 1 — Planner

**Role:** Decomposes the user's research question into a retrieval plan.

- Receives the raw query string
- Prompts the LLM to generate a JSON array of `PlanStep` objects, each with a `question` and `search_query`
- Produces 1–3 retrieval sub-queries that guide what evidence to fetch
- Falls back to treating the raw LLM output as a single search query if JSON parsing fails

**Output:** `List[PlanStep]` — structured retrieval plan  
**Trace event:** `evt-plan-001` (agent: `Planner`, type: `plan`)

### Step 2 — Retriever

**Role:** Fetches evidence from the vector store using the planner's search queries.

- Takes the first `PlanStep.search_query` from the plan
- Runs a cosine-similarity search against PostgreSQL + pgvector (`embeddings.py` generates vectors via Gemini `embedContent` API)
- Returns ranked document chunks with metadata (source ID, title, URL, published date, text snippet, chunk offsets, similarity score)
- Returns an empty list gracefully if no database is configured (stub mode)

**Output:** `List[EvidenceChunk]` — ranked evidence with metadata  
**Trace event:** `evt-retrieval-001` (agent: `Retriever`, type: `retrieve`)

### Step 3 — Writer

**Role:** Produces a grounded answer using only the retrieved evidence.

- Constructs a prompt with the query and up to 400 characters per evidence chunk
- Instructs the LLM to write an answer strictly grounded in the provided evidence
- Generates inline citations mapping each evidence chunk to a `Citation` object with source metadata, text snippet, chunk offsets, and best-effort answer span alignment
- Falls back to a summary of the first evidence chunk if the LLM returns nothing

**Output:** `{ draft_answer: str, citations: List[Citation] }`  
**Trace event:** `evt-writer-{iteration}` (agent: `Writer`, type: `write`)

### Step 4 — Critic

**Role:** Reviews the draft answer for gaps, unsupported claims, and missing evidence.

- Receives the query, the writer's draft answer, and the evidence chunks
- Prompts the LLM to identify weaknesses and return a short critique
- The critique text feeds back into the next Writer iteration (if the loop continues)

**Output:** `str` — critique text (up to 400 chars logged in trace)  
**Trace event:** `evt-critic-{iteration}` (agent: `Critic`, type: `critique`)

### Step 5 — Verifier

**Role:** Extracts claims from the answer and verifies each one against the evidence.

- Prompts the LLM to identify up to 3 key claims and return a JSON array with `claim_text`, `verdict` (supported / unsupported / partial), `confidence` (0.0–1.0), and `notes`
- Falls back to a heuristic single-claim verdict if JSON parsing fails
- Computes a composite `confidence_score` from the claim verdicts:
  - `0.0` if no evidence was found
  - `0.2` if no claims were extracted
  - `0.4 + 0.6 × (supported_ratio)` otherwise
- Sets `refusal = true` when confidence < 0.4 (the answer is not trustworthy enough to present)

**Output:** `List[ClaimVerification]` + `confidence_score` + `refusal` flag  
**Trace event:** `evt-verify-{iteration}` (agent: `Verifier`, type: `verify`)

### Iteration Loop

Steps 3–5 (Writer → Critic → Verifier) run in a loop controlled by two stop conditions:

1. **Confidence threshold:** Loop exits early when `confidence_score ≥ 0.4` (i.e., `refusal = false`)
2. **Iteration cap:** Maximum `MAX_AGENT_ITERATIONS` loops (default: 5, configurable via env var)

If the loop exhausts all iterations without reaching sufficient confidence, the response is returned with `refusal: true`.

---

## What the Platform Produces

Every query returns a structured `QueryResponse` containing:

| Field | Description |
|---|---|
| `answer` | Grounded answer text with inline citation references |
| `citations` | List of sources with title, URL, snippet, published date, chunk offsets, and optional answer span alignment |
| `claim_verifications` | Claim-level verification table — each claim has a verdict (supported/unsupported/partial), confidence, and justification notes |
| `confidence_score` | Composite score (0.0–1.0) derived from claim verification verdicts |
| `refusal` | `true` if the system determines the answer is not sufficiently grounded |
| `trace_id` | Links to the full execution trace (retrievable via `/v1/traces/{id}`) |
| `metrics` | Per-stage latency (`planner`, `retriever`, `writer`, `critic`, `verifier`), total duration, evidence/citation/claim counts |

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
│  (gemini-2.5- │
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
├── scripts/                       # Dev helper scripts
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
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model for generation |
| `OPENAI_API_KEY` | — | Used when `LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model for generation |
| `EMBEDDING_MODEL` | `models/gemini-embedding-002` | Embedding model |
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
| `POST` | `/v1/query` | Research query (blocking) — runs full 5-stage pipeline |
| `POST` | `/v1/query/stream` | Research query (SSE streaming) — same pipeline, streamed output |
| `POST` | `/v1/search` | Web search + document indexing into pgvector |
| `POST` | `/v1/documents` | Upload and index a document |
| `GET` | `/v1/documents/{id}` | Document metadata |
| `GET` | `/v1/traces/{id}` | Agent trace by ID — full pipeline execution log |

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Example Requests

```bash
# Health check
curl http://localhost:8000/v1/health

# Research query (runs Planner→Retriever→Writer→Critic→Verifier)
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the key findings on transformer attention mechanisms?"}'

# Streamed query (SSE — trace events → citations → answer chunks → final response)
curl -N -X POST http://localhost:8000/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "Summarise recent advances in RAG architectures."}'

# Upload document (indexed into pgvector for retrieval)
curl -X POST http://localhost:8000/v1/documents \
  -F "file=@backend/evals/data/sample.txt"

# Web search + index (fetches, extracts, embeds, and stores results)
curl -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "latest guidance on X", "max_results": 5}'

# Retrieve execution trace
curl http://localhost:8000/v1/traces/trace-a1b2c3d4
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

## Frontend Views

The frontend provides five panels mapped to the pipeline output:

| View | What it shows |
|---|---|
| **Chat Interface** | Submit queries, stream answers with inline citation chips |
| **Sources Panel** | Glass-style source cards with title, URL, snippet, score, date |
| **Agent Trace Viewer** | Pipeline timeline showing each agent step with per-stage latency |
| **Verification Table** | Claim-evidence table with verdict badges (supported/unsupported/partial) |
| **Metrics Dashboard** | Metric cards (confidence, evidence count, latency) + stage latency bar chart |

---

## Tests

```bash
python -m pytest backend/tests/ -v
```

| Test | Condition |
|---|---|
| `test_health` | Always runs |
| `test_query_stub_mode` | Always runs (validates full 5-stage pipeline in stub mode) |
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
- **Hallucination score** — fraction of answer sentences grounded in evidence (word-overlap)
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

---

## Manual Verification Steps

Use these steps to verify the platform is working correctly after setup.

### 1. Backend Health Check

```bash
curl http://localhost:8000/v1/health
```

**Expected:** `{"status": "ok", "version": "0.1.0"}`

### 2. Backend Startup Logs

When the backend starts, it should log a JSON event with:
- `"event": "startup"`
- `"llm_provider"`: `gemini`, `openai`, or `stub`
- `"database"`: `configured` or `not configured (in-memory fallback active)`
- `"search_provider"`: `bing`, `serpapi`, or `none`

Verify these match your `.env` configuration.

### 3. Stub Mode Query (no API keys required)

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is machine learning?"}'
```

**Verify the response contains:**
- `"answer"` — a non-empty string (stub fallback text if no Gemini key)
- `"citations"` — an array (empty if no pgvector database)
- `"claim_verifications"` — at least one entry with `claim_id`, `verdict`, `confidence`
- `"confidence_score"` — a number between 0.0 and 1.0
- `"refusal"` — `true` or `false`
- `"trace_id"` — a string starting with `trace-`
- `"metrics.stages"` — array containing entries for `planner`, `retriever`, `writer`, `critic`, `verifier`
- `"metrics.total_duration_ms"` — a positive number

### 4. SSE Streaming Query

```bash
curl -N -X POST http://localhost:8000/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain attention mechanisms."}'
```

**Verify the SSE stream emits events in this order:**
1. `event: trace_event` — one per agent step (planner, retriever, writer, critic, verifier)
2. `event: citation` — one per citation (may be zero in stub mode)
3. `event: answer_delta` — answer text in chunks
4. `event: final` — complete `QueryResponse` JSON

### 5. Trace Retrieval

After running a query, use the `trace_id` from the response:

```bash
curl http://localhost:8000/v1/traces/<trace_id>
```

**Verify the response contains:**
- `"trace_id"` — matches the requested ID
- `"query"` — the original query text
- `"events"` — array of `AgentTraceEvent` objects, each with `event_id`, `agent`, `event_type`, `timestamp`, `payload`

### 6. Document Upload and Retrieval (requires pgvector)

```bash
# Upload a document
curl -X POST http://localhost:8000/v1/documents \
  -F "file=@backend/evals/data/sample.txt"

# Note the document_id from the response, then:
curl http://localhost:8000/v1/documents/<document_id>
```

**Verify:**
- Upload returns `{"document_id": "...", "status": "indexed", "pages": 1}`
- Metadata returns `document_id`, `filename`, `uploaded_at`, `size_bytes`, `status`

### 7. Query After Document Ingestion (requires pgvector)

After uploading a document, query for its content:

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Summarize the uploaded document content."}'
```

**Verify:**
- `"citations"` is non-empty — the retriever found chunks from the uploaded document
- `"claim_verifications"` has entries with `"verdict": "supported"`
- `"confidence_score"` is above 0.4 (answer is not refused)

### 8. Web Search and Indexing (requires pgvector + search API key)

```bash
curl -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "transformer architecture", "max_results": 3}'
```

**Verify:**
- Returns `{"results": [...]}` with `source_id`, `title`, `url`, `snippet` per result
- Without a search API key, returns HTTP 503 with message: `"No search provider configured..."`

### 9. Frontend Verification

1. Open [http://localhost:3000](http://localhost:3000) in a browser
2. Verify the dark-themed UI loads with a sidebar and chat input
3. Submit a query — the answer should stream in with citation chips
4. Switch to **Sources & Verify** view — check that sources cards and the verification table render
5. Switch to **System Metrics** view — check that metric cards and the stage latency bar chart render
6. Click on the agent trace sidebar — verify the pipeline timeline shows all 5 stages with latency

### 10. Run Automated Tests

```bash
# Backend tests (2 pass, 2 skip without pgvector)
python -m pytest backend/tests/ -v

# Frontend build check
cd frontend && npm run build

# Evaluation harness (requires running backend)
python -m backend.evals.run
```

**Expected test results:**
- `test_health` — PASSED
- `test_query_stub_mode` — PASSED (validates full pipeline without external deps)
- `test_upload_query_trace_flow` — SKIPPED (requires pgvector)
- `test_web_search_indexes_results` — SKIPPED (requires pgvector + search key)
- Frontend build — exits 0 with no errors
- Eval harness — prints per-query scores for faithfulness, citation coverage, hallucination, and latency
