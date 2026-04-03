@echo off
echo ============================================
echo  PedalForge - Guitar Pedal Design Studio
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

:: Check if venv exists
if not exist "venv" (
    echo [SETUP] Creating Python virtual environment...
    python -m venv venv
)

:: Activate venv
call venv\Scripts\activate.bat

:: Install Python dependencies
echo [SETUP] Installing Python dependencies...
pip install -r backend\requirements.txt -q

:: Check if node_modules exists
if not exist "frontend\node_modules" (
    echo [SETUP] Installing frontend dependencies...
    cd frontend
    npm install
    cd ..
)

:: Check Ollama
echo [CHECK] Checking Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [WARN] Ollama not detected. AI features will be unavailable.
    echo        Start Ollama with: ollama serve
    echo        Then pull a model: ollama pull mistral
) else (
    echo [OK] Ollama is running
)

:: Check ngspice
ngspice --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] ngspice not found. SPICE validation will be unavailable.
    echo        Install from: https://ngspice.sourceforge.io/
) else (
    echo [OK] ngspice found
)

echo.
echo [START] Starting PedalForge...
echo         Backend:  http://localhost:8000
echo         Frontend: http://localhost:3000
echo.

:: Start backend in background
start "PedalForge Backend" cmd /c "venv\Scripts\activate.bat && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"

:: Wait a moment for backend to start
timeout /t 2 /nobreak >nul

:: Start frontend
cd frontend
start "PedalForge Frontend" cmd /c "npm run dev"
cd ..

:: Open browser
timeout /t 3 /nobreak >nul
start http://localhost:3000

echo.
echo PedalForge is running. Close this window to stop.
echo Press any key to stop all services...
pause >nul

:: Cleanup
taskkill /FI "WINDOWTITLE eq PedalForge Backend" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq PedalForge Frontend" /F >nul 2>&1
echo PedalForge stopped.
