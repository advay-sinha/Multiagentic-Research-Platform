from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


class TraceStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        _ensure_dir(os.path.dirname(db_path))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    events_json TEXT NOT NULL
                )
                """
            )

    def save_trace(self, trace_id: str, query: str, events: List[Dict[str, Any]]) -> None:
        events_json = json.dumps(events, ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO traces (trace_id, query, events_json)
                VALUES (?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    query=excluded.query,
                    events_json=excluded.events_json
                """,
                (trace_id, query, events_json),
            )

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT trace_id, query, events_json FROM traces WHERE trace_id = ?",
                (trace_id,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        events = json.loads(row[2])
        return {"trace_id": row[0], "query": row[1], "events": events}


TRACE_STORE = TraceStore(os.path.join(os.path.dirname(__file__), "data", "traces.db"))
