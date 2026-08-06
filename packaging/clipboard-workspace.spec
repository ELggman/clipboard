# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec：onedir（onefile 冷启动解压慢，冲击 <1s 启动目标）
# 构建入口：bash packaging/build.sh

from PyInstaller.utils.hooks import collect_submodules

APP_NAME = "Clipboard Workspace"
BUNDLE_ID = "com.clipboardworkspace.app"  # 一经发布不可更改（TCC 授权绑定）

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[],
    datas=[
        # 内置配置与 Action 插件目录（运行时加载，静态分析收集不到）
        ("../config", "config"),
        ("../actions", "actions"),
    ],
    hiddenimports=collect_submodules("actions"),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed：无终端（日志走 logs/）
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=APP_NAME,
    icon=None,  # TODO: resources/icon.icns 后替换
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "LSUIElement": True,  # accessory 应用：菜单栏常驻，Dock 无图标
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "NSHighResolutionCapable": True,
    },
)
