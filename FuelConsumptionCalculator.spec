# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

sys.path.insert(0, str(Path(SPECPATH) / "src"))
from fuel_consumption_calculator.config import APPLICATION_VERSION

a = Analysis(
    ["main.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=["playwright.sync_api", "openpyxl", "openpyxl.styles"],
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
    [],
    exclude_binaries=True,
    name="FuelConsumptionCalculator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=f"FuelConsumptionCalculator-{APPLICATION_VERSION}",
)
