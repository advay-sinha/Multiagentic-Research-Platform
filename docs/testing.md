# Testing

## Prerequisites
- Postgres with pgvector running
- `DATABASE_URL` set
- At least one web search key set (`BING_API_KEY` or `SERPAPI_KEY`) for `/v1/search`
- Optional for real LLM: `LLM_PROVIDER=openai` + `OPENAI_API_KEY`

## Sample documents
Two sample files are included:
- `sample.txt`
- `sample2.txt`

Upload them:

```powershell
curl -X POST http://localhost:8000/v1/documents -F "file=@sample.txt"
curl -X POST http://localhost:8000/v1/documents -F "file=@sample2.txt"
```

## Run tests

```powershell
python -m pytest
```

## Manual smoke tests

Query:

```powershell
curl -X POST http://localhost:8000/v1/query ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"Summarize the guidance on X\"}"
```

Streamed query:

```powershell
curl -N -X POST http://localhost:8000/v1/query/stream ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"Summarize the guidance on X\"}"
```

Web search (requires API key):

```powershell
curl -X POST http://localhost:8000/v1/search ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"latest guidance on X\",\"max_results\":5}"
```

Trace:

```powershell
curl http://localhost:8000/v1/traces/trace-12345678
```
