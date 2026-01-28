# Autonomous Agentic Research Platform — Project Plan

## 1) Vision & Success Criteria
**Goal:** Deliver a high-trust, evidence-grounded research copilot that is transparent, verifiable, and reliable.

**Success criteria**
- Answers include citations with claim-level evidence links.
- System refuses or downgrades confidence when evidence is insufficient.
- Measurable quality targets: faithfulness, citation coverage, and confidence calibration.
- Full traceability of agent decisions and retrieval pipeline.

## 2) Target Architecture (Tech Stack)
**Backend & Agents**
- Python + FastAPI (REST + streaming via SSE/WebSocket).
- LangGraph for agent orchestration (stateful graphs, retries, traceability).

**Retrieval & RAG**
- Embeddings: `text-embedding-3-large` (quality) or `text-embedding-3-small` (cost).
- Vector DB: `pgvector`.
- Web search: Bing Web Search API (primary) or SerpAPI (fallback).
- HTML fetching: `httpx` + `readability-lxml` or `trafilatura` for clean extraction.

**Storage & Caching**
- PostgreSQL for users, chats, traces, and metrics.
- Redis for search cache, retrieved-doc cache, rate limiting, and session state.
- Object storage: S3-compatible (AWS S3 / Azure Blob / MinIO).

**Observability**
- OpenTelemetry with Grafana/Loki/Prometheus.
- Structured JSON logs with request IDs.

**Frontend**
- Next.js (React + TypeScript).
- UI components: shadcn/ui.
- Markdown render with citations panel and trace viewer.

## 3) Phase Plan

### Phase 0 — Alignment & Design (1–2 weeks)
- Finalize product requirements and trust metrics.
- Define agent protocol and data contracts (Planner, Retriever, Writer, Critic, Verifier, Red-Team).
- Draft system architecture and security considerations.

**Deliverables**
- Architecture diagrams.
- Agent interaction spec.
- Evaluation rubric.

### Phase 1 — Core MVP (4–6 weeks)
- Implement Planner → Retriever → Writer pipeline using LangGraph.
- Build RAG ingestion (chunking, embeddings, pgvector indexing).
- Add web search + HTML extraction pipeline.
- MVP UI: query box, results with citations, and minimal trace view.
- Basic logging + cache layer.

**Deliverables**
- End-to-end system returning cited answers.
- FastAPI endpoints for query, retrieval, and tracing.
- Basic Next.js UI.

### Phase 2 — Verification & Trust Controls (4–6 weeks)
- Verifier agent for claim–evidence alignment.
- Critic agent for error detection and coverage gaps.
- Red-Team agent for adversarial testing and refusal triggers.
- Confidence scoring + refusal behavior in low-evidence cases.

**Deliverables**
- Claim-level verification pipeline.
- Confidence score with rationale.
- Refusal behavior for insufficient evidence.

### Phase 3 — Evaluation & Quality (3–5 weeks)
- Automated eval suite: faithfulness, citation coverage, hallucination rate.
- Regression tests for retrieval quality.
- Quality dashboards wired to production logs.

**Deliverables**
- Eval harness and dashboards.
- Quality KPIs and tuning recommendations.

### Phase 4 — Production Readiness (4–6 weeks)
- Dockerized deployment: API, worker, UI, Redis, Postgres.
- Observability integration (OpenTelemetry, Grafana, Loki, Prometheus).
- Rate limiting, auth, caching policies.
- Secure object storage handling for uploaded documents.

**Deliverables**
- Production deployment playbook.
- Monitoring and alerting configuration.
- Secure API gateway setup.

### Phase 5 — Advanced Capabilities (ongoing)
- Multi-document synthesis and cross-source comparison.
- Enterprise connectors (internal knowledge bases, SSO).
- Advanced trace UI: per-agent decision logs + evidence diffing.
- Persistent research threads and collaborative workspaces.

**Deliverables**
- Enterprise feature set and scalable retrieval.
- Mature traceability UI.

## 4) Workstreams & Ownership
**Core platform**
- FastAPI services, LangGraph workflows, RAG pipeline.

**Data & retrieval**
- Web search integration, ingestion pipeline, pgvector indexing, re-ranking.

**Trust & evaluation**
- Verification, confidence scoring, and eval suite.

**Frontend**
- Next.js UI, citations panel, trace viewer.

**Infra & observability**
- Dockerization, OpenTelemetry, logging, dashboards.

## 5) Milestones & Quality Gates
- **MVP Gate:** End-to-end flow with citations + trace logs.
- **Trust Gate:** Claim-level verification + refusal behavior.
- **Quality Gate:** Minimum scores for faithfulness/citation coverage.
- **Production Gate:** Monitoring, rate limiting, and secure deployments.

## 6) Risks & Mitigations
- **Hallucinations:** Strict claim–evidence linking + Verifier agent.
- **Search drift:** Freshness-aware re-querying + cache invalidation policies.
- **Latency:** Async retrieval pipeline + streaming responses.
- **Cost:** embedding tier switch + cached retrieval + aggressive dedup.

## 7) Next Actions
- Confirm evaluation rubric thresholds (faithfulness/citation coverage).
- Pick initial LLM vendor and budget model for tracing + evaluation.
- Draft API contracts for retrieval, answer, and trace endpoints.

## 8) API Contract Draft (FastAPI)

### 8.1 Authentication
- **Header:** `Authorization: Bearer <token>`
- **Request ID:** `X-Request-ID` (optional; generated if missing)

### 8.2 Common Types

**Citation**
```json
{
  "citation_id": "cit-001",
  "source_id": "src-123",
  "title": "WHO Guidance on X",
  "url": "https://example.com/page",
  "published_at": "2024-01-15T00:00:00Z",
  "snippet": "Relevant excerpt...",
  "chunk_start": 120,
  "chunk_end": 340
}
```

**EvidenceChunk**
```json
{
  "source_id": "src-123",
  "chunk_id": "chunk-7",
  "text": "Extracted content...",
  "score": 0.82,
  "metadata": {
    "url": "https://example.com/page",
    "title": "Example Page",
    "published_at": "2024-01-15T00:00:00Z"
  }
}
```

**ClaimVerification**
```json
{
  "claim_id": "clm-001",
  "claim_text": "The study reports a 12% reduction.",
  "verdict": "supported",
  "evidence_chunk_ids": ["chunk-7", "chunk-9"],
  "confidence": 0.86,
  "notes": "Directly stated in the abstract."
}
```

**AgentTraceEvent**
```json
{
  "event_id": "evt-001",
  "agent": "Retriever",
  "event_type": "search",
  "timestamp": "2024-05-01T12:00:00Z",
  "payload": {
    "query": "site:who.int vaccination efficacy 2023",
    "result_count": 10
  }
}
```

### 8.3 Endpoints

#### POST `/v1/query`
Submit a question and receive an evidence-grounded answer with citations and verification.

**Request**
```json
{
  "query": "What is the latest guidance on X?",
  "user_id": "usr-123",
  "session_id": "sess-456",
  "documents": ["doc-001", "doc-002"],
  "options": {
    "stream": false,
    "max_sources": 8,
    "temperature": 0.2,
    "embedding_model": "text-embedding-3-large",
    "search_provider": "bing",
    "enable_verifier": true
  }
}
```

**Response**
```json
{
  "answer_id": "ans-001",
  "query": "What is the latest guidance on X?",
  "answer": "According to ...",
  "citations": [
    {
      "citation_id": "cit-001",
      "source_id": "src-123",
      "title": "WHO Guidance on X",
      "url": "https://example.com/page",
      "published_at": "2024-01-15T00:00:00Z",
      "snippet": "Relevant excerpt...",
      "chunk_start": 120,
      "chunk_end": 340
    }
  ],
  "claim_verifications": [
    {
      "claim_id": "clm-001",
      "claim_text": "The study reports a 12% reduction.",
      "verdict": "supported",
      "evidence_chunk_ids": ["chunk-7", "chunk-9"],
      "confidence": 0.86,
      "notes": "Directly stated in the abstract."
    }
  ],
  "confidence_score": 0.78,
  "refusal": false,
  "trace_id": "trace-789"
}
```

#### POST `/v1/query/stream`
Streaming response with SSE or WebSocket. Emits incremental tokens and events.

**SSE Event Types**
- `answer_delta` — partial answer tokens
- `citation` — incremental citation list updates
- `trace_event` — agent trace events
- `final` — final response payload

**Example SSE event**
```
event: answer_delta
data: {"text": "According to ..."}
```

#### POST `/v1/search`
Perform a web search + extraction pipeline; returns ranked sources.

**Request**
```json
{
  "query": "latest guidance on X",
  "search_provider": "bing",
  "freshness": "month",
  "max_results": 10
}
```

**Response**
```json
{
  "results": [
    {
      "source_id": "src-123",
      "title": "WHO Guidance on X",
      "url": "https://example.com/page",
      "published_at": "2024-01-15T00:00:00Z",
      "snippet": "Relevant excerpt..."
    }
  ]
}
```

#### POST `/v1/documents`
Upload a document for private retrieval.

**Request** (multipart form-data)
- `file`: binary
- `metadata`: JSON string (optional)

**Response**
```json
{
  "document_id": "doc-001",
  "status": "indexed",
  "pages": 12
}
```

#### GET `/v1/documents/{document_id}`
Fetch metadata for an uploaded document.

**Response**
```json
{
  "document_id": "doc-001",
  "filename": "paper.pdf",
  "uploaded_at": "2024-05-01T12:00:00Z",
  "size_bytes": 340112,
  "status": "indexed"
}
```

#### GET `/v1/traces/{trace_id}`
Retrieve the full agent trace for a query.

**Response**
```json
{
  "trace_id": "trace-789",
  "query": "What is the latest guidance on X?",
  "events": [
    {
      "event_id": "evt-001",
      "agent": "Retriever",
      "event_type": "search",
      "timestamp": "2024-05-01T12:00:00Z",
      "payload": {
        "query": "site:who.int vaccination efficacy 2023",
        "result_count": 10
      }
    }
  ]
}
```

#### GET `/v1/health`
Health check for readiness/liveness.

**Response**
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### 8.4 Error Schema
```json
{
  "error": {
    "code": "invalid_request",
    "message": "Missing query field",
    "details": {
      "field": "query"
    }
  }
}
```

### 8.5 Tracing Payload Fields
- `trace_id` — correlation ID across services.
- `events` — ordered list of agent events.
- `agent` — Planner | Retriever | Writer | Critic | Verifier | Red-Team.
- `event_type` — `plan`, `search`, `retrieve`, `rank`, `write`, `critique`, `verify`, `refuse`.
- `payload` — event-specific fields (query, scores, doc IDs, claim IDs).

## 9) LangGraph Agent Flow Specification (Recommended)

### 9.1 State Schema
**State fields**
- `query`: raw user question
- `plan`: structured sub-questions + search queries
- `evidence`: retrieved chunks + metadata
- `draft_answer`: initial response
- `citations`: citation list
- `claim_verifications`: claim-level verdicts
- `confidence_score`: float 0–1
- `refusal`: boolean
- `trace_id`: correlation ID

### 9.2 Agent Nodes
**Planner**
- Input: `query`
- Output: `plan` (sub-questions, search queries, filters)

**Retriever**
- Input: `plan`
- Output: `evidence` (ranked chunks + metadata)

**Writer**
- Input: `query`, `evidence`
- Output: `draft_answer`, `citations`

**Critic**
- Input: `draft_answer`, `evidence`
- Output: critique notes, uncovered claims

**Verifier**
- Input: `draft_answer`, `evidence`
- Output: `claim_verifications`

**Red-Team**
- Input: `draft_answer`, `claim_verifications`
- Output: potential failure modes, refusal suggestion

### 9.3 Control Flow
1. **Planner** creates a step-by-step plan with retrieval queries.
2. **Retriever** executes web + document retrieval, returns ranked evidence.
3. **Writer** composes a draft answer with citations.
4. **Critic** checks for missing evidence, contradictions, or low coverage.
5. **Verifier** links claims to evidence chunks and assigns verdicts.
6. **Red-Team** attempts to identify unsupported claims or risky outputs.
7. **Decision Gate**: If confidence < threshold or critical claims unsupported, return refusal or request clarification.
8. **Finalize**: Produce answer, citations, verification table, and trace.

### 9.4 Retries & Routing
- If Retriever coverage < threshold, loop back with expanded queries.
- If Verifier flags unsupported claims, send Writer a constrained rewrite.
- If Red-Team flags high risk, trigger refusal or ask for more sources.

### 9.5 Trace Events (Recommended)
- `plan_created`
- `search_started` / `search_completed`
- `retrieval_completed`
- `draft_written`
- `critique_generated`
- `verification_completed`
- `redteam_completed`
- `final_decision`