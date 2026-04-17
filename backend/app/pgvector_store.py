from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import logging

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2.extras import Json

from .doc_store import DOCUMENT_STORE
from .embeddings import embed_texts
from .settings import load_settings

logger = logging.getLogger("research_api")

# When True, pgvector is unusable (missing extension, DB down, etc.) — fall
# back to in-memory DOCUMENT_STORE. Set by _get_conn / init_db.
_PGVECTOR_DISABLED = False


def _disable_pgvector(reason: str) -> None:
    global _PGVECTOR_DISABLED
    if not _PGVECTOR_DISABLED:
        logger.warning("pgvector disabled, falling back to in-memory store: %s", reason)
    _PGVECTOR_DISABLED = True


def _pgvector_available() -> bool:
    return bool(load_settings().database_url) and not _PGVECTOR_DISABLED


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


def _bootstrap_extension(conn) -> bool:
    """Create the pgvector extension on an unregistered connection.

    Returns True if the extension is usable afterward. Safe to call even
    when the extension is already present (IF NOT EXISTS).
    """
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        return True
    except psycopg2.Error as exc:
        conn.rollback()
        _disable_pgvector(f"CREATE EXTENSION failed: {exc}")
        return False


@contextmanager
def _get_conn():
    settings = load_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for pgvector storage")
    conn = psycopg2.connect(settings.database_url)
    try:
        try:
            register_vector(conn)
        except psycopg2.ProgrammingError:
            # Extension missing — try to install it, then retry registration.
            conn.rollback()
            if not _bootstrap_extension(conn):
                conn.close()
                raise RuntimeError(
                    "pgvector extension not installed and could not be created. "
                    "Run 'CREATE EXTENSION vector;' as a superuser."
                )
            try:
                register_vector(conn)
            except psycopg2.ProgrammingError as exc:
                conn.close()
                _disable_pgvector(f"register_vector still failing after bootstrap: {exc}")
                raise RuntimeError(
                    "pgvector extension is not usable on this database."
                ) from exc
    except Exception:
        conn.close()
        raise
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    settings = load_settings()
    if not settings.database_url:
        return
    # Step 1: bootstrap extension on a raw connection BEFORE register_vector.
    # Without this, _get_conn() fails on first startup against a fresh DB.
    try:
        conn = psycopg2.connect(settings.database_url)
    except psycopg2.Error as exc:
        _disable_pgvector(f"connect failed at init: {exc}")
        return
    try:
        if not _bootstrap_extension(conn):
            return
    finally:
        conn.close()

    # Step 2: register + create schema through the normal connection helper.
    try:
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
    except Exception as exc:
        _disable_pgvector(f"schema init failed: {exc}")


def _add_document_fallback(text: str, filename: str, metadata: Optional[Dict[str, Any]], status: str) -> Dict[str, Any]:
    """Store the document in the in-memory DOCUMENT_STORE instead of pgvector."""
    record = DOCUMENT_STORE.add_document(text=text, filename=filename, metadata=metadata)
    return {
        "document_id": record.document_id,
        "filename": record.filename,
        "uploaded_at": record.uploaded_at,
        "size_bytes": record.size_bytes,
        "status": status,
    }


def add_document(text: str, filename: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    safe_metadata = metadata or {}
    document_id = safe_metadata.get("document_id") or f"doc-{abs(hash(filename + text)) % (10 ** 8):08d}"
    uploaded_at = safe_metadata.get("uploaded_at") or _now()
    if not load_settings().database_url:
        # No DB configured → in-memory fallback so retrieval still has data.
        return _add_document_fallback(text, filename, safe_metadata, status="indexed_memory")
    if _PGVECTOR_DISABLED:
        return _add_document_fallback(text, filename, safe_metadata, status="indexed_memory")
    url = safe_metadata.get("url") or f"local://{document_id}"
    title = safe_metadata.get("title") or filename
    published_at = safe_metadata.get("published_at") or uploaded_at

    chunks = _chunk_text(text)
    try:
        embeddings = embed_texts([chunk for chunk, _, _ in chunks]) if chunks else []
    except Exception as exc:
        logger.warning("embed_texts failed for %s: %s — falling back to memory store", filename, exc)
        return _add_document_fallback(text, filename, safe_metadata, status="indexed_memory_no_embeddings")

    try:
        return _insert_document(
            document_id=document_id,
            filename=filename,
            uploaded_at=uploaded_at,
            text=text,
            safe_metadata=safe_metadata,
            url=url,
            title=title,
            published_at=published_at,
            chunks=chunks,
            embeddings=embeddings,
        )
    except Exception as exc:
        logger.warning("pgvector insert failed for %s: %s — falling back to memory store", filename, exc)
        _disable_pgvector(f"insert failed: {exc}")
        return _add_document_fallback(text, filename, safe_metadata, status="indexed_memory_db_failed")


def _insert_document(
    *,
    document_id: str,
    filename: str,
    uploaded_at: str,
    text: str,
    safe_metadata: Dict[str, Any],
    url: str,
    title: str,
    published_at: str,
    chunks: List[tuple[str, int, int]],
    embeddings: List[Any],
) -> Dict[str, Any]:
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
                    ) VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s)
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


def add_web_document(url: str, title: str, text: str, published_at: Optional[str], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    safe_metadata = metadata or {}
    safe_metadata.setdefault("url", url)
    safe_metadata.setdefault("title", title or url)
    safe_metadata.setdefault("published_at", published_at or _now())
    filename = title or url
    return add_document(text=text, filename=filename, metadata=safe_metadata)


def get_document(document_id: str) -> Optional[Dict[str, Any]]:
    if not _pgvector_available():
        record = DOCUMENT_STORE.get_document(document_id)
        if not record:
            return None
        return {
            "document_id": record.document_id,
            "filename": record.filename,
            "uploaded_at": record.uploaded_at,
            "size_bytes": record.size_bytes,
            "status": record.status,
        }
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


def _search_memory(query: str, limit: int) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for chunk in DOCUMENT_STORE.search(query, limit=limit):
        results.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "text": chunk.text,
                "url": chunk.metadata.get("url", ""),
                "title": chunk.metadata.get("title", ""),
                "published_at": chunk.metadata.get("published_at", ""),
                "chunk_start": chunk.chunk_start,
                "chunk_end": chunk.chunk_end,
                "score": float(chunk.score),
            }
        )
    return results


def search(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    if not _pgvector_available():
        return _search_memory(query, limit)
    # Short-circuit: empty chunks table → skip embedding (saves Gemini RPM).
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM chunks LIMIT 1")
                if cur.fetchone() is None:
                    return _search_memory(query, limit)
    except Exception as exc:
        logger.warning("pgvector chunk-count probe failed: %s — using memory fallback", exc)
        return _search_memory(query, limit)
    try:
        embeddings = embed_texts([query])
        query_vector = embeddings[0]
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chunk_id, document_id, text, url, title, published_at, chunk_start, chunk_end,
                           1 - (embedding <=> %s::vector) AS score
                    FROM chunks
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_vector, query_vector, limit),
                )
                rows = cur.fetchall()
    except Exception as exc:
        logger.warning("pgvector search failed: %s — using memory fallback", exc)
        return _search_memory(query, limit)

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
    # If DB has no rows but memory does, blend in memory results so manual
    # ingests still surface even when the DB side is empty.
    if not results:
        return _search_memory(query, limit)
    return results
