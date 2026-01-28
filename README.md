# Autonomous Agentic Research Platform

## Run API locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

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
