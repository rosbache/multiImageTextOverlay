@echo off
cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo Starting Image Metadata Overlay web UI...
echo Open http://localhost:8000 in your browser
echo Press Ctrl+C to stop the server
echo.

uvicorn web_app:app --host 127.0.0.1 --port 8000

pause
