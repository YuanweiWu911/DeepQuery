# build.spec
block_cipher = None

a = Analysis(
    ['__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('static/*', 'static'),
        ('templates/*', 'templates'),
        ('services/*.py', 'services'),
        ('app.py', '.'),
        ('config.py', '.'),
    ],
    hiddenimports=[
        'services.api_handler',
        'services.audio_util',
        'services.voice_service',
        'paramiko.transport',
        'pynvml',
        'paramiko.ed25519key',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
     	'asyncio'
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
    name='DeepQuery',
    icon='static/favicon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 隱藏控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True
)
