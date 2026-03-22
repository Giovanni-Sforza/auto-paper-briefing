# -*- mode: python ; coding: utf-8 -*-
# auto-paper-briefing.spec
#
# 本地打包：python -m PyInstaller auto-paper-briefing.spec
# CI 打包：  由 .github/workflows/build.yml 自动触发

import os
import sys

block_cipher = None

# ── 获取 certifi CA 证书路径（打包时写入，运行时读取）─────────────
try:
    import certifi
    certifi_cacert = (certifi.where(), "certifi")   # (源路径, 打包后目标目录)
    certifi_hidden = ['certifi']
except ImportError:
    certifi_cacert = None
    certifi_hidden = []
    print("WARNING: certifi not installed. SSL may fail on macOS after packaging.")
    print("         Run: pip install certifi")

# ── 主程序：auto-paper-briefing ───────────────────────────────

_datas_main = [('modules', 'modules')]
if certifi_cacert:
    _datas_main.append(certifi_cacert)

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=_datas_main,
    hiddenimports=[
        'yaml',
        'certifi',
        'ssl',
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
    ] + certifi_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ── 初始化向导：apb-setup ─────────────────────────────────────

_datas_setup = []
if certifi_cacert:
    _datas_setup.append(certifi_cacert)

a_setup = Analysis(
    ['setup.py'],
    pathex=['.'],
    binaries=[],
    datas=_datas_setup,
    hiddenimports=[
        'yaml',
        'certifi',
        'ssl',
        'xml.etree.ElementTree',
        'http.server',
        'urllib.request',
        'webbrowser',
        'threading',
    ] + certifi_hidden,
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
