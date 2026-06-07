"""配置加载/保存与敏感信息存储 (FR-11/FR-12)。

- 配置以 JSON 存于 ~/Library/Application Support/VoiceInput/config.json。
- API Key 等敏感信息优先存入 macOS 钥匙串（keyring）；不可用时降级到
  配置文件并记录提示（绝不静默明文，但保证可用）。
- 提供 dataclass 化的强类型配置，带默认值；与需求文档 §8 配置规格对应。

纯逻辑（合并默认值/序列化）可单测；钥匙串访问做了懒加载与降级。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_KEYCHAIN_SERVICE = "VoiceInput"
_KEYCHAIN_ACCOUNT = "online_api_key"
_KEYCHAIN_DASHSCOPE = "dashscope_api_key"

DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct-q4_K_M"


@dataclass
class GeneralConfig:
    language: str = "zh"          # 识别语言：zh 中文 | en 英文
    autostart: bool = False       # 开机自启 (FR-14)
    play_sound: bool = True       # 触发提示音
    inject_method: str = "paste"  # paste | keystroke (FR-10)
    # 连续听写：触发一次后持续监听，按停顿自动切段输入，再次触发才停止 (FR-03)
    continuous_dictation: bool = True


@dataclass
class HotkeyConfig:
    # 触发方式：double_command(默认,双击⌘) | custom_hotkey(自定义组合键) 已实现；
    # push_to_talk 暂未实现，设为该值会回退 double_command 并告警 (见 hotkey.IMPLEMENTED_TRIGGERS)。
    trigger: str = "double_command"
    double_tap_ms: int = 300               # 双击 Command 最大间隔
    custom_hotkey: str = "ctrl+option+space"  # trigger=custom_hotkey 时生效，如 'ctrl+option+space'


@dataclass
class AsrConfig:
    engine: str = "whisper_local"  # whisper_local | mlx_whisper | sensevoice | dashscope | online
    whisper_model: str = "small"   # tiny|base|small|medium
    compute: str = "auto"          # auto|metal|cpu
    initial_prompt: str = ""       # 自定义偏置提示词；空则中文自动用简体偏置
    # MLX Whisper (Apple Silicon MLX 加速；HF repo)
    mlx_model: str = "mlx-community/whisper-large-v3-turbo"
    # SenseVoice (极快本地引擎，自带标点)
    sensevoice_model: str = "FunAudioLLM/SenseVoiceSmall"
    # SenseVoice ASR HTTP 服务端口（局域网共享用，startup-asr-server 使用）
    sensevoice_server_port: int = 18765
    # 阿里云 DashScope Fun-ASR (在线)
    dashscope_model: str = "paraformer-realtime-v2"
    # Key 来源：env=用环境变量 DASHSCOPE_API_KEY | manual=用手动输入(存钥匙串)
    dashscope_key_source: str = "env"
    # 在线 ASR (FR-06)；API Key 复用在线 LLM 的钥匙串项
    online_base_url: str = "https://api.openai.com/v1"
    online_model: str = "whisper-1"
    # 强制过滤：配置只存纯文字；匹配时自动忽略识别结果里的空格与尾部标点。
    # 用于过滤引擎幻觉短语，如 "Yeah"。
    force_filter_phrases: list = field(default_factory=lambda: [
        "我", "我的", "我是", "是的", "Yeah", "字幕by索兰娅", "嗯", "嗯嗯",
    ])


@dataclass
class VadConfig:
    """语音活动检测/自动断句 (FR-04)。

    默认开启：按一次快捷键进入听写，说完停顿即自动断句并打字，无需再次按键。
    """
    enabled: bool = True
    silence_threshold: float = 0.036  # RMS 静音阈值（+80% 于原 0.02，逐次 20% 收敛）
    silence_sec: float = 1.0         # 连续静音多久判定结束（更跟手）
    min_speech_sec: float = 0.3      # 至少检测到这么长语音后才允许结束
    # 软封顶（针对放录音/少停顿场景）：单段超 soft_cap_sec 后逐步放宽所需静音，
    # 就近在微停顿处切段；达 hard_cap_sec 仍无停顿则硬切兜底。0 表示禁用。
    # 注：在线 ASR/翻译有单次时长上限且 30s 超时，使用在线引擎时建议调小（如 25/40）。
    soft_cap_sec: float = 180.0      # 3 分钟开始放宽静音要求
    hard_cap_sec: float = 360.0      # 6 分钟绝对上限（硬切兜底）
    soft_cap_step_sec: float = 60.0  # 阶梯减半的步进间隔（秒）
    auto_polish_on_hard_cut: bool = True  # 强制切段后自动启用 Ollama 智能润色
    # 底噪幻觉拦截：SenseVoice 等引擎会把环境底噪误识别成短词（如"我。"）。
    # 判据用"语音时长"（去掉静音/背景后真正有声的累计秒数）而非整段缓冲长度——
    # 识别出 N 个字却几乎没有真实语音 → 判为幻觉跳过注入；前面有长静音的真短词不误杀。
    noise_filter: bool = True
    # 各字数所需的"最少语音时长(秒)"：识别出 N 字但有声语音不足对应秒数 → 判噪音。
    # 仅 1/2/3 字做此检查，4 字及以上不限。某项填 0 表示该字数不拦截。可在设置页改。
    # 默认偏保守：只拦"几乎没发声"的纯底噪幻觉，正常语速的真短词(实测低至~0.06s)一律放行。
    noise_min_voice_1char_sec: float = 0.05
    noise_min_voice_2char_sec: float = 0.05
    noise_min_voice_3char_sec: float = 0.07


@dataclass
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = DEFAULT_OLLAMA_MODEL


@dataclass
class OnlineConfig:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    # api_key 不在此存储；运行时从钥匙串读取并注入。


@dataclass
class LlmConfig:
    enabled: bool = True
    mode: str = "ollama"  # ollama | online | off
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    online: OnlineConfig = field(default_factory=OnlineConfig)
    # 语音输入后处理要求稳定、少改写，默认用低随机性。
    temperature: float = 0.0
    timeout_sec: int = 20
    # 限制异常长输出；0 表示不限制。
    max_output_tokens: int = 512
    # off | low | medium | high。off 优先用于禁用思考模型，降低延迟并避免改写原话。
    reasoning: str = "off"
    # 兜底清理 thinking 模型泄露的 <think>...</think> 或“思考过程”前缀。
    strip_thinking: bool = True


@dataclass
class DenoiseConfig:
    """神经网络降噪 (DeepFilterNet3)，基于 ONNX Runtime 实时降噪。

    默认关闭，避免影响现有行为。用户手动在设置中开启。
    降噪在 VAD 之前执行——先清理音频中的环境噪声，再做人声检测和识别。
    加载失败或处理异常时自动直通原始音频，不阻断录音链路。
    """
    enabled: bool = False
    engine: str = "onnx"              # onnx | subprocess
    onnx_model_path: str = "deepfilternet3.onnx"  # 相对于 config_dir 或绝对路径
    attenuation: float = 0.8          # 降噪强度 0.0~1.0
    dry_wet_mix: float = 0.9          # 干湿混合比 0.0~1.0
    resample_quality: str = "fast"     # fast | high


@dataclass
class PostprocessConfig:
    # 默认 polish：仅纠错别字 + 补标点，**保持原话**，忠实且快。
    # organize(深度重组语序) 可在设置切换，但短句可能被改写曲解，按需启用。
    mode: str = "polish"  # raw | polish | organize | translate (FR-09)
    translate_target: str = "en"
    prompt_template: str = ""  # 空表示用内置模板（见 llm.py）


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    denoise: DenoiseConfig = field(default_factory=DenoiseConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    postprocess: PostprocessConfig = field(default_factory=PostprocessConfig)

    # ---- 序列化 ----

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """从（可能不完整的）字典构造，缺失字段回退默认值。"""
        def build(klass, sub: dict | None):
            sub = sub or {}
            kwargs = {}
            for f in klass.__dataclass_fields__.values():  # type: ignore[attr-defined]
                if f.name in sub:
                    kwargs[f.name] = sub[f.name]
            return klass(**kwargs)

        llm_raw = data.get("llm", {}) or {}
        llm = build(LlmConfig, {k: v for k, v in llm_raw.items()
                                if k not in ("ollama", "online")})
        llm.ollama = build(OllamaConfig, llm_raw.get("ollama"))
        llm.online = build(OnlineConfig, llm_raw.get("online"))

        return cls(
            general=build(GeneralConfig, data.get("general")),
            hotkey=build(HotkeyConfig, data.get("hotkey")),
            asr=build(AsrConfig, data.get("asr")),
            vad=build(VadConfig, data.get("vad")),
            denoise=build(DenoiseConfig, data.get("denoise")),
            llm=llm,
            postprocess=build(PostprocessConfig, data.get("postprocess")),
        )


# ---- 路径 ----

def config_dir() -> Path:
    """配置目录，允许通过环境变量覆盖（便于测试）。"""
    override = os.environ.get("VOICEINPUT_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Application Support" / "VoiceInput"


def config_path() -> Path:
    return config_dir() / "config.json"


# ---- 加载/保存 ----

def load_config() -> Config:
    """加载配置；不存在或损坏时返回默认配置（不抛异常，保证可启动）。"""
    path = config_path()
    if not path.exists():
        return Config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Config.from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError):
        # 损坏配置不应阻止启动（NFR-04）。
        return Config()


def save_config(cfg: Config) -> None:
    """保存配置到磁盘（API Key 不写入此文件）。"""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---- 钥匙串（敏感信息） ----

def set_api_key(key: str) -> bool:
    """把在线 API Key 存入钥匙串。返回是否成功（keyring 不可用则 False）。"""
    try:
        import keyring  # 懒加载

        keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT, key)
        return True
    except Exception:
        return False


def set_dashscope_key(key: str) -> bool:
    """手动 DashScope API Key 存入钥匙串。"""
    try:
        import keyring

        keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_DASHSCOPE, key)
        return True
    except Exception:
        return False


def get_dashscope_key() -> str | None:
    """读取手动存的 DashScope API Key（不含环境变量）。"""
    try:
        import keyring

        return keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_DASHSCOPE)
    except Exception:
        return None


def resolve_dashscope_key(source: str) -> str | None:
    """按来源解析 DashScope Key：manual→钥匙串，否则→环境变量。"""
    if source == "manual":
        return get_dashscope_key()
    return os.environ.get("DASHSCOPE_API_KEY")


def delete_api_key() -> bool:
    """从钥匙串删除在线 API Key（用于恢复默认）。返回是否成功。"""
    try:
        import keyring  # 懒加载

        keyring.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT)
        return True
    except Exception:
        return False


def get_api_key() -> str | None:
    """从钥匙串读取在线 API Key；不可用或未设置返回 None。"""
    # 环境变量优先（便于 CI / 临时使用）
    env = os.environ.get("VOICEINPUT_ONLINE_API_KEY")
    if env:
        return env
    try:
        import keyring  # 懒加载

        return keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT)
    except Exception:
        return None
