@echo off
setlocal

:: Start the FastAPI backend using the venv python directly (no activation needed)
if exist "%~dp0venv\Scripts\python.exe" (
    start "" /b "%~dp0venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
)

:: Give the backend a moment to initialize
timeout /t 2 /nobreak >nul

:: Run Vite dev server in foreground — keeps the CADEN child process alive
cd /d "%~dp0frontend"
npm run dev
