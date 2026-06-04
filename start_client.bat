@echo off
chcp 65001 >nul

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ERROR] venv not found. 请先运行 python setup.py --client
    pause
    exit /b 1
)

if not exist "%ROOT%\client_config.json" (
    echo [ERROR] client_config.json not found. 请先运行 python setup.py --client
    pause
    exit /b 1
)

echo ========================================
echo   AutoScript Hub Client
echo ========================================
echo.
"%PYTHON%" client\start.py
pause
