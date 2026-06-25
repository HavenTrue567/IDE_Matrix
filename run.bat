@echo off
title TermIDE Launcher
echo ==========================================
echo TermIDE - Starting Local Backend Service
echo ==========================================
echo.

:: Check if virtual environment exists
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Creating one...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Ensure Python is installed.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment created. Installing dependencies...
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)

:: Start the server
echo [INFO] Starting Flask + SocketIO server...
echo [INFO] Your browser should open automatically at http://127.0.0.1:5000
echo [INFO] Press Ctrl+C in this terminal window to stop the server.
echo.

.venv\Scripts\python.exe server.py

if errorlevel 1 (
    echo.
    echo [WARNING] Server stopped with error or was forced to close.
    pause
)
