#!/bin/bash
# Auto-Paper-Briefing 一键启动脚本 (macOS / Linux)

set -e

echo ""
echo "============================================================"
echo "  Auto-Paper-Briefing - 个人AI学术追踪系统"
echo "============================================================"
echo ""

# ── 检查 Python ────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未检测到 python3，请先安装 Python 3.10+。"
    echo "  macOS:  brew install python3"
    echo "  Ubuntu: sudo apt install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PYTHON_VERSION" -lt 10 ]; then
    echo "[警告] 检测到 Python 3.${PYTHON_VERSION}，建议使用 3.10 或更高版本。"
fi

# 切换到脚本所在目录（双击启动时确保路径正确）
cd "$(dirname "$0")"

# ── 检查并安装依赖 ────────────────────────────────────────────
echo "[检查] 正在验证依赖包..."
if ! python3 -c "import yaml" &>/dev/null; then
    echo "[安装] 正在安装依赖包，请稍候..."
    pip3 install -r requirements.txt
fi

# ── 首次运行：启动配置向导 ────────────────────────────────────
if [ ! -f "config.yaml" ]; then
    echo "[提示] 未找到 config.yaml，将启动初始化向导..."
    echo ""
    python3 setup.py
    echo ""
fi

# ── 启动主程序 ────────────────────────────────────────────────
echo "[启动] 正在启动 Auto-Paper-Briefing..."
echo ""
echo "  简报将生成至 reports/ 目录"
echo "  种子管理界面：http://127.0.0.1:19523/"
echo "  按 Ctrl+C 停止程序"
echo ""

# 如需通过环境变量传入 API Key（config.yaml 中 api_key 留空时使用）：
# export AI_API_KEY="sk-xxxxxxxxxxxxxxxx"

python3 main.py "$@"
