@echo off
setlocal

echo ==> Frontend validation started

if not exist frontend (
  echo frontend directory not found
  exit /b 1
)

cd frontend

if not exist package.json (
  echo package.json missing
  exit /b 1
)

call npm run lint --if-present
if errorlevel 1 exit /b 1

call npm run typecheck --if-present
if errorlevel 1 exit /b 1

call npm run build
if errorlevel 1 exit /b 1

echo ==> Frontend validation completed
endlocal