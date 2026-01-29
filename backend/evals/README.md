# Evaluation harness

This folder contains a minimal evaluation harness to score:
- Faithfulness (string match for expected facts)
- Citation coverage (expected citation tokens found in citation titles/urls)

## Dataset

`baseline.jsonl` contains a small set of 5 example prompts aligned to sample documents.

## Run

With the API running:

```powershell
python -m backend.evals.run
```

Override dataset or API base:

```powershell
python -m backend.evals.run backend\evals\baseline.jsonl http://localhost:8000
```

Environment variable:

- `EVAL_API_BASE` (default: `http://localhost:8000`)
