from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import httpx


DEFAULT_DATASET = Path(__file__).parent / "baseline.jsonl"
DEFAULT_API = os.environ.get("EVAL_API_BASE", "http://localhost:8000")

# Common stop-words excluded from hallucination overlap checks
_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "shall should may might can could of in to for on with at by from as into "
    "that this it and or but not no nor so yet if then else".split()
)


@dataclass
class EvalExample:
    example_id: str
    query: str
    expected_facts: List[str]
    expected_citations: List[str]


@dataclass
class EvalResult:
    example_id: str
    faithfulness: float
    citation_coverage: float
    hallucination_score: float
    latency_ms: float


def _load_dataset(path: Path) -> List[EvalExample]:
    examples: List[EvalExample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            examples.append(
                EvalExample(
                    example_id=payload["id"],
                    query=payload["query"],
                    expected_facts=payload.get("expected_facts", []),
                    expected_citations=payload.get("expected_citations", []),
                )
            )
    return examples


def _post_query(api_base: str, query: str) -> Dict[str, object]:
    payload = {"query": query}
    with httpx.Client(timeout=60.0) as client:
        response = client.post(f"{api_base}/v1/query", json=payload)
        response.raise_for_status()
        return response.json()


def _score_faithfulness(answer: str, expected_facts: Iterable[str]) -> float:
    expected_list = list(expected_facts)
    if not expected_list:
        return 1.0
    hits = 0
    lower = answer.lower()
    for fact in expected_list:
        if fact.lower() in lower:
            hits += 1
    return hits / max(len(expected_list), 1)


def _score_citation_coverage(citations: List[Dict[str, object]], expected: Iterable[str]) -> float:
    expected_list = list(expected)
    if not expected_list:
        return 1.0
    available = " ".join(
        [str(citation.get("title", "")) + " " + str(citation.get("url", "")) for citation in citations]
    ).lower()
    hits = sum(1 for item in expected_list if item.lower() in available)
    return hits / max(len(expected_list), 1)


def _score_hallucination(answer: str, citations: List[Dict[str, object]]) -> float:
    """Return ratio of answer sentences grounded in evidence (1.0 = no hallucination).

    Splits the answer into sentences and checks each for meaningful word overlap
    with the combined citation snippets. Sentences with fewer than 4 non-stopword
    tokens are skipped (too short to evaluate).
    """
    sentences = [s.strip() for s in answer.replace("\\n", ".").split(".") if len(s.strip()) > 20]
    if not sentences:
        return 1.0

    evidence_text = " ".join(str(c.get("snippet", "")) for c in citations).lower()
    evidence_words = set(evidence_text.split()) - _STOP_WORDS

    grounded = 0
    evaluated = 0
    for sentence in sentences:
        words = set(sentence.lower().split()) - _STOP_WORDS
        if len(words) < 4:
            continue
        evaluated += 1
        overlap = len(words & evidence_words)
        if overlap / max(len(words), 1) > 0.25:
            grounded += 1

    if evaluated == 0:
        return 1.0
    return grounded / evaluated


def run_eval(dataset_path: Path, api_base: str) -> Tuple[List[EvalResult], Dict[str, float]]:
    examples = _load_dataset(dataset_path)
    results: List[EvalResult] = []
    for example in examples:
        start = time.perf_counter()
        response = _post_query(api_base, example.query)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        answer = str(response.get("answer", ""))
        citations = response.get("citations", [])
        faithfulness = _score_faithfulness(answer, example.expected_facts)
        citation_coverage = _score_citation_coverage(citations, example.expected_citations)
        hallucination_score = _score_hallucination(answer, citations)
        results.append(
            EvalResult(
                example_id=example.example_id,
                faithfulness=faithfulness,
                citation_coverage=citation_coverage,
                hallucination_score=hallucination_score,
                latency_ms=latency_ms,
            )
        )

    n = max(len(results), 1)
    avg_faithfulness = sum(r.faithfulness for r in results) / n
    avg_citation = sum(r.citation_coverage for r in results) / n
    avg_hallucination = sum(r.hallucination_score for r in results) / n
    avg_latency = sum(r.latency_ms for r in results) / n
    return results, {
        "faithfulness": avg_faithfulness,
        "citation_coverage": avg_citation,
        "hallucination_score": avg_hallucination,
        "avg_latency_ms": avg_latency,
    }


def main(argv: List[str]) -> int:
    args = list(argv)
    if args and args[0].endswith((".py", "backend.evals.run")):
        args = args[1:]
    dataset = Path(args[0]) if len(args) > 0 else DEFAULT_DATASET
    api_base = args[1] if len(args) > 1 else DEFAULT_API

    results, aggregates = run_eval(dataset, api_base)
    print("Evaluation results")
    for item in results:
        print(
            f"  {item.example_id}: faithfulness={item.faithfulness:.2f}  "
            f"citation_coverage={item.citation_coverage:.2f}  "
            f"hallucination={item.hallucination_score:.2f}  "
            f"latency={item.latency_ms:.0f}ms"
        )
    print("Averages")
    print(f"  faithfulness       = {aggregates['faithfulness']:.2f}")
    print(f"  citation_coverage  = {aggregates['citation_coverage']:.2f}")
    print(f"  hallucination      = {aggregates['hallucination_score']:.2f}")
    print(f"  avg_latency        = {aggregates['avg_latency_ms']:.0f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
