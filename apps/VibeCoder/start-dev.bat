@echo off
cd /d "%~dp0backend"
pip install -r requirements.txt --quiet 2>nul
python main.py --server --port 5180
