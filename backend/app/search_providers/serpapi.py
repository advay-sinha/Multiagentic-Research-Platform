from __future__ import annotations

import os
from typing import List

import serpapi

from . import SearchProvider, SearchResult


class SerpApiSearchProvider(SearchProvider):
    """Search provider backed by SerpAPI.

    Supports both Google and Bing engines.  Pass ``engine="bing"`` to use
    Bing; defaults to ``"google"``.

    The API key is read from the ``SERPAPI_KEY`` environment variable when
    not supplied explicitly.
    """

    def __init__(self, api_key: str | None = None, engine: str = "google") -> None:
        self._api_key = api_key or os.environ.get("SERPAPI_KEY", "")
        if not self._api_key:
            raise ValueError("SERPAPI_KEY is not set")
        self._engine = engine.lower()

    def search(self, query: str, max_results: int) -> List[SearchResult]:
        client = serpapi.Client(api_key=self._api_key)

        if self._engine == "bing":
            params: dict = {
                "engine": "bing",
                "q": query,
                "cc": "US",
                "count": max_results,
            }
        else:
            params = {
                "engine": "google",
                "q": query,
                "google_domain": "google.com",
                "hl": "en",
                "gl": "us",
                "num": max_results,
            }

        raw = client.search(params)
        organic = raw.get("organic_results", [])

        results: List[SearchResult] = []
        for item in organic[:max_results]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "published_at": item.get("date"),
                }
            )
        return results
