from __future__ import annotations

from typing import List

import httpx

from . import SearchProvider, SearchResult


class BingSearchProvider(SearchProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def search(self, query: str, max_results: int) -> List[SearchResult]:
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self._api_key}
        params = {
            "q": query,
            "count": max_results,
            "textDecorations": False,
            "textFormat": "Raw",
        }
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()

        results: List[SearchResult] = []
        for item in payload.get("webPages", {}).get("value", []):
            results.append(
                {
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                    "published_at": item.get("datePublished") or item.get("dateLastCrawled"),
                }
            )
        return results
