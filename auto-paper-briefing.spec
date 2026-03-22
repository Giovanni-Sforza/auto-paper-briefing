# -*- mode: python ; coding: utf-8 -*-
# auto-paper-briefing.spec — PyInstaller 打包配置
# 用法：python -m PyInstaller auto-paper-briefing.spec

import sys
import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # 如果 config.yaml 已存在，打包进去作为默认配置
        ('config.yaml', '.') if os.path.exists('config.yaml') else ('requirements.txt', '.'),
    ],
    hiddenimports=[
        'yaml',
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
        # PyMuPDF（如已安装）
        'fitz',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    console=True,          # 保留终端窗口，方便查看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows 图标（可选，替换为你自己的 .ico 文件）
    # icon='icon.ico',
)

# ── setup 向导的单独打包 ──────────────────────────────────────

a_setup = Analysis(
    ['setup.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['yaml'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
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
    # icon='icon.ico',
)
