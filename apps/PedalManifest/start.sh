#!/bin/bash
echo "============================================"
echo " PedalForge - Guitar Pedal Design Studio"
echo "============================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 not found. Please install Python 3.11+"
    exit 1
fi

# Create venv if needed
if [ ! -d "venv" ]; then
    echo "[SETUP] Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install Python deps
echo "[SETUP] Installing Python dependencies..."
pip install -r backend/requirements.txt -q

# Install frontend deps if needed
if [ ! -d "frontend/node_modules" ]; then
    echo "[SETUP] Installing frontend dependencies..."
    cd frontend && npm install && cd ..
fi

# Check Ollama
echo "[CHECK] Checking Ollama..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "[OK] Ollama is running"
else
    echo "[WARN] Ollama not detected. AI features will be unavailable."
    echo "       Start Ollama with: ollama serve"
    echo "       Then pull a model: ollama pull mistral"
fi

# Check ngspice
if command -v ngspice &> /dev/null; then
    echo "[OK] ngspice found"
else
    echo "[WARN] ngspice not found. SPICE validation will be unavailable."
fi

echo ""
echo "[START] Starting PedalForge..."
echo "        Backend:  http://localhost:8000"
echo "        Frontend: http://localhost:3000"
echo ""

# Start backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

sleep 2

# Start frontend
cd frontend && npm run dev &
FRONTEND_PID=$!
cd ..

sleep 3

# Open browser
if command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:3000
elif command -v open &> /dev/null; then
    open http://localhost:3000
fi

echo ""
echo "PedalForge is running. Press Ctrl+C to stop."

# Handle shutdown
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'PedalForge stopped.'; exit 0" SIGINT SIGTERM
wait
