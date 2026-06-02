"""ASR 配置逻辑测试 (FR-05)。

不加载 Whisper 模型，仅验证提示词选择/计算后端选择等纯逻辑。
"""

from voiceinput.asr import _ZH_SIMPLIFIED_PROMPT, WhisperASR, _pick_compute


def test_chinese_uses_simplified_prompt_by_default():
    """中文默认启用简体偏置提示词（避免 Whisper 输出繁体）。"""
    asr = WhisperASR(language="zh")
    assert asr.initial_prompt == _ZH_SIMPLIFIED_PROMPT


def test_custom_prompt_overrides_default():
    asr = WhisperASR(language="zh", initial_prompt="自定义术语：MyApp。")
    assert asr.initial_prompt == "自定义术语：MyApp。"


def test_non_chinese_no_default_prompt():
    asr = WhisperASR(language="en")
    assert asr.initial_prompt is None


def test_pick_compute_auto_to_int8():
    assert _pick_compute("auto") == "int8"
    assert _pick_compute("metal") == "int8"


def test_pick_compute_explicit_kept():
    assert _pick_compute("float16") == "float16"
    assert _pick_compute("cpu") == "cpu"


def test_empty_audio_returns_empty():
    asr = WhisperASR()
    assert asr.transcribe([]) == ""
    assert asr.transcribe(None) == ""


def test_dehallucinate_filters_repeats_and_subtitle_spam():
    from voiceinput.asr import _dehallucinate
    # 重复 token 幻觉
    assert _dehallucinate("B3" * 50) == ""
    assert _dehallucinate("啊啊啊啊啊啊啊啊啊啊") == ""
    # 已知字幕/打赏话术幻觉
    assert _dehallucinate("请不吝点赞 订阅 转发 打赏支持明镜与点点栏目") == ""
    assert _dehallucinate("感谢观看 请订阅") == ""  # 两个标记
    assert _dehallucinate("字幕由 Amara.org 社区提供") == ""
    # 正常文本不应被误杀
    assert _dehallucinate("今天天气很好，我们去公园。") == "今天天气很好，我们去公园。"
    assert _dehallucinate("我要订阅这个杂志") == "我要订阅这个杂志"  # 仅1个标记
    assert _dehallucinate("") == ""
