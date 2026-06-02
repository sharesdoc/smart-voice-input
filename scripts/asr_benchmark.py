"""ASR 引擎速度基准测试（由 ./install -t 调用）。

对 4 个引擎输入**同一段音频**，预热后重复 N 次测量 transcribe 耗时，
输出每个引擎的 平均/中位/最小/最大 与实时率(RTF)，并按平均耗时排名找出最快者。

被测引擎：
  whisper_local  本地 Whisper (faster-whisper)
  mlx_whisper    本地 MLX Whisper (Apple Silicon)
  sensevoice     本地 SenseVoice (FunASR)
  dashscope      阿里云 Fun-ASR (在线)

缺依赖 / 缺模型 / 缺 API Key / 非 arm64 的引擎自动跳过并说明原因。

测试音频默认用 macOS `say` 合成一段中文语音（真实语音，四引擎都能解码）；
也可用 --wav 指定一个 16k 单声道 WAV。

用法:
  python scripts/asr_benchmark.py [--runs N] [--wav FILE] [--text "..."]
"""

from __future__ import annotations

import argparse
import contextlib
import os
import statistics
import sys
import time

# 让脚本能 import voiceinput（scripts/ 的上级即项目根）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 关闭第三方库(funasr/tqdm/hf_hub)的进度条与多余打印，保持报告干净
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


@contextlib.contextmanager
def _silence():
    """在底层文件描述符层面屏蔽 stdout/stderr（吞掉 funasr 等库的 C 级打印）。"""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_out, old_err = os.dup(1), os.dup(2)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        # 先把缓冲(如 funasr 导入时的版本打印)刷进 devnull，再恢复真实 fd
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(old_out, 1)
        os.dup2(old_err, 2)
        os.close(devnull)
        os.close(old_out)
        os.close(old_err)

SAMPLE_RATE = 16000

# (引擎内部值, 中文显示名)
ENGINES = [
    ("whisper_local", "本地Whisper(faster-whisper)"),
    ("mlx_whisper", "本地MLX Whisper(Apple)"),
    ("sensevoice", "本地SenseVoice-Small"),
    ("dashscope", "阿里云Fun-ASR(在线)"),
]

_DEFAULT_TEXT = "这是一段用于测试语音识别速度的中文语音样本，请尽快识别出来。"


# ---------------- 纯函数（可单测） ----------------

def summarize(times):
    """把多次耗时(秒)汇总为统计量。times 非空。"""
    return {
        "runs": len(times),
        "avg": statistics.mean(times),
        "median": statistics.median(times),
        "min": min(times),
        "max": max(times),
    }


def rank(results):
    """按平均耗时升序排出未跳过引擎的名次。

    results: {engine: {"summary": {...}} | {"skip": reason}}
    返回 [(engine, avg), ...]（升序，最快在前）。
    """
    ok = [(e, r["summary"]["avg"]) for e, r in results.items()
          if "summary" in r]
    return sorted(ok, key=lambda x: x[1])


# ---------------- 测试音频 ----------------

def _read_wav_f32(path):
    import wave

    import numpy as np

    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    return data, sr


def make_audio(wav, text):
    """返回 (float32 numpy 音频, 时长秒, 来源说明)。

    优先 --wav；否则用 macOS say 合成中文语音；失败则退化为合成音调。
    """
    import numpy as np

    if wav:
        data, sr = _read_wav_f32(wav)
        return data, len(data) / max(sr, 1), f"WAV 文件 {wav}"

    # macOS say → aiff → afconvert 16k 单声道 wav
    import subprocess
    import tempfile

    aiff = tempfile.mktemp(suffix=".aiff")
    wpath = tempfile.mktemp(suffix=".wav")
    try:
        voice_tried = False
        for cmd in (["say", "-v", "Tingting", "-o", aiff, text],
                    ["say", "-o", aiff, text]):
            try:
                subprocess.run(cmd, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                voice_tried = True
                break
            except Exception:
                continue
        if voice_tried:
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                 aiff, wpath],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            data, sr = _read_wav_f32(wpath)
            if len(data) > 0:
                return data, len(data) / sr, "macOS say 合成中文语音"
    except Exception:
        pass
    finally:
        for p in (aiff, wpath):
            try:
                os.unlink(p)
            except Exception:
                pass

    # 退化：3 秒合成音调（非真实语音，仅测纯计算延迟）
    secs = 3.0
    t = np.arange(int(SAMPLE_RATE * secs)) / SAMPLE_RATE
    sig = 0.1 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 440 * t))
    sig *= np.hanning(len(t))
    return sig.astype("float32"), secs, "合成音调(say 不可用，结果仅供参考)"


# ---------------- 单引擎基准 ----------------

def _build_engine(name):
    from voiceinput.asr import make_asr
    from voiceinput.config import load_config

    cfg = load_config()         # 用用户当前配置(模型名等)，更贴近真实使用
    cfg.asr.engine = name
    cfg.general.language = "zh"
    return cfg, make_asr(cfg)


def bench_engine(name, audio, runs):
    """对单个引擎做基准。返回 {"summary":...,"sample":...} 或 {"skip":reason}。"""
    import platform

    if name == "mlx_whisper" and platform.machine() != "arm64":
        return {"skip": "仅 Apple Silicon(arm64) 可用"}

    try:
        cfg, asr = _build_engine(name)
    except Exception as exc:
        return {"skip": f"创建失败: {exc}"}

    if name == "dashscope":
        from voiceinput.config import resolve_dashscope_key
        src = cfg.asr.dashscope_key_source
        if not (resolve_dashscope_key(src) or resolve_dashscope_key("env")):
            return {"skip": "无 DASHSCOPE_API_KEY（env 或钥匙串）"}

    # 预热：加载/下载模型 + 跑一次（不计时），排除冷启动影响
    try:
        with _silence():
            if hasattr(asr, "_ensure_model"):
                asr._ensure_model()
            sample = asr.transcribe(audio)
    except Exception as exc:
        msg = str(exc).replace("\n", " ")
        return {"skip": f"不可用(缺依赖/模型/网络): {msg[:160]}"}

    times = []
    for _ in range(runs):
        try:
            with _silence():
                t0 = time.monotonic()
                sample = asr.transcribe(audio)
                dt = time.monotonic() - t0
        except Exception as exc:
            return {"skip": f"运行出错: {exc}"}
        times.append(dt)

    return {"summary": summarize(times), "sample": (sample or "").strip()}


# ---------------- 报告 ----------------

def _fmt_row(label, summ, dur):
    rtf = summ["avg"] / dur if dur else 0.0
    return (f"  {label:<26} 次数={summ['runs']:<2} "
            f"平均={summ['avg']:.3f}s 中位={summ['median']:.3f}s "
            f"最小={summ['min']:.3f}s 最大={summ['max']:.3f}s RTF={rtf:.2f}x")


def run_benchmark(runs, wav, text):
    import platform

    print("=" * 70)
    print("ASR 引擎速度基准测试")
    print("=" * 70)
    audio, dur, src = make_audio(wav, text)
    print(f"测试音频: {src} | 时长≈{dur:.2f}s | 采样率={SAMPLE_RATE}Hz")
    print(f"每引擎重复次数: {runs}（另有 1 次预热不计时） | 架构: {platform.machine()}")
    print(f"指标: 平均/中位/最小/最大 耗时(秒)；RTF=平均耗时/音频时长(越小越快)")
    print("-" * 70)

    results = {}
    for name, label in ENGINES:
        print(f"▶ 测试 {label} ({name}) …", flush=True)
        res = bench_engine(name, audio, runs)
        results[name] = res
        if "skip" in res:
            print(f"  ⏭ 跳过：{res['skip']}")
        else:
            print(_fmt_row(label, res["summary"], dur))
            print(f"     识别样本: {res['sample'][:40]!r}")
    print("-" * 70)

    order = rank(results)
    if not order:
        print("没有可用引擎完成测试（全部被跳过）。请先 ./install -i 安装依赖与模型，"
              "或设置 DASHSCOPE_API_KEY。")
        return results

    print("排名（按平均耗时升序，越靠前越快）:")
    label_map = dict(ENGINES)
    for i, (name, avg) in enumerate(order, 1):
        rtf = avg / dur if dur else 0.0
        flag = "  ⏩ 最快" if i == 1 else ""
        print(f"  {i}. {label_map[name]:<26} 平均 {avg:.3f}s (RTF {rtf:.2f}x){flag}")

    fastest = label_map[order[0][0]]
    print("-" * 70)
    print(f"结论: 最快引擎为 【{fastest}】，平均 {order[0][1]:.3f}s/段。")
    print("=" * 70)
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="ASR 引擎速度基准测试")
    ap.add_argument("--runs", type=int, default=5, help="每引擎重复次数(默认5)")
    ap.add_argument("--wav", default=None, help="自定义 16k 单声道 WAV；不填则用 say 合成")
    ap.add_argument("--text", default=_DEFAULT_TEXT, help="say 合成所用文本")
    args = ap.parse_args(argv)
    run_benchmark(args.runs, args.wav, args.text)


if __name__ == "__main__":
    main()
