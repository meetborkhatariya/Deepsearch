@echo off
title Open Deep Research
cd /d "%~dp0"

set FRONTEND_URL=http://localhost:5173
set BACKEND_URL=http://localhost:8000

echo ============================================================
echo   Open Deep Research - Dev Server
echo ============================================================
echo.
echo   Frontend : %FRONTEND_URL%
echo   Backend  : %BACKEND_URL%
echo   API Docs : %BACKEND_URL%/docs
echo   Health   : %BACKEND_URL%/health
echo.
echo   Backend and frontend open in separate windows.
echo   Close them or press Ctrl+C in each window to stop.
echo ============================================================
echo.

if not exist "frontend\node_modules" (
    echo [setup] Installing frontend dependencies...
    pushd frontend
    call npm install
    popd
)

start "ODR Frontend - http://localhost:5173" cmd /k "cd /d "%~dp0frontend" && npm run dev"
start "ODR Backend - http://localhost:8000/docs" cmd /k "cd /d "%~dp0" && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

echo Both servers starting... open %FRONTEND_URL% in your browser.
echo.
pause