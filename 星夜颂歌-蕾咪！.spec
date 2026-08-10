# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['Remy.py'],
    pathex=[],
    binaries=[],
    datas=[('Remy_Shut.png', '.'), ('Remy_Open.png', '.'), ('Remy_Angry.png', '.'), ('Remy_Expect.png', '.'), ('Remy_Wronged.png', '.'), ('Remy_Happy.png', '.'), ('Remy_Sleep.png', '.'), ('Remy_Dangle.png', '.'), ('shortcuts.json', '.'), ('help.md', '.'), ('config.example.json', '.')],
    hiddenimports=[],
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
    name='星夜颂歌-蕾咪！',
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
    icon=['Remybaby.ico'],
)
