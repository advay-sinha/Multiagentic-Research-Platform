from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from .embeddings import embed_texts
from .extraction import fetch_and_extract
from .llm_client import LLMClient
from .pgvector_store import add_web_document, search as pg_search
from .settings import load_settings

# Hard cap on agent iterations. Loaded from MAX_AGENT_ITERATIONS env var (default 5).
MAX_ITERATIONS: int = int(os.environ.get("MAX_AGENT_ITERATIONS") or "5")

# Early-stop thresholds for the Writer→Critic→Verifier loop.
# CITATION_COVERAGE_MIN: fraction of claims that must be substring-matched in
# evidence text before the loop is allowed to exit. Set <=0 to disable.
CITATION_COVERAGE_MIN: float = float(os.environ.get("CITATION_COVERAGE_MIN") or "0.5")
# CRITIC_ISSUE_MAX: max number of critic-issue keywords ("missing", "unsupported",
# "insufficient", "hallucinat", "contradict") tolerated in the critique before
# another iteration is forced. Set <=0 to disable.
CRITIC_ISSUE_MAX: int = int(os.environ.get("CRITIC_ISSUE_MAX") or "1")
_CRITIC_ISSUE_KEYWORDS = (
    "missing",
    "unsupported",
    "insufficient",
    "hallucinat",
    "contradict",
    "no evidence",
)


@dataclass
class PlanStep:
    question: str
    search_query: str


@dataclass
class EvidenceChunk:
    source_id: str
    chunk_id: str
    text: str
    score: float
    metadata: Dict[str, Any]
    chunk_start: int
    chunk_end: int


@dataclass
class TraceEvent:
    event_id: str
    agent: str
    event_type: str
    timestamp: str
    payload: Dict[str, Any]


@dataclass
class StageLatency:
    stage: str
    duration_ms: float


@dataclass
class GraphState:
    query: str
    plan: List[PlanStep]
    evidence: List[EvidenceChunk]
    draft_answer: str
    citations: List[Dict[str, Any]]
    claim_verifications: List[Dict[str, Any]]
    confidence_score: float
    refusal: bool
    trace_events: List[TraceEvent]
    stage_latencies: List[StageLatency] = field(default_factory=list)
    total_duration_ms: float = 0.0


class PlannerNode:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(self, query: str) -> List[PlanStep]:
        prompt = (
            "Create a retrieval plan for the query. "
            "Return a JSON array of objects with 'question' and 'search_query' fields. "
            "Keep it to 1-3 steps. Example: "
            '[{"question": "...", "search_query": "..."}]'
        )
        raw = self._llm.generate(prompt=prompt, user_content=query, agent="planner").strip()
        # Try to parse structured JSON output from the LLM
        try:
            import json as _json
            parsed = _json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return [
                    PlanStep(
                        question=s.get("question", query),
                        search_query=s.get("search_query", query),
                    )
                    for s in parsed[:3]
                    if isinstance(s, dict)
                ] or [PlanStep(question=f"Key points for: {query}", search_query=raw)]
        except (ValueError, TypeError, AttributeError):
            pass
        # Fallback: treat raw LLM output as a single search query
        search_query = raw if raw else f"{query} evidence"
        return [PlanStep(question=f"Key points for: {query}", search_query=search_query)]


def _get_web_search_provider():
    """Lazy-resolve SerpAPI (preferred) or Bing web search provider.

    Kept local so retriever works without search keys (vector-only mode).
    """
    serp_key = os.environ.get("SERPAPI_KEY")
    bing_key = os.environ.get("BING_API_KEY")
    try:
        if serp_key:
            from .search_providers.serpapi import SerpApiSearchProvider
            return SerpApiSearchProvider(engine="google")
        if bing_key:
            from .search_providers.bing import BingSearchProvider
            return BingSearchProvider(bing_key)
    except Exception:
        return None
    return None


class RetrieverNode:
    """Hybrid retriever: web search (SerpAPI) + vector DB, with universal
    SerpAPI fallback when primary evidence is insufficient.

    Fallback trigger: if the primary retrieval returns zero rows OR the top
    score is below ``WEB_FALLBACK_SCORE_MIN`` (default 0.3), and web search
    was not already attempted in this run, the retriever runs SerpAPI to
    ground the answer. Fallback rows are marked ``origin='web_fallback'`` so
    traces and citations can distinguish them.
    """

    def __init__(self) -> None:
        self.last_web_fallback_used: bool = False
        self.last_web_fallback_count: int = 0

    def _web_search_rows(
        self,
        plan: List[PlanStep],
        budget: int,
        seen_urls: set,
        provider,
        do_index: bool = False,
    ) -> List[Dict[str, Any]]:
        """Run ``provider.search`` over each plan step and extract pages."""
        rows: List[Dict[str, Any]] = []
        for step in plan:
            try:
                hits = provider.search(step.search_query, max_results=budget)
            except Exception:
                hits = []
            for rank, hit in enumerate(hits):
                url = hit.get("url") or ""
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                extracted = fetch_and_extract(url, hit.get("title", ""), hit.get("published_at"))
                if not extracted or not extracted.text:
                    continue
                text = extracted.text[:2000]
                rows.append({
                    "chunk_id": f"web-{abs(hash(extracted.url))}",
                    "document_id": f"web-{abs(hash(extracted.url))}",
                    "text": text,
                    "url": extracted.url,
                    "title": extracted.title,
                    "published_at": extracted.published_at or "",
                    "chunk_start": 0,
                    "chunk_end": len(text),
                    "score": max(0.1, 1.0 - 0.05 * rank),
                })
                if do_index:
                    try:
                        add_web_document(
                            url=extracted.url,
                            title=extracted.title,
                            text=extracted.text,
                            published_at=extracted.published_at,
                            metadata={
                                "source_rank": rank,
                                "query": step.search_query,
                                "origin": "web",
                            },
                        )
                    except Exception:
                        continue
        return rows

    def _fallback_if_weak(
        self,
        final_rows: List[Dict[str, Any]],
        plan: List[PlanStep],
        budget: int,
        seen_urls: set,
        provider,
        already_tried_web: bool,
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """If ``final_rows`` is empty or low-score, escalate to SerpAPI."""
        if provider is None or already_tried_web:
            return final_rows
        threshold = float(os.environ.get("WEB_FALLBACK_SCORE_MIN") or "0.3")
        top_score = max((r["score"] for r in final_rows), default=0.0)
        if final_rows and top_score >= threshold:
            return final_rows
        fallback_rows = self._web_search_rows(plan, budget, seen_urls, provider, do_index=False)
        if not fallback_rows:
            return final_rows
        for r in fallback_rows:
            r["origin"] = "web_fallback"
        self.last_web_fallback_used = True
        self.last_web_fallback_count = len(fallback_rows)
        merged = list(final_rows) + fallback_rows
        merged.sort(key=lambda r: r["score"], reverse=True)
        return merged[:max_results]

    def run(self, plan: List[PlanStep], max_results: int) -> List[Dict[str, Any]]:
        self.last_web_fallback_used = False
        self.last_web_fallback_count = 0
        if not plan:
            return []

        mode = load_settings().retrieval_mode
        if mode == "off":
            return []

        provider = _get_web_search_provider()
        seen_urls: set[str] = set()
        web_budget = max(1, max_results)

        web_rows: List[Dict[str, Any]] = []
        do_web = mode in ("hybrid", "web_only") and provider is not None
        do_index = mode == "hybrid"

        if do_web:
            web_rows = self._web_search_rows(plan, web_budget, seen_urls, provider, do_index=do_index)

        if mode == "web_only":
            web_rows.sort(key=lambda r: r["score"], reverse=True)
            final = web_rows[:max_results]
            # If web_only returned nothing usable (SerpAPI empty / extraction
            # failures), retry once as fallback — no cost if provider is None.
            return self._fallback_if_weak(
                final, plan, web_budget, seen_urls, provider,
                already_tried_web=bool(web_rows), max_results=max_results,
            )

        # vector path (hybrid or vector_only). Warm embed cache once.
        unique_queries = list({step.search_query for step in plan if step.search_query})
        if unique_queries:
            try:
                embed_texts(unique_queries)
            except Exception:
                if web_rows:
                    web_rows.sort(key=lambda r: r["score"], reverse=True)
                    return web_rows[:max_results]
                # No web rows and embed exhausted — try SerpAPI fallback.
                return self._fallback_if_weak(
                    [], plan, web_budget, seen_urls, provider,
                    already_tried_web=do_web, max_results=max_results,
                )

        aggregated: Dict[str, Dict[str, Any]] = {}
        for step in plan:
            rows = pg_search(step.search_query, limit=max_results)
            for row in rows:
                cid = row["chunk_id"]
                if cid not in aggregated or row["score"] > aggregated[cid]["score"]:
                    aggregated[cid] = row

        for row in web_rows:
            cid = row["chunk_id"]
            if cid not in aggregated:
                aggregated[cid] = row

        ranked = sorted(aggregated.values(), key=lambda r: r["score"], reverse=True)
        final = ranked[:max_results]

        # Universal SerpAPI fallback — triggers when vector_only is weak or
        # hybrid got nothing. Skipped if web was already exhausted this run.
        return self._fallback_if_weak(
            final, plan, web_budget, seen_urls, provider,
            already_tried_web=do_web, max_results=max_results,
        )


class WriterNode:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(self, query: str, evidence: List[EvidenceChunk]) -> Dict[str, Any]:
        evidence_blocks = []
        for chunk in evidence:
            evidence_blocks.append(
                f"[{chunk.chunk_id}] {chunk.text[:400]}"
            )
        context = "\n".join(evidence_blocks) if evidence_blocks else "No evidence available."
        prompt = (
            "Write a grounded answer using only the evidence provided. "
            "If evidence is insufficient, say so."
        )
        answer = self._llm.generate(prompt=prompt, user_content=f"Query: {query}\nEvidence:\n{context}", agent="writer")
        if not answer:
            if evidence:
                answer = f"According to the retrieved sources, {evidence[0].text[:160]}"
            else:
                answer = f"No indexed sources matched the query: {query}"

        citations = []
        answer_lower = answer.lower()
        for index, chunk in enumerate(evidence):
            snippet = chunk.text[:200]
            # Best-effort span alignment: find snippet text in the answer
            span_start = None
            span_end = None
            pos = answer_lower.find(snippet[:60].lower())
            if pos >= 0:
                span_start = pos
                span_end = pos + len(snippet[:60])

            citations.append(
                {
                    "citation_id": f"cit-{index:03d}",
                    "source_id": chunk.source_id,
                    "title": chunk.metadata.get("title", "Untitled"),
                    "url": chunk.metadata.get("url", ""),
                    "published_at": chunk.metadata.get("published_at", ""),
                    "snippet": snippet,
                    "chunk_start": chunk.chunk_start,
                    "chunk_end": chunk.chunk_end,
                    "answer_span_start": span_start,
                    "answer_span_end": span_end,
                }
            )

        return {"draft_answer": answer, "citations": citations}


class CriticNode:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(self, query: str, answer: str, evidence: List[EvidenceChunk]) -> str:
        prompt = (
            "Review the answer for missing evidence or unsupported claims. "
            "Return a short critique."
        )
        context = "\n".join(chunk.text[:200] for chunk in evidence) if evidence else "No evidence."
        critique = self._llm.generate(prompt=prompt, user_content=f"Query: {query}\nAnswer: {answer}\nEvidence: {context}", agent="critic")
        return critique or "No critique available."


class VerifierNode:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(self, answer: str, evidence: List[EvidenceChunk]) -> List[Dict[str, Any]]:
        if not answer or not evidence:
            return []
        prompt = (
            "Identify up to 3 key claims from the answer. For each claim, return a JSON array: "
            '[{"claim_text": "...", "verdict": "supported"|"unsupported"|"partial", '
            '"confidence": 0.0-1.0, "notes": "brief justification"}]. '
            "Base verdicts strictly on the provided evidence."
        )
        evidence_context = "\n".join(f"[{c.chunk_id}] {c.text[:300]}" for c in evidence[:4])
        raw = self._llm.generate(
            prompt=prompt,
            user_content=f"Answer: {answer}\n\nEvidence:\n{evidence_context}",
            agent="verifier",
        )
        evidence_ids = [chunk.chunk_id for chunk in evidence[:4]]

        # Try to parse structured JSON claims from the LLM
        try:
            import json as _json
            parsed = _json.loads(raw)
            if isinstance(parsed, list) and parsed:
                claims = []
                for i, item in enumerate(parsed[:3]):
                    if not isinstance(item, dict):
                        continue
                    claims.append({
                        "claim_id": f"clm-{i + 1:03d}",
                        "claim_text": str(item.get("claim_text", answer[:120])),
                        "verdict": str(item.get("verdict", "supported")).lower(),
                        "evidence_chunk_ids": evidence_ids,
                        "confidence": float(item.get("confidence", 0.66)),
                        "notes": str(item.get("notes", "")),
                    })
                if claims:
                    return claims
        except (ValueError, TypeError, AttributeError):
            pass

        # Fallback: heuristic single-claim verdict
        verdict_label = "supported" if "unsupported" not in raw.lower() else "unsupported"
        return [
            {
                "claim_id": "clm-001",
                "claim_text": answer[:120],
                "verdict": verdict_label,
                "evidence_chunk_ids": evidence_ids,
                "confidence": 0.66,
                "notes": raw or "Heuristic verification.",
            }
        ]


def _derive_confidence(claims: List[Dict[str, Any]], evidence: List[EvidenceChunk]) -> float:
    if not evidence:
        return 0.0
    if not claims:
        return 0.2
    supported = sum(1 for claim in claims if claim.get("verdict") == "supported")
    ratio = supported / max(len(claims), 1)
    return round(0.4 + 0.6 * ratio, 2)


def _citation_coverage(claims: List[Dict[str, Any]], evidence: List[EvidenceChunk]) -> float:
    """Fraction of claims whose text has a substring match in any evidence chunk.

    Crude but cheap proxy for grounding: no LLM calls, no embeddings.
    """
    if not claims or not evidence:
        return 0.0
    blob = " ".join(c.text for c in evidence).lower()
    if not blob:
        return 0.0
    matched = 0
    for claim in claims:
        text = str(claim.get("claim_text", "")).strip().lower()
        if not text:
            continue
        # Split on whitespace and require at least one 4+-char token to appear.
        tokens = [tok for tok in text.split() if len(tok) >= 4]
        if any(tok in blob for tok in tokens[:8]):
            matched += 1
    return round(matched / len(claims), 3)


def _count_critic_issues(critique: str) -> int:
    if not critique:
        return 0
    low = critique.lower()
    return sum(1 for kw in _CRITIC_ISSUE_KEYWORDS if kw in low)


def _to_evidence(rows: List[Dict[str, Any]]) -> List[EvidenceChunk]:
    return [
        EvidenceChunk(
            source_id=row["document_id"],
            chunk_id=row["chunk_id"],
            text=row["text"],
            score=row["score"],
            metadata={
                "url": row["url"],
                "title": row["title"],
                "published_at": row["published_at"],
                "origin": row.get("origin", "web" if str(row.get("chunk_id", "")).startswith("web-") else "vector"),
            },
            chunk_start=row["chunk_start"],
            chunk_end=row["chunk_end"],
        )
        for row in rows
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def run_graph(query: str, max_sources: int) -> GraphState:
    llm = LLMClient()
    planner = PlannerNode(llm)
    retriever = RetrieverNode()
    writer = WriterNode(llm)
    critic = CriticNode(llm)
    verifier = VerifierNode(llm)

    graph_start = time.perf_counter()
    stage_latencies: List[StageLatency] = []
    trace_events: List[TraceEvent] = []

    # ── Planner (single pass) ────────────────────────────────────────────────
    t = time.perf_counter()
    plan = planner.run(query)
    stage_latencies.append(StageLatency(stage="planner", duration_ms=_ms(t)))
    trace_events.append(TraceEvent(
        event_id="evt-plan-001",
        agent="Planner",
        event_type="plan",
        timestamp=_now(),
        payload={"plan": [step.search_query for step in plan]},
    ))

    # ── Retriever (single pass) ──────────────────────────────────────────────
    t = time.perf_counter()
    rows = retriever.run(plan, max_results=max_sources)
    evidence = _to_evidence(rows)
    stage_latencies.append(StageLatency(stage="retriever", duration_ms=_ms(t)))
    web_enabled = bool(os.environ.get("SERPAPI_KEY") or os.environ.get("BING_API_KEY"))
    fallback_used = getattr(retriever, "last_web_fallback_used", False)
    fallback_count = getattr(retriever, "last_web_fallback_count", 0)
    trace_events.append(TraceEvent(
        event_id="evt-retrieval-001",
        agent="Retriever",
        event_type="retrieve",
        timestamp=_now(),
        payload={
            "query": plan[0].search_query if plan else query,
            "result_count": len(evidence),
            "web_search": "enabled" if web_enabled else "disabled",
            "web_fallback_triggered": fallback_used,
            "web_fallback_sources": fallback_count,
            "sources": [
                {
                    "url": c.metadata.get("url", ""),
                    "title": c.metadata.get("title", ""),
                    "origin": c.metadata.get("origin", ""),
                }
                for c in evidence[:max_sources]
            ],
        },
    ))

    # ── Writer → Critic → Verifier loop (up to MAX_ITERATIONS) ──────────────
    # Iterates until confidence is sufficient or iteration cap is reached.
    writer_output: Dict[str, Any] = {"draft_answer": "", "citations": []}
    claim_verifications: List[Dict[str, Any]] = []
    confidence_score = 0.0
    refusal = True

    for iteration in range(MAX_ITERATIONS):
        t = time.perf_counter()
        writer_output = writer.run(query, evidence)
        stage_latencies.append(StageLatency(stage="writer", duration_ms=_ms(t)))
        trace_events.append(TraceEvent(
            event_id=f"evt-writer-{iteration + 1:03d}",
            agent="Writer",
            event_type="write",
            timestamp=_now(),
            payload={"iteration": iteration + 1, "citations": len(writer_output["citations"])},
        ))

        t = time.perf_counter()
        critique = critic.run(query, writer_output["draft_answer"], evidence)
        stage_latencies.append(StageLatency(stage="critic", duration_ms=_ms(t)))
        trace_events.append(TraceEvent(
            event_id=f"evt-critic-{iteration + 1:03d}",
            agent="Critic",
            event_type="critique",
            timestamp=_now(),
            payload={"iteration": iteration + 1, "notes": critique[:400]},
        ))

        t = time.perf_counter()
        claim_verifications = verifier.run(writer_output["draft_answer"], evidence)
        confidence_score = _derive_confidence(claim_verifications, evidence)
        refusal = confidence_score < 0.4
        coverage = _citation_coverage(claim_verifications, evidence)
        critic_issues = _count_critic_issues(critique)
        stage_latencies.append(StageLatency(stage="verifier", duration_ms=_ms(t)))
        trace_events.append(TraceEvent(
            event_id=f"evt-verify-{iteration + 1:03d}",
            agent="Verifier",
            event_type="verify",
            timestamp=_now(),
            payload={
                "iteration": iteration + 1,
                "claim_count": len(claim_verifications),
                "confidence_score": confidence_score,
                "citation_coverage": coverage,
                "critic_issues": critic_issues,
                "refusal": refusal,
            },
        ))

        # Stop early when ALL quality gates pass:
        #   - confidence ≥ 0.4 (not a refusal)
        #   - citation coverage meets minimum (if configured)
        #   - critic issue count within tolerance (if configured)
        coverage_ok = CITATION_COVERAGE_MIN <= 0 or coverage >= CITATION_COVERAGE_MIN
        critic_ok = CRITIC_ISSUE_MAX <= 0 or critic_issues <= CRITIC_ISSUE_MAX
        if not refusal and coverage_ok and critic_ok:
            break
        # Stop early when providers are all unreachable — re-running just
        # burns throttle time producing identical stub output.
        if getattr(llm, "stub_fallback_hit", False):
            trace_events.append(TraceEvent(
                event_id=f"evt-abort-{iteration + 1:03d}",
                agent="Verifier",
                event_type="abort",
                timestamp=_now(),
                payload={"reason": "all_providers_unavailable"},
            ))
            break

    return GraphState(
        query=query,
        plan=plan,
        evidence=evidence,
        draft_answer=writer_output["draft_answer"],
        citations=writer_output["citations"],
        claim_verifications=claim_verifications,
        confidence_score=confidence_score,
        refusal=refusal,
        trace_events=trace_events,
        stage_latencies=stage_latencies,
        total_duration_ms=_ms(graph_start),
    )
