@echo off
:: CADEN VibeCoder - Global CLI launcher
:: Add the folder containing this file to your system PATH
:: Then just type "vibe" from any terminal

setlocal
set "VIBECODER_DIR=%~dp0backend"

:: Activate venv if it exists
if exist "%VIBECODER_DIR%\.venv\Scripts\activate.bat" (
    call "%VIBECODER_DIR%\.venv\Scripts\activate.bat"
)

python "%VIBECODER_DIR%\main.py" %*
endlocal
