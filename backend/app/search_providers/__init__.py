from __future__ import annotations

from typing import List, Optional, TypedDict


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str
    published_at: Optional[str]


class SearchProvider:
    def search(self, query: str, max_results: int) -> List[SearchResult]:
        raise NotImplementedError
