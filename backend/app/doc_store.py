from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokenize(text: str) -> List[str]:
    return TOKEN_PATTERN.findall(text.lower())


def _vectorize(text: str) -> Dict[str, float]:
    # TODO: Replace token-count vectors with real embeddings.
    counts: Dict[str, float] = {}
    for token in _tokenize(text):
        counts[token] = counts.get(token, 0.0) + 1.0
    return counts


def _vector_norm(vec: Dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vec.values()))


def _cosine_similarity(a: Dict[str, float], a_norm: float, b: Dict[str, float], b_norm: float) -> float:
    if a_norm == 0 or b_norm == 0:
        return 0.0
    dot = 0.0
    for key, value in a.items():
        dot += value * b.get(key, 0.0)
    return dot / (a_norm * b_norm)


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[Tuple[str, int, int]]:
    if not text:
        return []
    chunks: List[Tuple[str, int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunk = text[start:end]
        chunks.append((chunk, start, end))
        if end == length:
            break
        start = max(0, end - overlap)
    return chunks


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    text: str
    score: float
    vector: Dict[str, float]
    norm: float
    metadata: Dict[str, Any]
    chunk_start: int
    chunk_end: int


@dataclass
class DocumentRecord:
    document_id: str
    filename: str
    uploaded_at: str
    size_bytes: int
    status: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunks: List[DocumentChunk] = field(default_factory=list)


class DocumentStore:
    def __init__(self) -> None:
        self._documents: Dict[str, DocumentRecord] = {}
        self._chunks: List[DocumentChunk] = []

    def add_document(self, text: str, filename: str, metadata: Optional[Dict[str, Any]] = None) -> DocumentRecord:
        document_id = f"doc-{uuid.uuid4().hex[:8]}"
        uploaded_at = datetime.now(timezone.utc).isoformat()
        safe_metadata = metadata or {}
        record = DocumentRecord(
            document_id=document_id,
            filename=filename,
            uploaded_at=uploaded_at,
            size_bytes=len(text.encode("utf-8")),
            status="indexed",
            metadata=safe_metadata,
        )
        url = safe_metadata.get("url") or f"local://{document_id}"
        title = safe_metadata.get("title") or filename
        published_at = safe_metadata.get("published_at") or uploaded_at
        for index, (chunk_text, start, end) in enumerate(_chunk_text(text)):
            vector = _vectorize(chunk_text)
            norm = _vector_norm(vector)
            chunk = DocumentChunk(
                chunk_id=f"chunk-{index}",
                document_id=document_id,
                text=chunk_text,
                score=0.0,
                vector=vector,
                norm=norm,
                metadata={
                    "url": url,
                    "title": title,
                    "published_at": published_at,
                },
                chunk_start=start,
                chunk_end=end,
            )
            record.chunks.append(chunk)
            self._chunks.append(chunk)
        self._documents[document_id] = record
        return record

    def get_document(self, document_id: str) -> Optional[DocumentRecord]:
        return self._documents.get(document_id)

    def search(self, query: str, limit: int = 8) -> List[DocumentChunk]:
        query_vec = _vectorize(query)
        query_norm = _vector_norm(query_vec)
        scored: List[DocumentChunk] = []
        for chunk in self._chunks:
            score = _cosine_similarity(query_vec, query_norm, chunk.vector, chunk.norm)
            if score <= 0:
                continue
            scored.append(
                DocumentChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    text=chunk.text,
                    score=score,
                    vector=chunk.vector,
                    norm=chunk.norm,
                    metadata=chunk.metadata,
                    chunk_start=chunk.chunk_start,
                    chunk_end=chunk.chunk_end,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]


DOCUMENT_STORE = DocumentStore()
