@echo off
title Veloce Video Downloader Launcher
color 0B
echo ==============================================================
echo       Veloce Video Downloader Launcher
echo ==============================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python is not installed or not added to system PATH!
    echo Please download and install Python from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: 2. Check dependencies
echo [1/3] Checking environment dependencies...
python -c "import flask, yt_dlp" >nul 2>&1
if %errorlevel% neq 0 (
    color 0E
    echo [INFO] Missing required packages. Installing flask and yt-dlp...
    python -m pip install --upgrade pip
    python -m pip install flask yt-dlp
    if %errorlevel% neq 0 (
        color 0C
        echo [ERROR] Failed to install dependencies via pip!
        echo Please try running "pip install flask yt-dlp" in terminal manually.
        pause
        exit /b 1
    )
    color 0B
    echo [SUCCESS] Dependencies installed successfully.
) else (
    echo [INFO] Dependencies verified.
)

:: 3. Create downloads directory
echo.
echo [2/3] Preparing downloads directory...
if not exist downloads (
    mkdir downloads
    echo [INFO] Created folder: downloads/
) else (
    echo [INFO] Folder downloads/ already exists.
)

:: 4. Start Flask server
echo.
echo [3/3] Starting the backend server...
echo [INFO] Your browser will open http://127.0.0.1:5000 automatically.
echo [INFO] Please keep this command prompt window open while using the app.
echo.

timeout /t 1 /nobreak >nul
start http://127.0.0.1:5000

python app.py

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo [ERROR] Server exited with code: %errorlevel%
    pause
)
