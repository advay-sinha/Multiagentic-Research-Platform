from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Settings:
    database_url: str
    embedding_model: str
    embedding_dim: int


def load_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL", "")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    embedding_dim = int(os.environ.get("EMBEDDING_DIM", "384"))
    return Settings(
        database_url=database_url,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
    )
