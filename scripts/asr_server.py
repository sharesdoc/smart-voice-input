#!/usr/bin/env python
"""局域网 SenseVoice ASR 服务 — 兼容 OpenAI /v1/audio/transcriptions 接口。

【Mac Studio 启动方式】
    # 先确保已安装依赖
    pip install fastapi uvicorn python-multipart

    # 启动（默认监听所有网卡，端口 8765）
    python scripts/asr_server.py

    # 自定义参数
    python scripts/asr_server.py --port 8765 --language zh --device auto

【客户机（本机）配置方式】
    设置 → 语音识别 → 引擎选「在线 ASR」
    在线 BaseURL : http://<Mac-Studio-局域网IP>:8765/v1
    在线模型    : SenseVoiceSmall   （服务端忽略此字段，随便填）
    API Key    : （留空，本地服务不验证）

【测试连通性】
    curl http://<ip>:8765/health
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import wave

import numpy as np


# ── 把项目根目录加入 path，便于 import voiceinput ──
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _decode_wav(data: bytes) -> np.ndarray | None:
    """WAV bytes → float32 numpy array（与 OnlineASR._encode_wav 对称）。"""
    try:
        buf = io.BytesIO(data)
        with wave.open(buf) as w:
            sampwidth = w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sampwidth == 2:
            return np.frombuffer(raw, dtype="<i2").astype("float32") / 32767.0
        if sampwidth == 4:
            return np.frombuffer(raw, dtype="<i4").astype("float32") / 2147483647.0
        return None
    except Exception as exc:
        print(f"[warn] 音频解码失败: {exc}")
        return None


def build_app(language: str, device: str):
    """构建 FastAPI app，预加载 SenseVoice 模型。"""
    try:
        from fastapi import FastAPI, Form, UploadFile
        from fastapi.responses import JSONResponse
    except ImportError:
        print("缺少依赖，请先执行：pip install fastapi uvicorn python-multipart")
        sys.exit(1)

    from voiceinput.asr import SenseVoiceASR

    print(f"[info] 加载 SenseVoice 模型（device={device}, language={language}）…")
    asr = SenseVoiceASR(language=language, device=device)
    asr._ensure_model()
    print("[info] 模型就绪 ✓")

    app = FastAPI(title="VoiceInput ASR Server")

    @app.get("/health")
    def health():
        return {"status": "ok", "engine": "SenseVoice"}

    @app.post("/v1/audio/transcriptions")
    async def transcribe(
        file: UploadFile,
        model: str = Form(default="SenseVoiceSmall"),   # 服务端忽略
        language: str = Form(default=None),              # 可选，覆盖启动参数
    ):
        data = await file.read()
        audio = _decode_wav(data)
        if audio is None or len(audio) == 0:
            return JSONResponse({"text": ""})
        # 若请求里带 language 参数则动态切换（按段识别不同语言）
        if language and language != asr.language:
            old, asr.language = asr.language, language
            text = asr.transcribe(audio)
            asr.language = old
        else:
            text = asr.transcribe(audio)
        return {"text": text or ""}

    return app


def main():
    parser = argparse.ArgumentParser(
        description="局域网 SenseVoice ASR HTTP 服务（OpenAI API 兼容）")
    parser.add_argument("--host", default="0.0.0.0",
                        help="监听地址，默认 0.0.0.0（所有网卡）")
    parser.add_argument("--port", type=int, default=8765,
                        help="监听端口，默认 8765")
    parser.add_argument("--language", default="zh",
                        help="识别语言：zh/en/auto，默认 zh")
    parser.add_argument("--device", default="auto",
                        help="推理设备：auto/mps/cpu，默认 auto（Apple Silicon 自动用 MPS）")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("缺少依赖，请先执行：pip install fastapi uvicorn python-multipart")
        sys.exit(1)

    app = build_app(args.language, args.device)
    print(f"[info] 服务启动 → http://{args.host}:{args.port}")
    print(f"[info] 客户机 Base URL: http://<本机IP>:{args.port}/v1")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
