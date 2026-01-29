from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from .llm_client import LLMClient
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
    claim_verifications: List[Dict[str, Any]]
    confidence_score: float
    refusal: bool
    trace_events: List[TraceEvent]


class PlannerNode:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(self, query: str) -> List[PlanStep]:
        # TODO: Replace with structured planning output.
        prompt = (
            "Create a minimal retrieval plan for the query. "
            "Return a short search query string."
        )
        search_query = self._llm.generate(prompt=prompt, user_content=query).strip()
        if not search_query:
            search_query = f"{query} evidence"
        return [PlanStep(question=f"Key points for: {query}", search_query=search_query)]


class RetrieverNode:
    def run(self, plan: List[PlanStep], max_results: int) -> List[Dict[str, Any]]:
        # TODO: Replace with real retrieval + ranking + pgvector tuning.
        query = plan[0].search_query if plan else ""
        return pg_search(query, limit=max_results)


class WriterNode:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(self, query: str, evidence: List[EvidenceChunk]) -> Dict[str, Any]:
        # TODO: Improve citation mapping with explicit span alignment.
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
        answer = self._llm.generate(prompt=prompt, user_content=f"Query: {query}\nEvidence:\n{context}")
        if not answer:
            if evidence:
                answer = f"According to the retrieved sources, {evidence[0].text[:160]}"
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


class CriticNode:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(self, query: str, answer: str, evidence: List[EvidenceChunk]) -> str:
        prompt = (
            "Review the answer for missing evidence or unsupported claims. "
            "Return a short critique."
        )
        context = "\n".join(chunk.text[:200] for chunk in evidence) if evidence else "No evidence."
        critique = self._llm.generate(prompt=prompt, user_content=f"Query: {query}\nAnswer: {answer}\nEvidence: {context}")
        return critique or "No critique available."


class VerifierNode:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(self, answer: str, evidence: List[EvidenceChunk]) -> List[Dict[str, Any]]:
        # TODO: Replace heuristic verification with claim-level alignment.
        if not answer or not evidence:
            return []
        prompt = (
            "Identify up to 2 key claims from the answer and label them as "
            "supported or unsupported based on the evidence."
        )
        evidence_ids = [chunk.chunk_id for chunk in evidence[:2]]
        verdict = self._llm.generate(prompt=prompt, user_content=answer)
        verdict_label = "supported" if "unsupported" not in verdict.lower() else "unsupported"
        return [
            {
                "claim_id": "clm-001",
                "claim_text": answer[:120],
                "verdict": verdict_label,
                "evidence_chunk_ids": evidence_ids,
                "confidence": 0.66,
                "notes": verdict or "Heuristic verification.",
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
    llm = LLMClient()
    planner = PlannerNode(llm)
    retriever = RetrieverNode()
    writer = WriterNode(llm)
    critic = CriticNode(llm)
    verifier = VerifierNode(llm)

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
    critique = critic.run(query, writer_output["draft_answer"], evidence)
    critic_event = TraceEvent(
        event_id="evt-critic-001",
        agent="Critic",
        event_type="critique",
        timestamp=_now(),
        payload={"notes": critique[:400]},
    )
    claim_verifications = verifier.run(writer_output["draft_answer"], evidence)
    confidence_score = _derive_confidence(claim_verifications, evidence)
    refusal = confidence_score < 0.4
    verifier_event = TraceEvent(
        event_id="evt-verify-001",
        agent="Verifier",
        event_type="verify",
        timestamp=_now(),
        payload={"claim_count": len(claim_verifications), "confidence_score": confidence_score, "refusal": refusal},
    )

    return GraphState(
        query=query,
        plan=plan,
        evidence=evidence,
        draft_answer=writer_output["draft_answer"],
        citations=writer_output["citations"],
        claim_verifications=claim_verifications,
        confidence_score=confidence_score,
        refusal=refusal,
        trace_events=[plan_event, retrieval_event, writer_event, critic_event, verifier_event],
    )
