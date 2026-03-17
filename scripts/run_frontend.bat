@echo off
setlocal

echo ==> Starting frontend

if not exist frontend (
  echo frontend directory not found
  exit /b 1
)

cd frontend
call npm run dev

endlocal