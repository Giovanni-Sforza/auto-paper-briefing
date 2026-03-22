# -*- mode: python ; coding: utf-8 -*-
# auto-paper-briefing.spec
#
# 本地打包：python -m PyInstaller auto-paper-briefing.spec
# CI 打包：  由 .github/workflows/build.yml 自动触发

import os

block_cipher = None

# ── 主程序：auto-paper-briefing ───────────────────────────────

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # modules 目录整体打包（确保所有子模块都能被找到）
        ('modules', 'modules'),
    ],
    hiddenimports=[
        'yaml',
        'xml.etree.ElementTree',
        'http.server',
        'urllib.request',
        'urllib.parse',
        'urllib.error',
        'modules.config_loader',
        'modules.history_manager',
        'modules.arxiv_fetcher',
        'modules.pdf_processor',
        'modules.ai_summarizer',
        'modules.report_generator',
        'modules.click_tracker',
        'modules.keyword_evolver',
        'modules.seed_manager',
        'modules.likes_manager',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除不需要的大型库，减小体积
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='auto-paper-briefing',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # 保留终端窗口，方便查看运行日志
    disable_windowed_traceback=False,
    argv_emulation=False,   # macOS 专用，False 避免双击行为异常
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ── 初始化向导：apb-setup ─────────────────────────────────────

a_setup = Analysis(
    ['setup.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'yaml',
        'xml.etree.ElementTree',
        'http.server',
        'urllib.request',
        'webbrowser',
        'threading',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    cipher=block_cipher,
)

pyz_setup = PYZ(a_setup.pure, a_setup.zipped_data, cipher=block_cipher)

exe_setup = EXE(
    pyz_setup,
    a_setup.scripts,
    a_setup.binaries,
    a_setup.zipfiles,
    a_setup.datas,
    [],
    name='apb-setup',
    debug=False,
    strip=False,
    upx=True,
    console=True,
    argv_emulation=False,
)
