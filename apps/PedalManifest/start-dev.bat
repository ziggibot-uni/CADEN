@echo off
start /b "" venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
npx vite
