@echo off
cd /d "%~dp0"

set OLLAMA_GPU_OVERHEAD=0

echo Killing stale CADEN and backend processes...
taskkill /f /im caden.exe >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq uvicorn*" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do taskkill /f /pid %%a >nul 2>&1

echo Clearing Vite cache...
if exist "node_modules\.vite" rd /s /q "node_modules\.vite"

echo Clearing stale build output...
if exist "dist" rd /s /q "dist"

echo Clearing WebView2 code cache...
if exist "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\Cache" rd /s /q "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\Cache"
if exist "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\Code Cache" rd /s /q "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\Code Cache"
if exist "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\GPUCache" rd /s /q "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\GPUCache"
if exist "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\DawnGraphiteCache" rd /s /q "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\DawnGraphiteCache"
if exist "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\DawnWebGPUCache" rd /s /q "%LOCALAPPDATA%\com.caden.app\EBWebView\Default\DawnWebGPUCache"

echo Removing stale Rust binary...
if exist "src-tauri\target\debug\caden.exe" del /f /q "src-tauri\target\debug\caden.exe"

echo Starting PedalManifest backend...
cd apps\PedalManifest
start /b "" venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
cd /d "%~dp0"

npm run tauri -- dev
