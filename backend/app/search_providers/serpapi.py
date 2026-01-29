from __future__ import annotations

from typing import List

import httpx

from . import SearchProvider, SearchResult


class SerpApiSearchProvider(SearchProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def search(self, query: str, max_results: int) -> List[SearchResult]:
        url = "https://serpapi.com/search.json"
        params = {
            "q": query,
            "engine": "google",
            "num": max_results,
            "api_key": self._api_key,
        }
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

        results: List[SearchResult] = []
        for item in payload.get("organic_results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "published_at": item.get("date"),
                }
            )
        return results
