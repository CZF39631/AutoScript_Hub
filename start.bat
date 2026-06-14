@echo off
chcp 65001 >nul

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [错误] 未找到虚拟环境，请先运行 python setup.py --server
    pause
    exit /b 1
)

if not exist "%ROOT%\config.json" (
    echo [错误] 未找到配置文件，请先运行 python setup.py --server
    pause
    exit /b 1
)

echo ========================================
echo   AutoScript Hub 服务端
echo ========================================
echo.
"%PYTHON%" backend\app\main.py
pause
