# Autonomous Multi-Agentic Research Platform — Project Plan

## Overview

An AI research assistant that produces evidence-grounded answers by orchestrating multiple specialized agents in a pipeline. Each query goes through planning, retrieval, writing, critique, and verification stages, producing a structured response with citations, claim-level verdicts, confidence scores, and full execution traces.

## Agent Pipeline

```
Query → Planner → Retriever → Writer → Critic → Verifier → Response
                                  ↑                  │
                                  └──── loop ─────────┘
                              (up to MAX_ITERATIONS)
```

### Agent Roles

| Agent | Input | Output | Purpose |
|-------|-------|--------|---------|
| **Planner** | User query | `[{question, search_query}]` | Decomposes query into retrieval steps |
| **Retriever** | Plan steps | Evidence chunks | Fetches relevant documents from pgvector |
| **Writer** | Query + evidence | Draft answer + citations | Writes a grounded answer using evidence |
| **Critic** | Query + answer + evidence | Critique text | Reviews for missing evidence or unsupported claims |
| **Verifier** | Answer + evidence | Claim verdicts | Labels claims as supported/unsupported/partial |

The Writer → Critic → Verifier loop repeats until confidence exceeds 0.4 or the iteration cap is reached.

## Technology Stack

- **Backend:** Python 3.11+, FastAPI, PostgreSQL + pgvector
- **Frontend:** Next.js, React, Tailwind CSS
- **LLM:** Gemini REST API (default), OpenAI (optional), stub fallback
- **Embeddings:** Gemini embedContent API (768-dim vectors)
- **Search:** Bing Search API, SerpAPI (optional)
- **Tracing:** SQLite-backed trace store
- **Streaming:** Server-Sent Events (SSE)

## Implementation Phases

1. **Backend Startup** — FastAPI app, health endpoint, settings, error handling
2. **Agent Orchestration** — Pipeline loop with iteration cap and confidence-based stopping
3. **Retrieval Layer** — pgvector store, Gemini embeddings, chunking, web search integration
4. **Verification & Metrics** — Claim-evidence verification, per-stage latency, trace logging
5. **API Contracts** — Pydantic schemas aligned between backend and frontend
6. **Frontend** — Next.js dashboard with Chat, Sources, Verification Table, Trace Viewer, Metrics
7. **Evaluation** — Faithfulness, citation coverage, hallucination detection, latency measurement
8. **Polish** — Docker Compose, documentation, .env cleanup, stale code removal

## Graceful Degradation

The system runs at any configuration level:
- **No API keys:** Stub LLM responses, empty retrieval, full pipeline still executes
- **LLM key only:** Real generation but no vector search
- **LLM + DB:** Full retrieval and generation
- **LLM + DB + search keys:** Full pipeline including web search and document indexing
