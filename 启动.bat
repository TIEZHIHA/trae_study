@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   医药知识图谱问答系统
echo ============================================

py -3 -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo 首次运行，正在安装依赖...
    py -3 -m pip install -r requirements.txt
    if errorlevel 1 (
        echo 依赖安装失败，请检查 Python 与网络。
        pause
        exit /b 1
    )
)

echo 正在启动服务，浏览器将自动打开 http://127.0.0.1:8000
start "" /b py -3 -c "import time, webbrowser; time.sleep(2); webbrowser.open('http://127.0.0.1:8000')"

py -3 GUI.py
pause
