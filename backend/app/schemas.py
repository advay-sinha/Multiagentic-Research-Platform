from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class QueryOptions(BaseModel):
    stream: bool = False
    max_sources: int = Field(default=8, ge=1, le=25)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    embedding_model: str = "text-embedding-3-large"
    search_provider: str = "bing"
    enable_verifier: bool = True


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    documents: List[str] = Field(default_factory=list)
    options: QueryOptions = Field(default_factory=QueryOptions)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    search_provider: str = "bing"
    freshness: str = "month"
    max_results: int = Field(default=10, ge=1, le=50)


class Citation(BaseModel):
    citation_id: str
    source_id: str
    title: str
    url: str
    published_at: str
    snippet: str
    chunk_start: int
    chunk_end: int


class ClaimVerification(BaseModel):
    claim_id: str
    claim_text: str
    verdict: str
    evidence_chunk_ids: List[str]
    confidence: float
    notes: str


class QueryResponse(BaseModel):
    answer_id: str
    query: str
    answer: str
    citations: List[Citation]
    claim_verifications: List[ClaimVerification]
    confidence_score: float
    refusal: bool
    trace_id: str


class SearchResult(BaseModel):
    source_id: str
    title: str
    url: str
    published_at: str
    snippet: str


class SearchResponse(BaseModel):
    results: List[SearchResult]


class AgentTraceEvent(BaseModel):
    event_id: str
    agent: str
    event_type: str
    timestamp: str
    payload: dict[str, Any]


class TraceResponse(BaseModel):
    trace_id: str
    query: str
    events: List[AgentTraceEvent]


class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str
    pages: int


class DocumentMetadataResponse(BaseModel):
    document_id: str
    filename: str
    uploaded_at: str
    size_bytes: int
    status: str


class HealthResponse(BaseModel):
    status: str
    version: str
