"""菜单栏应用与流程编排 (FR-01/FR-02, §7)。

依赖 rumps（懒加载，仅 macOS）。负责：
- 顶部状态栏图标与状态显示；
- 菜单：开始/停止、后处理模式、引擎、设置、关于、退出；
- 串联 双击⌘热键 → 录音 → Pipeline(ASR→LLM→注入/重写)。

业务流程在 pipeline.Pipeline 中（已单测）；本文件只做 UI 装配与线程调度，
在非 macOS 环境不导入也可被测试其余模块。
"""

from __future__ import annotations

import queue
import threading

from . import __app_name__, __version__
from .audio import Recorder
from .config import DEFAULT_OLLAMA_MODEL, Config, load_config, save_config
from .hotkey import GlobalHotkeyListener
from .injector import make_injector
from .llm import list_ollama_models
from .pipeline import Pipeline
from .state import AppState, StateMachine

# 停顿检测时长允许范围（秒）
_PAUSE_MIN = 0.2
_PAUSE_MAX = 5.0

# 进入听写时的提示音（general.play_sound）。系统自带音效，非阻塞播放。
_START_SOUND = "/System/Library/Sounds/Tink.aiff"


def _afplay(sound_path: str) -> None:
    """非阻塞播放系统音效（macOS afplay）。模块级以便测试 monkeypatch。"""
    import subprocess

    subprocess.Popen(
        ["afplay", sound_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def parse_pause_seconds(text: str):
    """解析用户输入的停顿时长 → 秒（float）。无法解析返回 None。

    支持：'0.8'(秒) / '800ms' / '500'(无单位且≥20 视为毫秒) / '1s'。
    结果 clamp 到 [_PAUSE_MIN, _PAUSE_MAX]。
    """
    t = (text or "").strip().lower().replace(" ", "").replace("秒", "s")
    if not t:
        return None
    is_ms = False
    if t.endswith("ms"):
        t = t[:-2]
        is_ms = True
    elif t.endswith("s"):
        t = t[:-1]
    try:
        v = float(t)
    except ValueError:
        return None
    if is_ms:
        v /= 1000.0
    elif v >= 20:          # 无单位且较大 → 视为毫秒
        v /= 1000.0
    v = max(_PAUSE_MIN, min(_PAUSE_MAX, v))
    return round(v, 3)


def parse_online_form(text: str) -> dict:
    """解析在线模型设置对话框的 key=value 文本（纯函数，可单测）。"""
    out: dict = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, val = line.split("=", 1)
        out[k.strip().lower()] = val.strip()
    return out


# ============ 统一系统配置页：枚举值 + 字段定义（中英对照） ============
# 枚举：内部值 → (中文显示, 英文显示)
_ENUMS: dict[str, list] = {
    "language": [("zh", "中文", "Chinese"), ("en", "英文", "English")],
    "asr_engine": [
        ("whisper_local", "本地Whisper(faster-whisper)", "Local Whisper (faster-whisper)"),
        ("mlx_whisper", "本地MLX Whisper(Apple加速)", "Local MLX Whisper (Apple)"),
        ("sensevoice", "本地SenseVoice-Small", "Local SenseVoice-Small"),
        ("dashscope", "阿里云Fun-ASR", "Aliyun Fun-ASR"),
        ("online", "在线OpenAI", "Online OpenAI"),
    ],
    "ppmode": [
        ("raw", "纯转写", "Raw"),
        ("polish", "智能纠错润色", "Polish"),
        ("organize", "智能整理", "Organize"),
        ("translate", "翻译", "Translate"),
    ],
    "llm_mode": [
        ("ollama", "本地Ollama", "Local Ollama"),
        ("online", "在线", "Online"),
        ("off", "关闭", "Off"),
    ],
    "reasoning": [
        ("off", "关闭思考(默认)", "Off (default)"),
        ("low", "低", "Low"),
        ("medium", "中", "Medium"),
        ("high", "高", "High"),
    ],
    "dskey_source": [
        ("env", "使用环境变量 DASHSCOPE_API_KEY", "Use env DASHSCOPE_API_KEY"),
        ("manual", "手动输入", "Manual input"),
    ],
    "bool": [(True, "开", "On"), (False, "关", "Off")],
}

# 字段标签：id → (中文, 英文)
_LABELS: dict[str, tuple] = {
    "language": ("语言", "Language"),
    "asr_engine": ("语音识别引擎", "ASR engine"),
    "whisper_model": ("Whisper模型", "Whisper model"),
    "mlx_model": ("MLX Whisper模型", "MLX Whisper model"),
    "dashscope_key_source": ("Fun-ASR Key来源", "Fun-ASR key source"),
    "dashscope_key": ("Fun-ASR API Key", "Fun-ASR API Key"),
    "continuous": ("连续听写", "Continuous"),
    "pause": ("停顿秒数", "Pause seconds"),
    "soft_cap": ("开始探测断句(秒)", "Start probing (sec)"),
    "hard_cap": ("强制切断时间(秒)", "Force cut (sec)"),
    "soft_cap_step": ("探测间隔(秒)", "Probe interval (sec)"),
    "auto_polish_on_hard_cut": ("强制切自动润色", "Auto-polish on force cut"),
    "silence_threshold": ("静音阈值(VAD)", "Silence threshold (VAD)"),
    "noise_filter": ("底噪幻觉拦截", "Noise filter"),
    "noise_min_voice_1char": ("1字最少语音(秒)", "1-char min voice (s)"),
    "noise_min_voice_2char": ("2字最少语音(秒)", "2-char min voice (s)"),
    "noise_min_voice_3char": ("3字最少语音(秒)", "3-char min voice (s)"),
    "ppmode": ("后处理模式", "Post-process"),
    "llm_mode": ("大模型引擎", "LLM engine"),
    "ollama_model": ("Ollama模型", "Ollama model"),
    "online_base": ("在线BaseURL", "Online BaseURL"),
    "online_model": ("在线模型", "Online model"),
    "online_key": ("在线APIKey", "Online APIKey"),
    "llm_temperature": ("随机性/温度", "Temperature"),
    "llm_max_output_tokens": ("输出上限", "Max output tokens"),
    "llm_reasoning": ("思考/推理", "Reasoning"),
    "llm_strip_thinking": ("清理思考内容", "Strip thinking"),
    "prompt_template": ("自定义系统提示词", "Custom system prompt"),
    "autostart": ("开机自启", "Launch at login"),
    "force_filter": ("强制过滤短语", "Force-filter phrases"),
    "asr_online_base":  ("ASR服务BaseURL", "ASR BaseURL"),
    "asr_online_model": ("ASR服务模型",    "ASR model"),
    "asr_online_key":   ("ASR服务APIKey",  "ASR API Key"),
    "denoise_enabled": ("神经网络降噪", "Neural denoising"),
    "denoise_attenuation": ("降噪强度", "Denoise strength"),
    "denoise_dry_wet_mix": ("干湿混合比", "Dry/wet mix"),
    "svr_port": ("SenseVoice 服务端口", "Server port"),
    "svr_control": ("SenseVoice 服务", "Server"),
}

# 设置页布局（有序）：("H",(中,英)) 分组标题；("C",(中,英)) 说明注释；
# ("F", id, enum或None, kind) 字段。kind: enum/free/secret
def _enum_display(enum: str, internal, lang: str) -> str:
    for it in _ENUMS[enum]:
        if it[0] == internal:
            return it[1] if lang == "zh" else it[2]
    return str(internal)


def _enum_parse(enum: str, text: str):
    t = (text or "").strip()
    tl = t.lower()
    for internal, zh, en in _ENUMS[enum]:
        if t == zh or tl == en.lower() or tl == str(internal).lower():
            return internal
    if enum == "bool":
        if tl in ("开", "on", "yes", "true", "1", "是"):
            return True
        if tl in ("关", "off", "no", "false", "0", "否"):
            return False
    return None


class VoiceInputApp:
    """主应用。run() 进入 rumps 事件循环。"""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or load_config()
        self._busy = threading.Lock()
        self._recorder = Recorder()
        self._finished = False  # 防 VAD/手动重复结束
        self._sm = StateMachine(on_change=self._on_state_change)
        self._asr = None  # 懒加载
        self._app = None
        self._listener: GlobalHotkeyListener | None = None
        self._status_item = None
        self._current_pipeline: Pipeline | None = None  # 供抢占检测 (FR-17)
        # 连续听写会话状态
        self._continuous_active = False
        self._seg_queue: queue.Queue | None = None
        self._worker: threading.Thread | None = None
        self._stop_worker: threading.Event | None = None
        from .logsetup import get_logger

        self._log = get_logger()  # run() 中再配置文件处理器
        from .diag import OutputMonitor

        # 每段输出监控：记录实际输出文本并检测疑似重复，写入日志便于稳定性分析
        self._out_monitor = OutputMonitor()
        # 降噪引擎缓存（懒加载，配置变更时清除）
        self._denoise_cache = None
        # 启动时检测 Ollama 可用性：不可用则自动关闭"强制切自动润色"
        self._check_and_disable_auto_polish_if_ollama_gone()

    # ---- ASR 懒加载 ----

    def _get_asr(self):
        if self._asr is None:
            from .asr import make_asr

            self._asr = make_asr(self.cfg)  # 按 engine 选本地/在线 (FR-05/06)
        return self._asr

    # ---- 状态 → 菜单栏 ----

    def _on_state_change(self, old: AppState, new: AppState) -> None:
        if self._app is not None:
            self._app.title = new.icon
            if self._status_item is not None:
                self._status_item.title = (
                    self._t("status_prefix") + self._t(f"state_{new.name}")
                )

    def _t(self, key: str, **fmt) -> str:
        """按当前界面语言取文案。"""
        from .i18n import tr

        return tr(self.cfg.general.language, key, **fmt)

    def _activate(self) -> None:
        """弹模态窗前激活 App 到前台。

        菜单栏应用默认是 accessory 策略（无 Dock 图标），此时 NSAlert/NSWindow
        不会显示在最前、模态会占住事件循环导致"死机/菜单变灰"。必须临时把激活
        策略切到 Regular 并激活，窗口才会弹出到前台。
        """
        try:
            from AppKit import (
                NSApplication,
                NSApplicationActivationPolicyRegular,
            )

            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            app.activateIgnoringOtherApps_(True)
        except Exception as exc:
            self._log.debug("激活到前台失败(忽略): %s", exc)

    def _deactivate(self) -> None:
        """模态窗关闭后恢复 accessory 策略（隐藏 Dock 图标）。"""
        try:
            from AppKit import (
                NSApplication,
                NSApplicationActivationPolicyAccessory,
            )

            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory)
        except Exception as exc:
            self._log.debug("恢复 accessory 策略失败(忽略): %s", exc)

    def _alert(self, title: str, message: str) -> None:
        """前台弹出提示框（激活→弹窗→恢复），规避菜单栏应用弹窗卡死。"""
        import rumps

        self._activate()
        try:
            rumps.alert(title=title, message=message)
        finally:
            self._deactivate()

    def _error_alert_with_log_button(self, title: str, message: str) -> None:
        """显示错误弹框，并提供查看日志按钮。"""
        self._activate()
        try:
            try:
                from AppKit import NSAlert

                alert = NSAlert.alloc().init()
                alert.setMessageText_(title)
                alert.setInformativeText_(message)
                alert.addButtonWithTitle_("确定")
                alert.addButtonWithTitle_("查看日志")
                resp = alert.runModal()
                if int(resp) == 1001:  # NSAlertSecondButtonReturn
                    self._open_log(None)
            except Exception:
                self._alert(title, message)
        finally:
            self._deactivate()

    def _set_state(self, name: str) -> None:
        """pipeline 回调用字符串名设置状态。"""
        try:
            target = AppState[name]
        except KeyError:
            return
        if target == AppState.IDLE:
            self._sm.force_idle()
        elif self._sm.can_transition(target):
            self._sm.transition(target)

    def _set_state_listening(self, name: str) -> None:
        """连续听写专用状态回调：处理完一段后回到 LISTENING（仍在监听）。"""
        if not self._continuous_active:
            self._set_state(name)
            return
        try:
            target = AppState[name]
        except KeyError:
            return
        if target == AppState.IDLE:
            target = AppState.LISTENING  # 一段处理完仍在持续监听
        self._sm.set_state(target)

    def _play_start_sound(self) -> None:
        """进入听写时播放提示音（仅当 general.play_sound 开启）。失败仅 debug 记录。"""
        if not self.cfg.general.play_sound:
            return
        try:
            _afplay(_START_SOUND)
        except Exception as exc:
            self._log.debug("提示音播放失败(忽略): %s", exc)

    # ---- 录音触发（双击⌘） ----

    def _on_double_tap(self) -> None:
        # 在后台线程处理，避免阻塞监听线程
        threading.Thread(target=self._toggle_listening, daemon=True).start()

    def _toggle_listening(self) -> None:
        if self.cfg.general.continuous_dictation:
            if self._continuous_active:
                self._stop_continuous()
            else:
                self._start_continuous()
        else:
            # 切换式（旧行为，可在设置关闭连续听写时使用）
            if self._recorder.is_recording:
                self._finish_and_process()
            else:
                self._start_record()

    # ---- 连续听写（默认）：一次触发，持续监听，按停顿自动分段输入 ----

    @staticmethod
    def _effective_vad_caps(engine: str, soft: float, hard: float):
        """按 ASR 引擎返回生效的软封顶上限 (X-103 审查整改 [2])。

        在线引擎(dashscope/online)单次时长有上限且约 30s 超时，长段会整段失败，
        故收紧到安全值(25/40s)，不依赖用户手动改配置；本地引擎用配置原值。
        """
        if engine in ("dashscope", "online"):
            soft = min(soft, 25.0) if soft > 0 else 25.0
            hard = min(hard, 40.0) if hard > 0 else 40.0
        return soft, hard

    def _new_continuous_recorder(self):
        from .audio import Recorder, SilenceDetector

        # 连续听写必须有 VAD 来切段（即使 cfg.vad.enabled 关闭也强制启用）
        # 软封顶：放录音/少停顿时单段过长会逐步放宽所需静音，就近切段避免无限累积。
        soft, hard = self._effective_vad_caps(
            self.cfg.asr.engine, self.cfg.vad.soft_cap_sec, self.cfg.vad.hard_cap_sec)
        vad = SilenceDetector(
            silence_threshold=self.cfg.vad.silence_threshold,
            silence_sec=self.cfg.vad.silence_sec,
            min_speech_sec=self.cfg.vad.min_speech_sec,
            soft_cap_sec=soft,
            hard_cap_sec=hard,
            soft_cap_step_sec=self.cfg.vad.soft_cap_step_sec,
        )
        denoise = self._get_denoise_engine()
        return Recorder(vad=vad, on_segment=self._enqueue_segment, denoise=denoise)

    def _enqueue_segment(self, seg, speech_sec: float = 0.0) -> None:
        """采集线程回调：仅入队(段音频, VAD语音时长)，耗时处理交给 worker。"""
        if self._seg_queue is not None:
            self._seg_queue.put((seg, speech_sec))

    def _segment_worker(self) -> None:
        """后台顺序处理每个语音段：ASR → LLM → 注入，保证输入顺序。"""
        injector = make_injector(self.cfg.general.inject_method)
        transcribe = self._get_asr().transcribe
        assert self._stop_worker is not None and self._seg_queue is not None
        while not self._stop_worker.is_set():
            try:
                item = self._seg_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if item is None:                       # 关闭哨兵
                self._seg_queue.task_done()
                break
            seg, speech_sec = item                 # (段音频, VAD 语音时长)
            try:
                pipeline = Pipeline(
                    cfg=self.cfg,
                    injector=injector,
                    transcribe_fn=transcribe,
                    on_state=self._set_state_listening,
                )
                self._current_pipeline = pipeline
                res = pipeline.run(seg, speech_sec=speech_sec)
                self._out_monitor.record(res.final_text)
            except Exception as exc:
                self._log.warning("分段处理失败: %s", exc)
            finally:
                self._current_pipeline = None
                self._seg_queue.task_done()

    def _start_continuous(self) -> None:
        if not self._busy.acquire(blocking=False):
            return
        try:
            self._continuous_active = True
            self._seg_queue = queue.Queue()
            self._stop_worker = threading.Event()
            self._worker = threading.Thread(target=self._segment_worker, daemon=True)
            self._worker.start()
            self._recorder = self._new_continuous_recorder()
            self._sm.set_state(AppState.LISTENING)
            self._play_start_sound()
            self._recorder.start()
            self._log.info("进入连续听写：说话即自动分段输入；再次触发快捷键停止。")
        except Exception as exc:
            self._log.warning("启动连续听写失败: %s", exc)
            self._continuous_active = False
            # 通知 worker 退出并唤醒阻塞在 get() 的线程，避免泄漏
            if self._stop_worker is not None:
                self._stop_worker.set()
            if self._seg_queue is not None:
                self._drain_queue(self._seg_queue)
                self._seg_queue.put(None)
            self._sm.force_idle()
            if self._busy.locked():
                self._busy.release()

    @staticmethod
    def _drain_queue(q: "queue.Queue") -> None:
        """清空队列中尚未处理的语音段（丢弃），不阻塞。"""
        try:
            while True:
                q.get_nowait()
                q.task_done()
        except queue.Empty:
            pass

    def _stop_continuous(self) -> None:
        self._continuous_active = False
        # 1) 先停采集：不再产生新语音段
        try:
            self._recorder.stop()
        except Exception as exc:
            self._log.debug("停止录音失败(忽略): %s", exc)
        # 2) 通知 worker 停止（处理完/取消当前段后退出，不再取新段）
        if self._stop_worker is not None:
            self._stop_worker.set()
        # 3) 清空排队中尚未处理的语音段，并唤醒可能阻塞在 get() 的 worker
        if self._seg_queue is not None:
            self._drain_queue(self._seg_queue)
            self._seg_queue.put(None)
        # 4) 取消正在处理的那一段：丢弃其结果、不再注入（协作式取消）
        cur = self._current_pipeline
        if cur is not None:
            try:
                cur.cancel()
            except Exception as exc:
                self._log.debug("取消当前流水线失败(忽略): %s", exc)
        self._sm.force_idle()
        if self._busy.locked():
            self._busy.release()
        self._log.info("已退出连续听写（已清空待处理语音段）。")

    # ---- 切换式（回退路径，仅在关闭连续听写时使用） ----

    def _get_denoise_engine(self):
        """创建（或返回缓存的）降噪引擎实例。

        未启用时返回 None。引擎加载失败时也返回 None（不阻断录音）。
        配置变更时需先调用 _clear_denoise_cache() 使旧实例失效。
        """
        if not self.cfg.denoise.enabled:
            return None
        if hasattr(self, '_denoise_cache') and self._denoise_cache is not None:
            return self._denoise_cache
        from .denoise import make_denoise_engine
        dc = self.cfg.denoise
        self._log.info(
            "创建降噪引擎: engine=%s enabled=%s attenuation=%.2f dry_wet=%.2f "
            "resample=%s model=%s",
            dc.engine, dc.enabled, dc.attenuation, dc.dry_wet_mix,
            dc.resample_quality, dc.onnx_model_path)
        engine = make_denoise_engine(dc)
        self._denoise_cache = engine
        if engine is not None:
            self._log.info("降噪引擎已就绪")
        else:
            self._log.info("降噪引擎不可用（模型未找到或依赖缺失），录音链路直通")
        return engine

    def _clear_denoise_cache(self) -> None:
        """清除降噪引擎缓存（配置变更后调用）。"""
        self._denoise_cache = None

    def _new_recorder(self):
        from .audio import Recorder, SilenceDetector

        vad = None
        if self.cfg.vad.enabled:
            # 软封顶与连续听写保持一致，避免用户自定义 soft/hard_cap 在切换式下失效。
            soft, hard = self._effective_vad_caps(
                self.cfg.asr.engine, self.cfg.vad.soft_cap_sec, self.cfg.vad.hard_cap_sec)
            vad = SilenceDetector(
                silence_threshold=self.cfg.vad.silence_threshold,
                silence_sec=self.cfg.vad.silence_sec,
                min_speech_sec=self.cfg.vad.min_speech_sec,
                soft_cap_sec=soft,
                hard_cap_sec=hard,
                soft_cap_step_sec=self.cfg.vad.soft_cap_step_sec,
            )
        denoise = self._get_denoise_engine()
        return Recorder(vad=vad, on_auto_stop=self._on_vad_stop, denoise=denoise)

    def _start_record(self) -> None:
        if not self._busy.acquire(blocking=False):
            return
        try:
            self._recorder = self._new_recorder()
            self._finished = False
            self._sm.transition(AppState.LISTENING)
            self._play_start_sound()
            self._recorder.start()
        except Exception as exc:
            self._log.warning("启动录音失败: %s", exc)
            self._sm.force_idle()
            self._busy.release()

    def _on_vad_stop(self) -> None:
        threading.Thread(target=self._finish_and_process, daemon=True).start()

    def _finish_and_process(self) -> None:
        if getattr(self, "_finished", False):
            return
        self._finished = True
        try:
            audio = self._recorder.stop()
            pipeline = Pipeline(
                cfg=self.cfg,
                injector=make_injector(self.cfg.general.inject_method),
                transcribe_fn=self._get_asr().transcribe,
                on_state=self._set_state,
            )
            self._current_pipeline = pipeline
            res = pipeline.run(audio)
            self._out_monitor.record(res.final_text)
        except Exception:
            self._sm.force_idle()
        finally:
            self._current_pipeline = None
            if self._busy.locked():
                self._busy.release()

    # ---- 设置应用逻辑（纯逻辑，可单测，无 rumps 依赖） ----

    def apply_language(self, lang: str) -> None:
        """切换语言（zh/en）：同时切换①识别输出语言 ②界面文字。

        失效 ASR 缓存以按新语言重建；并重建菜单使界面文字即时跟随。
        """
        changed = lang != self.cfg.general.language
        self.cfg.general.language = lang
        self._asr = None
        save_config(self.cfg)
        if changed:
            self._rebuild_menu()

    def _ollama_available(self) -> bool:
        """向 Ollama /api/tags 发轻量请求检测是否可用（3s 超时）。"""
        try:
            from .llm import check_ollama_available
            return check_ollama_available(self.cfg, timeout=3)
        except Exception:
            return False

    def _check_and_disable_auto_polish_if_ollama_gone(self) -> None:
        """启动时检测：Ollama 不可用则自动关闭强制切润色。"""
        if not self.cfg.vad.auto_polish_on_hard_cut:
            return
        if not self._ollama_available():
            self._log.warning("Ollama 不可用，自动关闭「强制切自动润色」")
            self.cfg.vad.auto_polish_on_hard_cut = False
            save_config(self.cfg)

    def apply_continuous(self, enabled: bool) -> None:
        self.cfg.general.continuous_dictation = enabled
        save_config(self.cfg)

    def apply_vad_silence(self, sec: float) -> None:
        """设置停顿检测时长(秒)：静音超过该时长即判定一句说完、触发识别/输入。"""
        sec = max(_PAUSE_MIN, min(_PAUSE_MAX, float(sec)))
        self.cfg.vad.silence_sec = round(sec, 3)
        save_config(self.cfg)

    def apply_postprocess_mode(self, mode: str) -> None:
        self.cfg.postprocess.mode = mode
        save_config(self.cfg)

    def apply_llm_mode(self, mode: str) -> None:
        self.cfg.llm.mode = mode
        save_config(self.cfg)

    def apply_ollama_model(self, name: str) -> None:
        self.cfg.llm.ollama.model = name
        save_config(self.cfg)

    def apply_whisper_model(self, name: str) -> None:
        self.cfg.asr.whisper_model = name
        self._asr = None  # 失效缓存，下次按新模型重载
        save_config(self.cfg)

    def apply_asr_engine(self, engine: str) -> None:
        self.cfg.asr.engine = engine
        self._asr = None  # 失效缓存，下次按新引擎重建
        save_config(self.cfg)

    def apply_autostart(self, enabled: bool) -> bool:
        """开关开机自启 (FR-14)。返回操作是否成功。"""
        from . import autostart

        ok = autostart.enable() if enabled else autostart.disable()
        if ok:
            self.cfg.general.autostart = enabled
            save_config(self.cfg)
        return ok

    def apply_online_setting(self, field: str, value: str) -> None:
        if field == "base_url":
            self.cfg.llm.online.base_url = value
        elif field == "model":
            self.cfg.llm.online.model = value
        save_config(self.cfg)

    def apply_api_key(self, key: str) -> bool:
        """保存 API Key 到钥匙串，返回是否成功。"""
        from .config import set_api_key

        return set_api_key(key)

    def available_ollama_models(self) -> list[str]:
        return list_ollama_models(self.cfg)

    # ---- 菜单回调（UI 装配，需 rumps） ----

    def _make_picker(self, apply_fn, value, group: dict):
        """生成一个"选中即应用 + 刷新勾选"的回调。"""
        def handler(_sender):
            apply_fn(value)
            for v, item in group.items():
                item.state = 1 if v == value else 0
        return handler

    def _build_choice_menu(self, title, choices, current, apply_fn):
        """构建带勾选的单选子菜单。choices: {value: label}。"""
        import rumps

        menu = rumps.MenuItem(title)
        group: dict = {}
        for value, label in choices.items():
            item = rumps.MenuItem(label)
            group[value] = item
            item.set_callback(self._make_picker(apply_fn, value, group))
            item.state = 1 if value == current else 0
            menu.add(item)
        return menu

    def _make_pause_picker(self, sec: float, group: dict):
        def handler(_sender):
            self.apply_vad_silence(sec)
            for v, item in group.items():
                item.state = 1 if abs(v - sec) < 1e-6 else 0
        return handler

    def _build_pause_menu(self):
        import rumps

        menu = rumps.MenuItem(self._t("menu_pause"))
        self._pause_group: dict = {}
        cur = round(float(self.cfg.vad.silence_sec), 3)
        presets = [
            (0.3, "pause_fastest"),
            (0.5, "pause_05"),
            (0.8, "pause_08"),
            (1.0, "pause_default"),
            (1.5, "pause_15"),
            (2.0, "pause_complete"),
        ]
        for sec, key in presets:
            item = rumps.MenuItem(self._t(key))
            self._pause_group[sec] = item
            item.set_callback(self._make_pause_picker(sec, self._pause_group))
            item.state = 1 if abs(sec - cur) < 1e-6 else 0
            menu.add(item)
        menu.add(rumps.MenuItem(self._t("pause_custom"), callback=self._set_custom_pause))
        return menu

    def _set_custom_pause(self, _s) -> None:
        import rumps

        v = self._prompt(
            self._t("menu_pause"),
            self._t("pause_prompt"),
            str(self.cfg.vad.silence_sec),
        )
        if not v:
            return
        sec = parse_pause_seconds(v)
        if sec is None:
            self._alert(self._t("pause_title"), self._t("pause_bad"))
            return
        self.apply_vad_silence(sec)
        # 刷新预设勾选（自定义值可能不在预设中）
        for val, item in getattr(self, "_pause_group", {}).items():
            item.state = 1 if abs(val - sec) < 1e-6 else 0
        self._alert(self._t("pause_title"), self._t("pause_set", sec=f"{sec:g}"))

    def _build_ollama_menu(self):
        import rumps

        menu = rumps.MenuItem(self._t("menu_ollama_model"))
        models = self.available_ollama_models()
        if not models:
            menu.add(rumps.MenuItem(self._t("ollama_none")))
            return menu
        group: dict = {}
        cur = self.cfg.llm.ollama.model
        for name in models:
            item = rumps.MenuItem(name)
            group[name] = item
            item.set_callback(self._make_picker(self.apply_ollama_model, name, group))
            item.state = 1 if name == cur else 0
            menu.add(item)
        return menu

    def _prompt(self, title: str, message: str, default: str = "") -> str | None:
        """弹出单行输入窗，返回文本（取消返回 None）。"""
        import rumps

        self._activate()  # 菜单栏应用弹窗前激活，避免输入窗卡死
        win = rumps.Window(
            message=message, title=title, default_text=default,
            ok=self._t("btn_save"), cancel=self._t("btn_cancel"),
            dimensions=(340, 24),
        )
        resp = win.run()
        return resp.text.strip() if resp.clicked else None

    _KEY_PLACEHOLDER = "********"

    def _online_form_text(self) -> str:
        from .config import get_api_key

        key_line = self._KEY_PLACEHOLDER if get_api_key() else ""
        return (
            f"base_url={self.cfg.llm.online.base_url}\n"
            f"model={self.cfg.llm.online.model}\n"
            f"api_key={key_line}"
        )

    def _apply_online_form(self, text: str) -> None:
        """把对话框文本应用到配置并持久化（api_key 留占位符则不改）。"""
        form = parse_online_form(text)
        if form.get("base_url"):
            self.cfg.llm.online.base_url = form["base_url"]
        if form.get("model"):
            self.cfg.llm.online.model = form["model"]
        save_config(self.cfg)
        api = form.get("api_key", "")
        if api and api != self._KEY_PLACEHOLDER:
            self.apply_api_key(api)

    def _test_online(self) -> str:
        """用当前在线配置做一次连通测试，返回文案。"""
        from .config import Config
        from .llm import postprocess

        try:
            probe = Config.from_dict(self.cfg.to_dict())
            probe.llm.mode = "online"
            probe.postprocess.mode = "polish"
            r = postprocess(probe, "hello")
            return self._t("conn_online_ok") if r.ok else self._t("conn_fail", err=r.error)
        except Exception as exc:
            return self._t("conn_fail", err=exc)

    def _open_online_settings(self, _s) -> None:
        """单一对话框：填全部在线模型字段 + 保存 + 测试 (用户要求的统一设置页)。"""
        import rumps

        default_text = self._online_form_text()
        while True:
            self._activate()
            win = rumps.Window(
                message=self._t("online_form_msg"),
                title=self._t("menu_online_settings"),
                default_text=default_text,
                ok=self._t("btn_save"), cancel=self._t("btn_cancel"),
                dimensions=(380, 90),
            )
            win.add_button(self._t("online_test"))  # 额外按钮
            resp = win.run()

            if resp.clicked == 0:           # 取消
                return
            # 先把编辑内容落盘（保存与测试都基于最新输入）
            self._apply_online_form(resp.text)
            if resp.clicked == 1:           # 保存
                self._alert(self._t("menu_online_settings"), self._t("online_saved"))
                return
            # 其它（测试连接）：测后用最新文本重开对话框
            self._alert(self._t("conn_title"), self._test_online())
            default_text = self._online_form_text()

    def test_connection_message(self) -> str:
        """返回连通性测试结果文案（纯逻辑，可单测）。"""
        from .config import Config
        from .llm import postprocess

        if self.cfg.llm.mode == "ollama":
            models = self.available_ollama_models()
            return (self._t("conn_ollama_ok", n=len(models))
                    if models else self._t("conn_ollama_fail"))
        try:
            probe = Config.from_dict(self.cfg.to_dict())
            probe.postprocess.mode = "polish"
            r = postprocess(probe, "你好")
            return self._t("conn_online_ok") if r.ok else self._t("conn_fail", err=r.error)
        except Exception as exc:
            return self._t("conn_fail", err=exc)

    def default_ollama_model_missing_message(self) -> str:
        """默认 Ollama 模型缺失时的用户提示；无需提示则返回空字符串。"""
        if self.cfg.postprocess.mode == "raw":
            return ""
        if self.cfg.llm.mode != "ollama":
            return ""
        if self.cfg.llm.ollama.model != DEFAULT_OLLAMA_MODEL:
            return ""
        models = self.available_ollama_models()
        if DEFAULT_OLLAMA_MODEL in models:
            return ""
        cmd = f"ollama pull {DEFAULT_OLLAMA_MODEL}; ollama list"
        if self.cfg.general.language == "en":
            return (
                f"Default local model is not installed: {DEFAULT_OLLAMA_MODEL}\n\n"
                f"Run this command in Terminal:\n{cmd}"
            )
        return (
            f"未检测到默认本地文字加工模型：{DEFAULT_OLLAMA_MODEL}\n\n"
            f"请在终端执行：\n{cmd}"
        )

    def _warn_default_ollama_model_missing(self) -> None:
        msg = self.default_ollama_model_missing_message()
        if msg:
            self._alert(self._t("menu_ollama_model"), msg)


    # ---- 构建与运行 ----

    def _menu_items(self) -> list:
        """构建精简菜单：状态 + 听写开关 + 系统配置 + 关于 + 退出。

        所有设置项统一收进"系统配置"对话框（_open_system_settings）。
        """
        import rumps

        t = self._t
        self._status_item = rumps.MenuItem(
            t("status_prefix") + t(f"state_{self._sm.state.name}"))
        self._record_item = rumps.MenuItem(t("menu_record"), callback=self._menu_toggle_record)

        return [
            self._status_item,
            self._record_item,
            None,
            rumps.MenuItem(t("menu_system_settings"), callback=self._open_system_settings),
            rumps.MenuItem(t("menu_logs"), callback=self._open_log),
            rumps.MenuItem(t("menu_clear_logs"), callback=self._clear_logs),
            rumps.MenuItem(t("menu_about"), callback=self._open_about),
            None,
            rumps.MenuItem(t("menu_quit"), callback=self._quit),
        ]

    def _menu_items_legacy(self) -> list:
        """（旧版分散菜单，保留实现备用，不再挂载）"""
        import rumps
        from . import autostart as _autostart

        t = self._t
        self._status_item = rumps.MenuItem(
            t("status_prefix") + t(f"state_{self._sm.state.name}"))

        language_menu = self._build_choice_menu(
            t("menu_language"),
            {"zh": t("lang_zh"), "en": t("lang_en")},
            self.cfg.general.language, self.apply_language)

        mode_menu = self._build_choice_menu(
            t("menu_postprocess"),
            {"raw": t("mode_raw"), "polish": t("mode_polish"),
             "organize": t("mode_organize"), "translate": t("mode_translate")},
            self.cfg.postprocess.mode, self.apply_postprocess_mode)

        engine_menu = self._build_choice_menu(
            t("menu_llm_engine"),
            {"ollama": t("llm_ollama"), "online": t("llm_online"), "off": t("llm_off")},
            self.cfg.llm.mode, self.apply_llm_mode)

        asr_engine_menu = self._build_choice_menu(
            t("menu_asr_engine"),
            {"whisper_local": t("asr_local"), "sensevoice": t("asr_sensevoice"),
             "dashscope": t("asr_dashscope"), "online": t("asr_online")},
            self.cfg.asr.engine, self.apply_asr_engine)

        whisper_menu = self._build_choice_menu(
            t("menu_whisper_model"),
            {
                "tiny": "tiny (~75MB，最快)",
                "base": "base (~150MB)",
                "small": "small (~500MB，推荐)",
                "medium": "medium (~1.5GB，最准)",
            },
            self.cfg.asr.whisper_model, self.apply_whisper_model)

        # 单一菜单项 → 一个对话框填全部在线模型字段（用户要求）
        online_menu = rumps.MenuItem(t("menu_online_settings"),
                                     callback=self._open_online_settings)

        self._autostart_item = rumps.MenuItem(t("menu_autostart"), callback=self._toggle_autostart)
        self._autostart_item.state = 1 if _autostart.is_enabled() else 0

        self._continuous_item = rumps.MenuItem(
            t("menu_continuous"), callback=self._toggle_continuous_cfg)
        self._continuous_item.state = 1 if self.cfg.general.continuous_dictation else 0

        self._record_item = rumps.MenuItem(t("menu_record"), callback=self._menu_toggle_record)

        return [
            self._status_item,
            self._record_item,
            None,
            language_menu,
            mode_menu,
            engine_menu,
            self._build_ollama_menu(),
            asr_engine_menu,
            whisper_menu,
            self._continuous_item,
            self._build_pause_menu(),
            None,
            online_menu,
            self._autostart_item,
            rumps.MenuItem(t("menu_viewcfg"), callback=self._open_settings),
            rumps.MenuItem(t("menu_about"), callback=self._about),
            None,
            rumps.MenuItem(t("menu_quit"), callback=self._quit),
        ]

    def build(self):
        import rumps  # 懒加载

        app = rumps.App(__app_name__, title=AppState.IDLE.icon, quit_button=None)
        self._app = app
        app.menu = self._menu_items()
        return app

    def _rebuild_menu(self) -> None:
        """界面语言切换后重建菜单，使界面文字即时跟随语言。"""
        if self._app is None:
            return
        try:
            self._app.menu.clear()
            self._app.menu.update(self._menu_items())
        except Exception as exc:
            self._log.warning("重建菜单失败（重启后生效）: %s", exc)

    def _menu_toggle_record(self, _sender) -> None:
        self._on_double_tap()  # 复用双击触发的线程化逻辑

    def _toggle_continuous_cfg(self, sender) -> None:
        want = sender.state != 1
        self.apply_continuous(want)
        sender.state = 1 if want else 0

    def _toggle_autostart(self, sender) -> None:
        want = sender.state != 1
        ok = self.apply_autostart(want)
        if ok:
            sender.state = 1 if want else 0
        else:
            self._alert(self._t("menu_autostart"), self._t("autostart_fail"))

    # ---- 统一系统配置页 ----

    def _field_get(self, fid: str):
        c = self.cfg
        if fid == "dashscope_key":      # 明文显示已存的手动 Key
            from .config import get_dashscope_key
            return get_dashscope_key() or ""
        if fid == "asr_online_key":
            from .config import get_api_key
            return self._KEY_PLACEHOLDER if get_api_key() else ""
        if fid == "prompt_template":
            return c.postprocess.prompt_template or self._default_system_prompt()
        return {
            "language": c.general.language,
            "asr_engine": c.asr.engine,
            "whisper_model": c.asr.whisper_model,
            "mlx_model": c.asr.mlx_model,
            "continuous": c.general.continuous_dictation,
            "pause": c.vad.silence_sec,
            "ppmode": c.postprocess.mode,
            "llm_mode": c.llm.mode,
            "ollama_model": c.llm.ollama.model,
            "online_base": c.llm.online.base_url,
            "online_model": c.llm.online.model,
            "llm_temperature": c.llm.temperature,
            "llm_max_output_tokens": c.llm.max_output_tokens,
            "llm_reasoning": c.llm.reasoning,
            "llm_strip_thinking": c.llm.strip_thinking,
            "autostart": c.general.autostart,
            "dashscope_key_source": c.asr.dashscope_key_source,
            "soft_cap": c.vad.soft_cap_sec,
            "hard_cap": c.vad.hard_cap_sec,
            "soft_cap_step": c.vad.soft_cap_step_sec,
            "auto_polish_on_hard_cut": c.vad.auto_polish_on_hard_cut,
            "silence_threshold": c.vad.silence_threshold,
            "noise_filter": c.vad.noise_filter,
            "noise_min_voice_1char": c.vad.noise_min_voice_1char_sec,
            "noise_min_voice_2char": c.vad.noise_min_voice_2char_sec,
            "noise_min_voice_3char": c.vad.noise_min_voice_3char_sec,
            # 强制过滤：内部存纯文字 list，UI 层用英文逗号紧凑展示
            "force_filter": ",".join(c.asr.force_filter_phrases),
            "asr_online_base":  c.asr.online_base_url,
            "asr_online_model": c.asr.online_model,
            "denoise_enabled": c.denoise.enabled,
            "denoise_attenuation": c.denoise.attenuation,
            "denoise_dry_wet_mix": c.denoise.dry_wet_mix,
            "svr_port": c.asr.sensevoice_server_port,
        }.get(fid)

    def _field_set(self, fid: str, val) -> None:
        c = self.cfg
        if fid == "language":
            c.general.language = val
        elif fid == "asr_engine":
            c.asr.engine = val
        elif fid == "whisper_model":
            c.asr.whisper_model = val
        elif fid == "mlx_model":
            c.asr.mlx_model = val
        elif fid == "continuous":
            c.general.continuous_dictation = bool(val)
        elif fid == "pause":
            c.vad.silence_sec = float(val)
        elif fid == "ppmode":
            c.postprocess.mode = val
        elif fid == "llm_mode":
            c.llm.mode = val
        elif fid == "ollama_model":
            c.llm.ollama.model = val
        elif fid == "online_base":
            c.llm.online.base_url = val
        elif fid == "online_model":
            c.llm.online.model = val
        elif fid == "llm_temperature":
            c.llm.temperature = max(0.0, min(2.0, float(val)))
        elif fid == "llm_max_output_tokens":
            c.llm.max_output_tokens = max(0, min(4096, int(float(val))))
        elif fid == "llm_reasoning":
            c.llm.reasoning = val if val in {"off", "low", "medium", "high"} else "off"
        elif fid == "llm_strip_thinking":
            c.llm.strip_thinking = bool(val)
        elif fid == "prompt_template":
            text = str(val or "").strip()
            c.postprocess.prompt_template = "" if text == self._default_system_prompt() else text
        elif fid == "autostart":
            c.general.autostart = bool(val)
        elif fid == "online_key":
            if val and val != self._KEY_PLACEHOLDER:
                self.apply_api_key(val)
        elif fid == "dashscope_key_source":
            c.asr.dashscope_key_source = val
        elif fid == "dashscope_key":
            if val:
                from .config import set_dashscope_key
                set_dashscope_key(val)
        elif fid == "soft_cap":
            c.vad.soft_cap_sec = float(val)
        elif fid == "hard_cap":
            c.vad.hard_cap_sec = float(val)
        elif fid == "soft_cap_step":
            c.vad.soft_cap_step_sec = float(val)
        elif fid == "auto_polish_on_hard_cut":
            enabled = bool(val)
            if enabled and not self._ollama_available():
                self._log.warning("Ollama 不可用，拒绝开启自动润色")
                return  # 不保存，保持关闭
            c.vad.auto_polish_on_hard_cut = enabled
        elif fid == "silence_threshold":
            # RMS 静音阈值：越大越不易把底噪当人声。夹到合理区间，防误填。
            c.vad.silence_threshold = max(0.005, min(0.2, float(val)))
        elif fid == "noise_filter":
            c.vad.noise_filter = bool(val)
        elif fid in ("noise_min_voice_1char", "noise_min_voice_2char",
                     "noise_min_voice_3char"):
            # 噪音判定的"最少语音时长(秒)"：夹到 [0,5]，0=该字数不拦截。
            sec = max(0.0, min(5.0, float(val)))
            setattr(c.vad, {
                "noise_min_voice_1char": "noise_min_voice_1char_sec",
                "noise_min_voice_2char": "noise_min_voice_2char_sec",
                "noise_min_voice_3char": "noise_min_voice_3char_sec",
            }[fid], sec)
        elif fid == "force_filter":
            # UI 层传入逗号分隔字符串，保存为纯文字：忽略空格和逗号以外标点。
            import re

            from .pipeline import _force_filter_key

            phrases = []
            for raw_phrase in re.split(r"[,，]", str(val)):
                phrase = _force_filter_key(raw_phrase)
                if phrase:
                    phrases.append(phrase)
            c.asr.force_filter_phrases = phrases
        elif fid == "asr_online_base":
            c.asr.online_base_url = val
        elif fid == "asr_online_model":
            c.asr.online_model = val
        elif fid == "asr_online_key":
            if val and val != self._KEY_PLACEHOLDER:
                self.apply_api_key(val)
        elif fid == "denoise_enabled":
            enabled = bool(val)
            c.denoise.enabled = enabled
            self._clear_denoise_cache()  # 开关变化需重建引擎
        elif fid == "denoise_attenuation":
            c.denoise.attenuation = max(0.0, min(1.0, float(val)))
            self._clear_denoise_cache()  # 参数变化需以新参数重建
        elif fid == "denoise_dry_wet_mix":
            c.denoise.dry_wet_mix = max(0.0, min(1.0, float(val)))
            self._clear_denoise_cache()
        elif fid == "svr_port":
            c.asr.sensevoice_server_port = max(1024, min(65535, int(val)))

    def _default_system_prompt(self) -> str:
        """返回当前语言/后处理模式下实际生效的内置系统提示词。"""
        import copy

        from .llm import system_prompt_for

        cfg = copy.deepcopy(self.cfg)
        cfg.postprocess.prompt_template = ""
        return system_prompt_for(cfg)

    def _restore_defaults(self) -> None:
        from .config import Config as _Config
        from .config import delete_api_key

        self.cfg = _Config()
        self._asr = None
        save_config(self.cfg)
        try:
            delete_api_key()
        except Exception as exc:
            self._log.debug("恢复默认时删除 API Key 失败(忽略): %s", exc)

    def _open_system_settings(self, _s=None) -> None:
        """打开原生分类设置窗口（下拉/开关为主），见 settings_ui。"""
        try:
            from . import settings_ui

            self._warn_default_ollama_model_missing()
            settings_ui.open_settings_window(self)
        except Exception as exc:
            # 新 UI 异常：完整堆栈进日志便于定位，并直接弹错误给用户（旧文本 UI 已删除）
            self._log.exception("打开设置窗口失败")
            self._error_alert_with_log_button(
                self._t("menu_system_settings"),
                f"设置窗口打开失败：{exc}\n可点击“查看日志”打开 voiceinput.log。")
        # 保存后可能换了引擎/模型：后台预热(本地模型会下载)，避免首次说话卡住
        threading.Thread(target=self._prewarm, kwargs={"notify": True},
                         daemon=True).start()

    def _open_log(self, _s=None) -> None:
        """用系统默认文本编辑器打开日志文件 voiceinput.log。"""
        import subprocess

        from .logsetup import log_dir

        try:
            p = log_dir() / "voiceinput.log"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch(exist_ok=True)
            subprocess.run(["open", "-t", str(p)], check=False)  # -t = 默认文本编辑器
        except Exception as exc:
            self._log.warning("打开日志失败: %s", exc)

    def _clear_logs(self, _s=None) -> None:
        """清除所有日志文件（仅本应用日志，删前二次确认，不可恢复）。"""
        import rumps

        from . import logsetup

        # 二次确认（自带前台激活，避免菜单栏应用弹窗卡死）
        self._activate()
        try:
            resp = rumps.alert(
                title=self._t("menu_clear_logs"),
                message=self._t("clear_logs_confirm"),
                ok=self._t("btn_ok"), cancel=self._t("btn_cancel"),
            )
        finally:
            self._deactivate()
        if resp != 1:                       # 1=确定；0/其它=取消
            return
        try:
            removed = logsetup.clear_logs()  # 仅删 voiceinput.log[.N]/install.log[.N]
            self._log.info("已清除日志文件 %d 个: %s", len(removed), removed)
            self._alert(self._t("menu_clear_logs"),
                        self._t("clear_logs_done", n=len(removed)))
        except Exception as exc:
            self._log.exception("清除日志失败")
            self._alert(self._t("menu_clear_logs"), f"清除失败：{exc}")

    def _open_about(self, _s=None) -> None:
        """打开原生「关于」窗口。"""
        try:
            from . import settings_ui

            settings_ui.open_about_window(self)
        except Exception as exc:
            self._log.warning("打开关于窗口失败: %s", exc)
            import platform
            self._alert(f"{__app_name__} v{__version__}",
                        self._t("about_body", arch=platform.machine()))

    def _open_settings(self, _sender) -> None:
        from .config import config_path

        cont = self._t("on_label") if self.cfg.general.continuous_dictation else self._t("off_label")
        self._alert(
            self._t("cfg_title"),
            self._t(
                "cfg_field",
                path=config_path(),
                lang=self.cfg.general.language,
                cont=cont,
                pause=self.cfg.vad.silence_sec,
                ppmode=self.cfg.postprocess.mode,
                llm=self.cfg.llm.mode,
                ollama=self.cfg.llm.ollama.model,
                whisper=self.cfg.asr.whisper_model,
            ),
        )

    def _about(self, _sender) -> None:
        import platform

        self._alert(f"{__app_name__} v{__version__}",
                    self._t("about_body", arch=platform.machine()))

    def _quit(self, _sender) -> None:
        import rumps

        if self._listener is not None:
            self._listener.stop()
        rumps.quit_application()

    def _open_privacy_settings(self) -> None:
        """打开 macOS 隐私与安全性设置（输入监控）面板 (FR-13)。"""
        import subprocess

        try:
            subprocess.run([
                "open",
                "x-apple.systempreferences:com.apple.preference.security"
                "?Privacy_ListenEvent",
            ], check=False)
        except Exception as exc:
            self._log.warning("打开系统设置失败: %s", exc)

    def _prewarm(self, notify: bool = False) -> None:
        """后台预热 ASR 模型（本地模型首次会下载，可能较久）。"""
        try:
            asr = self._get_asr()
            if not hasattr(asr, "_ensure_model"):
                return  # 在线引擎(dashscope/online)无需预热
            self._log.info("正在准备 ASR 模型(本地模型首次需下载，请稍候)…")
            if notify:
                self._notify("正在准备语音模型", "首次切换本地模型需下载，完成前请稍候…")
            asr._ensure_model()
            self._log.info("ASR 模型已就绪，识别将更快")
            if notify:
                self._notify("语音模型就绪", "现在可以开始听写了。")
        except Exception as exc:
            self._log.warning("ASR 预热失败（首次识别可能稍慢/需下载）: %s", exc)

    def _notify(self, title: str, msg: str) -> None:
        try:
            import rumps

            rumps.notification(title=__app_name__, subtitle=title, message=msg)
        except Exception:
            pass

    def run(self) -> None:
        from .logsetup import setup_logging

        self._log = setup_logging()
        self._log.info("VoiceInput 启动 v%s", __version__)
        # 自检：确认本进程加载的设置控制器已注册 noiseHistory_（拦截历史按钮依赖它）。
        # 日志若显示 False，说明跑的是旧代码/旧字节码——是定位“点按钮报 selector”根因的铁证。
        try:
            from . import settings_ui

            _c = settings_ui._get_controller_class().alloc().init()
            self._log.info(
                "自检 设置控制器: noiseHistory_=%s categoryClicked_=%s | settings_ui=%s",
                bool(_c.respondsToSelector_("noiseHistory:")),
                bool(_c.respondsToSelector_("categoryClicked:")),
                settings_ui.__file__,
            )
        except Exception:
            self._log.exception("自检设置控制器失败")
        app = self.build()
        # 后台预热 ASR 模型（首次说话不再等模型加载）
        threading.Thread(target=self._prewarm, daemon=True).start()
        # 启动全局热键监听
        from .hotkey import IMPLEMENTED_TRIGGERS

        trigger = self.cfg.hotkey.trigger
        if trigger not in IMPLEMENTED_TRIGGERS:
            self._log.warning(
                "热键触发方式 %r 暂未实现，回退为双击 Command（可选 %s）",
                trigger, "/".join(IMPLEMENTED_TRIGGERS))
            trigger = "double_command"
        self._listener = GlobalHotkeyListener(
            on_double_tap=self._on_double_tap,
            double_tap_ms=self.cfg.hotkey.double_tap_ms,
            trigger=trigger,
            custom_hotkey=self.cfg.hotkey.custom_hotkey,
        )
        try:
            self._listener.start()
        except Exception as exc:
            # 无权限时降级：菜单"开始/停止 录音"仍可手动触发，并引导授权 (FR-13)
            self._log.warning("全局热键监听启动失败(可能缺少输入监控权限): %s", exc)
            try:
                import rumps

                rumps.notification(
                    title=__app_name__,
                    subtitle="双击⌘热键不可用",
                    message="请在 系统设置→隐私与安全性→输入监控 授权；可先用菜单手动录音。",
                )
                self._open_privacy_settings()
            except Exception:
                pass
        app.run()


def main() -> None:
    VoiceInputApp().run()
