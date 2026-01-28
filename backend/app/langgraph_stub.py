from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from .pgvector_store import search as pg_search


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
class GraphState:
    query: str
    plan: List[PlanStep]
    evidence: List[EvidenceChunk]
    draft_answer: str
    citations: List[Dict[str, Any]]
    trace_events: List[TraceEvent]


class PlannerNode:
    def run(self, query: str) -> List[PlanStep]:
        # TODO: Replace with real planner model call.
        return [
            PlanStep(
                question=f"Key points for: {query}",
                search_query=f"{query} evidence",
            )
        ]


class RetrieverNode:
    def run(self, plan: List[PlanStep], max_results: int) -> List[Dict[str, Any]]:
        # TODO: Replace with real retrieval + ranking + pgvector tuning.
        query = plan[0].search_query if plan else ""
        return pg_search(query, limit=max_results)


class WriterNode:
    def run(self, query: str, evidence: List[EvidenceChunk]) -> Dict[str, Any]:
        # TODO: Replace with real answer generation and citation mapping.
        if evidence:
            snippet = evidence[0].text[:160]
            answer = f"According to the retrieved sources, {snippet}"
        else:
            answer = f"No indexed sources matched the query: {query}"

        citations = []
        for index, chunk in enumerate(evidence):
            citations.append(
                {
                    "citation_id": f"cit-{index:03d}",
                    "source_id": chunk.source_id,
                    "title": chunk.metadata.get("title", "Untitled"),
                    "url": chunk.metadata.get("url", ""),
                    "published_at": chunk.metadata.get("published_at", ""),
                    "snippet": chunk.text[:200],
                    "chunk_start": chunk.chunk_start,
                    "chunk_end": chunk.chunk_end,
                }
            )

        return {"draft_answer": answer, "citations": citations}


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
            },
            chunk_start=row["chunk_start"],
            chunk_end=row["chunk_end"],
        )
        for row in rows
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_graph(query: str, max_sources: int) -> GraphState:
    planner = PlannerNode()
    retriever = RetrieverNode()
    writer = WriterNode()

    plan = planner.run(query)
    plan_event = TraceEvent(
        event_id="evt-plan-001",
        agent="Planner",
        event_type="plan",
        timestamp=_now(),
        payload={"plan": [step.search_query for step in plan]},
    )

    rows = retriever.run(plan, max_results=max_sources)
    evidence = _to_evidence(rows)
    retrieval_event = TraceEvent(
        event_id="evt-retrieval-001",
        agent="Retriever",
        event_type="retrieve",
        timestamp=_now(),
        payload={
            "query": plan[0].search_query if plan else query,
            "result_count": len(evidence),
        },
    )

    writer_output = writer.run(query, evidence)
    writer_event = TraceEvent(
        event_id="evt-writer-001",
        agent="Writer",
        event_type="write",
        timestamp=_now(),
        payload={"citations": len(writer_output["citations"])},
    )

    return GraphState(
        query=query,
        plan=plan,
        evidence=evidence,
        draft_answer=writer_output["draft_answer"],
        citations=writer_output["citations"],
        trace_events=[plan_event, retrieval_event, writer_event],
    )
