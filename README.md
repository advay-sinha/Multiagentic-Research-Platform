# Autonomous Agentic Research Platform

## Run API locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

## Postgres + pgvector setup

Start Postgres with pgvector:

```powershell
docker run --name research-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=research -p 5432:5432 -d pgvector/pgvector:pg16
```

Set environment variables:

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/research"
$env:EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
$env:EMBEDDING_DIM = "384"
```

## Web search API keys

Set at least one provider key:

```powershell
$env:BING_API_KEY = "<your-bing-key>"
# or
$env:SERPAPI_KEY = "<your-serpapi-key>"
```

## LLM configuration

```powershell
$env:LLM_PROVIDER = "openai"  # or "stub"
$env:OPENAI_API_KEY = "<your-openai-key>"
$env:OPENAI_MODEL = "gpt-4o-mini"
```

Run the API:

```powershell
uvicorn backend.app.main:app --reload --port 8000
```

## Frontend (Next.js)

```powershell
cd frontend
npm install
$env:NEXT_PUBLIC_API_BASE = "http://localhost:8000"
npm run dev
```

Visit http://localhost:3000 to use the UI.

## Example requests

Health check:

```powershell
Invoke-RestMethod http://localhost:8000/v1/health
```

Upload document:

```powershell
curl -X POST http://localhost:8000/v1/documents ^
  -F "file=@sample.txt" ^
  -F "metadata={\"title\":\"Sample Doc\"}"
```

Query:

```powershell
curl -X POST http://localhost:8000/v1/query ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"What is the latest guidance on X?\"}"
```

Streamed query:

```powershell
curl -N -X POST http://localhost:8000/v1/query/stream ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"What is the latest guidance on X?\"}"
```

Search:

```powershell
curl -X POST http://localhost:8000/v1/search ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"latest guidance on X\",\"max_results\":5}"
```

Trace:

```powershell
curl http://localhost:8000/v1/traces/trace-12345678
```

## Testing

See `docs/testing.md` for test setup and sample commands.

## Evaluation harness

Run the baseline evaluation (API must be running):

```powershell
python -m backend.evals.run
```

Override dataset/API base:

```powershell
python -m backend.evals.run backend\\evals\\baseline.jsonl http://localhost:8000
```
