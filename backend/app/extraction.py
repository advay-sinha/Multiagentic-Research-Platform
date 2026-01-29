from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

import httpx


@dataclass
class ExtractionResult:
    url: str
    title: str
    text: str
    published_at: Optional[str]


def _extract_with_trafilatura(html: str, url: str) -> Optional[str]:
    try:
        import trafilatura
    except ImportError:
        return None
    return trafilatura.extract(html, url=url)


def _extract_with_readability(html: str) -> Optional[str]:
    try:
        from readability import Document
    except ImportError:
        return None
    doc = Document(html)
    summary = doc.summary()
    return re.sub(r"<[^>]+>", " ", summary)


def fetch_and_extract(url: str, title: str, published_at: Optional[str]) -> Optional[ExtractionResult]:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        html = response.text

    extracted = _extract_with_trafilatura(html, url) or _extract_with_readability(html)
    if not extracted:
        return None

    return ExtractionResult(url=url, title=title, text=extracted, published_at=published_at)
