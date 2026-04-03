@echo off
echo ============================================
echo  PedalForge Setup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)
echo [OK] Python found

:: Create venv
echo [SETUP] Creating virtual environment...
python -m venv venv
call venv\Scripts\activate.bat

:: Install Python packages
echo [SETUP] Installing Python packages...
pip install -r backend\requirements.txt

:: Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+ from https://nodejs.org
    pause
    exit /b 1
)
echo [OK] Node.js found

:: Install frontend packages
echo [SETUP] Installing frontend packages...
cd frontend
npm install
cd ..

:: Check Ollama
echo.
echo [INFO] Optional dependencies:
echo.
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo  - Ollama: NOT RUNNING
    echo    Install from: https://ollama.com
    echo    Then run: ollama serve
    echo    Then pull a model: ollama pull mistral
) else (
    echo  - Ollama: OK
)

ngspice --version >nul 2>&1
if errorlevel 1 (
    echo  - ngspice: NOT FOUND
    echo    Install from: https://ngspice.sourceforge.io/
) else (
    echo  - ngspice: OK
)

echo.
echo ============================================
echo  Setup complete! Run start.bat to launch.
echo ============================================
pause
