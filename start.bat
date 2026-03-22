@echo off
chcp 65001 >nul
title Auto-Paper-Briefing

echo.
echo ============================================================
echo   Auto-Paper-Briefing - 个人AI学术追踪系统
echo ============================================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或更高版本。
    echo        下载地址：https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 检查配置文件
if not exist "config.yaml" (
    echo [提示] 未找到 config.yaml，将启动初始化向导...
    echo.
    python setup.py
    if errorlevel 1 (
        echo [错误] 初始化向导运行失败。
        pause
        exit /b 1
    )
    echo.
)

:: 检查依赖
echo [检查] 正在验证依赖包...
python -c "import yaml" >nul 2>&1
if errorlevel 1 (
    echo [安装] 正在安装依赖包，请稍候...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )
)

echo [启动] 正在启动 Auto-Paper-Briefing...
echo.
echo   简报将生成至 reports\ 目录
echo   种子管理界面：http://127.0.0.1:19523/
echo   按 Ctrl+C 停止程序
echo.

:: 读取环境变量（如果 config.yaml 中 api_key 为空，则从环境变量读取）
:: 如需设置，取消下一行注释并填写你的 Key：
:: set AI_API_KEY=sk-xxxxxxxxxxxxxxxx

python main.py %*

echo.
echo 程序已退出。
pause
