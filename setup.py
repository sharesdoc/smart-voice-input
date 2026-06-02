"""py2app 打包配置 (M4)。

打包为常驻菜单栏 .app（无 Dock 图标，LSUIElement）。
用法：
    ~/ins/miniconda/bin/python -m pip install py2app
    ~/ins/miniconda/bin/python setup.py py2app          # 产出 dist/VoiceInput.app

注意：faster-whisper/pyobjc 体积较大；首次打包较慢。Apple Silicon 上产出
arm64 .app，Intel 机器上产出 x86_64 .app（按 D-04，代码兼容双架构）。
"""

from setuptools import setup

APP = ["voiceinput/__main__.py"]

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "VoiceInput",
        "CFBundleDisplayName": "VoiceInput",
        "CFBundleIdentifier": "com.voiceinput.app",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        # 菜单栏常驻应用：隐藏 Dock 图标
        "LSUIElement": True,
        # 权限用途说明（FR-13）
        "NSMicrophoneUsageDescription": "用于采集语音进行识别输入。",
        "NSAppleEventsUsageDescription": "用于将识别文本注入当前输入框。",
    },
    "packages": ["voiceinput"],
    "includes": ["rumps", "pynput", "httpx", "sounddevice", "numpy"],
    # faster-whisper 模型在运行时下载到用户缓存，不打入包
    "excludes": ["tkinter", "matplotlib"],
}

setup(
    name="VoiceInput",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
