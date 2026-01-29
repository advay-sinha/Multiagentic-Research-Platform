from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import httpx


DEFAULT_DATASET = Path(__file__).parent / "baseline.jsonl"
DEFAULT_API = os.environ.get("EVAL_API_BASE", "http://localhost:8000")


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


def run_eval(dataset_path: Path, api_base: str) -> Tuple[List[EvalResult], Dict[str, float]]:
    examples = _load_dataset(dataset_path)
    results: List[EvalResult] = []
    for example in examples:
        response = _post_query(api_base, example.query)
        answer = str(response.get("answer", ""))
        citations = response.get("citations", [])
        faithfulness = _score_faithfulness(answer, example.expected_facts)
        citation_coverage = _score_citation_coverage(citations, example.expected_citations)
        results.append(
            EvalResult(
                example_id=example.example_id,
                faithfulness=faithfulness,
                citation_coverage=citation_coverage,
            )
        )

    avg_faithfulness = sum(item.faithfulness for item in results) / max(len(results), 1)
    avg_citation = sum(item.citation_coverage for item in results) / max(len(results), 1)
    return results, {"faithfulness": avg_faithfulness, "citation_coverage": avg_citation}


def main(argv: List[str]) -> int:
    args = list(argv)
    if args and args[0].endswith((".py", "backend.evals.run")):
        args = args[1:]
    dataset = Path(args[0]) if len(args) > 0 else DEFAULT_DATASET
    api_base = args[1] if len(args) > 1 else DEFAULT_API

    results, aggregates = run_eval(dataset, api_base)
    print("Evaluation results")
    for item in results:
        print(f"- {item.example_id}: faithfulness={item.faithfulness:.2f}, citation_coverage={item.citation_coverage:.2f}")
    print("Averages")
    print(f"- faithfulness={aggregates['faithfulness']:.2f}")
    print(f"- citation_coverage={aggregates['citation_coverage']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
