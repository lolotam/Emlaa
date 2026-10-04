# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['source/notq.py'],
    pathex=[],
    binaries=[],
    datas=[('source/notq.ico', '.'), ('source/notq.png', '.'), ('source/ui', 'ui')],
    hiddenimports=['pystray._win32', 'app_web', 'webview', 'clr',
                   'comtypes.gen.UIAutomationClient', 'comtypes.gen.stdole',
                   'comtypes.gen._944DE083_8FB8_45CF_BCB7_C477ACB2F897_0_1_0',
                   'comtypes.gen._00020430_0000_0000_C000_000000000046_0_2_0'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Emlaa',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['source/notq.ico'],
)
