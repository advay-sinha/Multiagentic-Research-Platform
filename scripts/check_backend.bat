@echo off
setlocal

echo ==> Backend validation started

if not exist backend (
  echo backend directory not found
  exit /b 1
)

cd backend

if not exist requirements.txt (
  echo requirements.txt missing
  exit /b 1
)

python -m compileall app
if errorlevel 1 exit /b 1

python -c "import app.main; print('FastAPI import check passed')"
if errorlevel 1 exit /b 1

if exist tests (
  echo ==> tests directory found
) else (
  echo ==> tests directory not found ^(non-blocking^)
)

echo ==> Backend validation completed
endlocal