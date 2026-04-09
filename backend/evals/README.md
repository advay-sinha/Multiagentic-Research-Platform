# Evaluation Harness

Scores research query responses against a baseline dataset.

## Metrics

| Metric | Description |
|--------|-------------|
| **Faithfulness** | Fraction of expected facts found (substring match) in the answer |
| **Citation Coverage** | Fraction of expected citation tokens found in citation titles/URLs |
| **Hallucination Score** | Fraction of answer sentences grounded in evidence (1.0 = no hallucination) |
| **Latency** | Round-trip time in milliseconds for each query |

## Dataset

`baseline.jsonl` contains 5 example prompts aligned to sample documents. Each line is a JSON object:

```json
{"id": "ex-001", "query": "...", "expected_facts": ["..."], "expected_citations": ["..."]}
```

## Run

With the API running on port 8000:

```bash
python -m backend.evals.run
```

Override dataset or API base:

```bash
python -m backend.evals.run backend/evals/baseline.jsonl http://localhost:8000
```

Environment variable:

- `EVAL_API_BASE` (default: `http://localhost:8000`)
