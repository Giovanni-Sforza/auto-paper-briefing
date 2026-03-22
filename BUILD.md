# ============================================================
#  Auto-Paper-Briefing PyInstaller 打包说明
#
#  使用 PyInstaller 将项目打包为单文件可执行程序：
#    Windows → auto-paper-briefing.exe
#    macOS   → auto-paper-briefing（Unix 可执行文件）
#    Linux   → auto-paper-briefing
#
#  注意：必须在目标平台上分别打包（不支持交叉编译）。
# ============================================================

# ── 安装 PyInstaller ──────────────────────────────────────────
# pip install pyinstaller

# ── 打包命令（推荐）─────────────────────────────────────────────
# python -m PyInstaller auto-paper-briefing.spec

# ── 或直接用命令行参数打包 ──────────────────────────────────────
# python -m PyInstaller \
#     --onefile \
#     --name auto-paper-briefing \
#     --add-data "config.yaml:." \
#     --hidden-import yaml \
#     --hidden-import fitz \
#     main.py

# ── 打包 setup 向导 ──────────────────────────────────────────
# python -m PyInstaller \
#     --onefile \
#     --name apb-setup \
#     setup.py

# ── 打包后的文件位置 ──────────────────────────────────────────
# dist/auto-paper-briefing   (macOS/Linux)
# dist/auto-paper-briefing.exe  (Windows)
# dist/apb-setup             (向导，macOS/Linux)
# dist/apb-setup.exe         (向导，Windows)

# ── 分发给朋友的文件 ──────────────────────────────────────────
# 将以下文件放在同一文件夹中发给对方：
#   auto-paper-briefing（或 .exe）
#   apb-setup（或 .exe）
#   requirements.txt（备用）
# 对方首次运行 apb-setup，配置完成后运行 auto-paper-briefing。
