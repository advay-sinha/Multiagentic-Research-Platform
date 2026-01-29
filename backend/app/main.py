from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, AsyncGenerator, Dict, Iterable, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .extraction import fetch_and_extract
from .langgraph_stub import GraphState, TraceEvent, run_graph
from .logging_utils import log_event, setup_logging
from .pgvector_store import add_document, add_web_document, get_document, init_db, search as pg_search
from .search_providers.bing import BingSearchProvider
from .search_providers.serpapi import SerpApiSearchProvider
from .schemas import (
    AgentTraceEvent,
    ClaimVerification,
    DocumentMetadataResponse,
    DocumentUploadResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    TraceResponse,
)
from .trace_store import TRACE_STORE

app = FastAPI(title="Autonomous Agentic Research Platform", version="0.1.0")
logger = setup_logging()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("CORS_ALLOW_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    init_db()


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    log_event(
        logger,
        {
            "event": "request_started",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        },
    )
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    response.headers["X-Request-ID"] = request_id
    log_event(
        logger,
        {
            "event": "request_completed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.get("/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


def _dump_model(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _chunk_answer(text: str, chunk_size: int = 80) -> Iterable[str]:
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


def _build_claim_verifications(claims: list[dict[str, Any]]) -> list[ClaimVerification]:
    return [ClaimVerification(**claim) for claim in claims]


def _build_query_response(payload: QueryRequest, graph_state: GraphState, trace_id: str) -> QueryResponse:
    return QueryResponse(
        answer_id=f"ans-{uuid.uuid4().hex[:8]}",
        query=payload.query,
        answer=graph_state.draft_answer,
        citations=graph_state.citations,
        claim_verifications=_build_claim_verifications(graph_state.claim_verifications),
        confidence_score=graph_state.confidence_score,
        refusal=graph_state.refusal,
        trace_id=trace_id,
    )


def _trace_events_to_payload(events: list[TraceEvent]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event.event_id,
            "agent": event.agent,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "payload": event.payload,
        }
        for event in events
    ]


def _resolve_search_provider() -> Optional[Any]:
    bing_key = os.environ.get("BING_API_KEY")
    serp_key = os.environ.get("SERPAPI_KEY")
    if bing_key:
        return BingSearchProvider(bing_key)
    if serp_key:
        return SerpApiSearchProvider(serp_key)
    return None


@app.post("/v1/query", response_model=QueryResponse)
async def query(payload: QueryRequest) -> QueryResponse:
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    graph_state = run_graph(payload.query, payload.options.max_sources)
    response = _build_query_response(payload, graph_state, trace_id)

    # TODO: Integrate real model inference, verification pipeline, and refusal handling.
    TRACE_STORE.save_trace(trace_id, payload.query, _trace_events_to_payload(graph_state.trace_events))
    return response


@app.post("/v1/query/stream")
async def query_stream(payload: QueryRequest) -> StreamingResponse:
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    graph_state = run_graph(payload.query, payload.options.max_sources)
    response = _build_query_response(payload, graph_state, trace_id)

    TRACE_STORE.save_trace(trace_id, payload.query, _trace_events_to_payload(graph_state.trace_events))

    async def event_stream() -> AsyncGenerator[str, None]:
        for event in graph_state.trace_events:
            data = {
                "event_id": event.event_id,
                "agent": event.agent,
                "event_type": event.event_type,
                "timestamp": event.timestamp,
                "payload": event.payload,
            }
            yield f"event: trace_event\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"
        for citation in response.citations:
            yield f"event: citation\ndata: {json.dumps(_dump_model(citation), ensure_ascii=True)}\n\n"
        for chunk in _chunk_answer(response.answer):
            yield f"event: answer_delta\ndata: {json.dumps({'text': chunk}, ensure_ascii=True)}\n\n"
        yield f"event: final\ndata: {json.dumps(_dump_model(response), ensure_ascii=True)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/v1/search", response_model=SearchResponse)
async def search(payload: SearchRequest) -> SearchResponse:
    # TODO: Add provider tuning and result filtering.
    provider = _resolve_search_provider()
    if provider is None:
        raise HTTPException(status_code=500, detail="Search provider API key not configured")

    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    search_results = provider.search(payload.query, payload.max_results)
    trace_events: list[TraceEvent] = [
        TraceEvent(
            event_id="evt-search-001",
            agent="Retriever",
            event_type="search",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            payload={"query": payload.query, "result_count": len(search_results)},
        )
    ]

    for index, result in enumerate(search_results):
        extracted = fetch_and_extract(result["url"], result["title"], result.get("published_at"))
        if not extracted:
            continue
        add_web_document(
            url=extracted.url,
            title=extracted.title,
            text=extracted.text,
            published_at=extracted.published_at,
            metadata={"source_rank": index, "query": payload.query},
        )
        trace_events.append(
            TraceEvent(
                event_id=f"evt-extract-{index:03d}",
                agent="Retriever",
                event_type="retrieve",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                payload={"url": extracted.url, "status": "indexed"},
            )
        )

    TRACE_STORE.save_trace(trace_id, payload.query, _trace_events_to_payload(trace_events))

    rows = pg_search(payload.query, limit=payload.max_results)
    results = [
        SearchResult(
            source_id=row["document_id"],
            title=row["title"],
            url=row["url"],
            published_at=row["published_at"],
            snippet=row["text"][:200],
        )
        for row in rows
    ]
    return SearchResponse(results=results)


@app.post("/v1/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(default=None),
) -> DocumentUploadResponse:
    raw_bytes = await file.read()
    text = raw_bytes.decode("utf-8", errors="ignore")
    metadata_payload = json.loads(metadata) if metadata else {}
    record = add_document(text=text, filename=file.filename, metadata=metadata_payload)
    return DocumentUploadResponse(document_id=record["document_id"], status=record["status"], pages=1)


@app.get("/v1/documents/{document_id}", response_model=DocumentMetadataResponse)
async def get_document_by_id(document_id: str) -> DocumentMetadataResponse:
    record = get_document(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentMetadataResponse(
        document_id=record["document_id"],
        filename=record["filename"],
        uploaded_at=record["uploaded_at"],
        size_bytes=record["size_bytes"],
        status=record["status"],
    )


@app.get("/v1/traces/{trace_id}", response_model=TraceResponse)
async def trace(trace_id: str) -> TraceResponse:
    trace_payload = TRACE_STORE.get_trace(trace_id)
    if not trace_payload:
        raise HTTPException(status_code=404, detail="Trace not found")
    events = [AgentTraceEvent(**event) for event in trace_payload["events"]]
    return TraceResponse(
        trace_id=trace_payload["trace_id"],
        query=trace_payload["query"],
        events=events,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    log_event(
        logger,
        {
            "event": "unhandled_exception",
            "request_id": request_id,
            "error": str(exc),
            "path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Unexpected server error",
                "details": {"request_id": request_id},
            }
        },
    )
