from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import Json

from .embeddings import embed_texts
from .settings import load_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[tuple[str, int, int]]:
    if not text:
        return []
    chunks: List[tuple[str, int, int]] = []
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


@contextmanager
def _get_conn():
    settings = load_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for pgvector storage")
    conn = psycopg2.connect(settings.database_url)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    settings = load_settings()
    if not settings.database_url:
        return
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    metadata JSONB NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding VECTOR(%s) NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    chunk_start INTEGER NOT NULL,
                    chunk_end INTEGER NOT NULL
                )
                """,
                (settings.embedding_dim,),
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks (document_id)")
        conn.commit()


def add_document(text: str, filename: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    safe_metadata = metadata or {}
    document_id = safe_metadata.get("document_id") or f"doc-{abs(hash(filename + text)) % (10 ** 8):08d}"
    uploaded_at = safe_metadata.get("uploaded_at") or _now()
    url = safe_metadata.get("url") or f"local://{document_id}"
    title = safe_metadata.get("title") or filename
    published_at = safe_metadata.get("published_at") or uploaded_at

    chunks = _chunk_text(text)
    embeddings = embed_texts([chunk for chunk, _, _ in chunks]) if chunks else []

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (document_id, filename, uploaded_at, size_bytes, status, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(document_id) DO UPDATE SET
                    filename=excluded.filename,
                    uploaded_at=excluded.uploaded_at,
                    size_bytes=excluded.size_bytes,
                    status=excluded.status,
                    metadata=excluded.metadata
                """,
                (
                    document_id,
                    filename,
                    uploaded_at,
                    len(text.encode("utf-8")),
                    "indexed",
                    Json(safe_metadata),
                ),
            )
            for index, (chunk_text, start, end) in enumerate(chunks):
                chunk_id = f"{document_id}-chunk-{index}"
                cur.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, document_id, chunk_index, text, embedding, url, title, published_at, chunk_start, chunk_end
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        text=excluded.text,
                        embedding=excluded.embedding,
                        url=excluded.url,
                        title=excluded.title,
                        published_at=excluded.published_at,
                        chunk_start=excluded.chunk_start,
                        chunk_end=excluded.chunk_end
                    """,
                    (
                        chunk_id,
                        document_id,
                        index,
                        chunk_text,
                        embeddings[index],
                        url,
                        title,
                        published_at,
                        start,
                        end,
                    ),
                )
        conn.commit()

    return {
        "document_id": document_id,
        "filename": filename,
        "uploaded_at": uploaded_at,
        "size_bytes": len(text.encode("utf-8")),
        "status": "indexed",
    }


def get_document(document_id: str) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT document_id, filename, uploaded_at, size_bytes, status FROM documents WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "document_id": row[0],
        "filename": row[1],
        "uploaded_at": row[2],
        "size_bytes": row[3],
        "status": row[4],
    }


def search(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    embeddings = embed_texts([query])
    query_vector = embeddings[0]
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, document_id, text, url, title, published_at, chunk_start, chunk_end,
                       1 - (embedding <=> %s) AS score
                FROM chunks
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_vector, query_vector, limit),
            )
            rows = cur.fetchall()

    results: List[Dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "chunk_id": row[0],
                "document_id": row[1],
                "text": row[2],
                "url": row[3],
                "title": row[4],
                "published_at": row[5],
                "chunk_start": row[6],
                "chunk_end": row[7],
                "score": float(row[8]),
            }
        )
    return results
