@echo off
setlocal

echo ==> Starting backend

if not exist backend (
  echo backend directory not found
  exit /b 1
)

cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

endlocal