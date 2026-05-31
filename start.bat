@echo off
chcp 65001 >nul

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ERROR] venv not found. Please run setup.py first.
    pause
    exit /b 1
)

if not exist "%ROOT%\config.json" (
    echo [ERROR] config.json not found. Please run setup.py first.
    pause
    exit /b 1
)

wt --title "Backend" -d "%ROOT%" cmd /k ""%PYTHON%" backend\app\main.py" ^; new-tab --title "Frontend" -d "%ROOT%\frontend" cmd /k "npm run dev" ^; new-tab --title "Agent" -d "%ROOT%" cmd /k ""%PYTHON%" -m client.agent.main"
