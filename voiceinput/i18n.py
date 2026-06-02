"""界面文案本地化 (UI i18n)：中文 / 英文。

tr(lang, key, **fmt) 返回对应语言文案；缺失回退中文，再回退 key。
界面语言跟随 general.language 选择。
"""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # 状态
    "status_prefix":   {"zh": "状态：",   "en": "Status: "},
    "state_IDLE":      {"zh": "空闲",     "en": "Idle"},
    "state_LISTENING": {"zh": "聆听中",   "en": "Listening"},
    "state_TRANSCRIBING": {"zh": "识别中", "en": "Transcribing"},
    "state_REFINING":  {"zh": "整理中",   "en": "Refining"},
    "state_REWRITING": {"zh": "重写中",   "en": "Rewriting"},
    "state_INJECTING": {"zh": "注入中",   "en": "Injecting"},
    "state_ERROR":     {"zh": "错误",     "en": "Error"},
    # 菜单
    "menu_record":  {"zh": "开始/停止 听写（或双击⌘）",
                     "en": "Start/Stop Dictation (or double-⌘)"},
    "menu_language": {"zh": "语言 / Language", "en": "Language / 语言"},
    "lang_zh": {"zh": "中文", "en": "Chinese"},
    "lang_en": {"zh": "英文", "en": "English"},
    "menu_postprocess": {"zh": "后处理模式", "en": "Post-processing"},
    "mode_raw":      {"zh": "纯转写",           "en": "Raw transcription"},
    "mode_polish":   {"zh": "智能纠错润色",     "en": "Polish (fix & punctuate)"},
    "mode_organize": {"zh": "智能整理(动态重写)", "en": "Organize (rewrite)"},
    "mode_translate": {"zh": "翻译模式",        "en": "Translate"},
    "menu_llm_engine": {"zh": "LLM 引擎", "en": "LLM Engine"},
    "llm_ollama": {"zh": "本地 Ollama", "en": "Local Ollama"},
    "llm_online": {"zh": "在线模型",    "en": "Online"},
    "llm_off":    {"zh": "关闭后处理",  "en": "Off"},
    "menu_ollama_model": {"zh": "Ollama 模型", "en": "Ollama Model"},
    "ollama_none": {"zh": "（未检测到，请确认 Ollama 运行）",
                    "en": "(none detected; is Ollama running?)"},
    "menu_asr_engine": {"zh": "ASR 引擎", "en": "ASR Engine"},
    "asr_local":  {"zh": "本地 Whisper", "en": "Local Whisper"},
    "asr_sensevoice": {"zh": "本地 SenseVoice-Small（极快·自带标点）",
                       "en": "Local SenseVoice-Small (fast)"},
    "asr_dashscope": {"zh": "在线ASR（阿里云Fun-ASR语音识别）",
                      "en": "Online ASR (Aliyun Fun-ASR)"},
    "asr_online": {"zh": "在线 ASR（OpenAI 兼容）", "en": "Online ASR (OpenAI-compat)"},
    "menu_whisper_model": {"zh": "Whisper 模型", "en": "Whisper Model"},
    "menu_continuous": {"zh": "连续听写（说完自动分段输入）",
                        "en": "Continuous dictation (auto-segment)"},
    "menu_pause": {"zh": "停顿检测时长", "en": "Pause threshold"},
    "pause_fastest": {"zh": "0.3 秒（最快，易切断）", "en": "0.3 s (fastest)"},
    "pause_05": {"zh": "0.5 秒", "en": "0.5 s"},
    "pause_08": {"zh": "0.8 秒", "en": "0.8 s"},
    "pause_default": {"zh": "1.0 秒（默认）", "en": "1.0 s (default)"},
    "pause_15": {"zh": "1.5 秒", "en": "1.5 s"},
    "pause_complete": {"zh": "2.0 秒（更完整，慢）", "en": "2.0 s (more complete)"},
    "pause_custom": {"zh": "自定义…（秒或毫秒）", "en": "Custom… (s or ms)"},
    "menu_online_settings": {"zh": "在线模型设置…", "en": "Online Model Settings…"},
    "online_test": {"zh": "测试连接",       "en": "Test Connection"},
    "online_form_msg": {
        "zh": ("编辑下方各行后点【保存】；可点【测试连接】先验证。\n"
               "api_key 留空则保持不变。"),
        "en": ("Edit the lines below, then Save. Click Test to verify first.\n"
               "Leave api_key blank to keep the current key."),
    },
    "online_saved": {"zh": "已保存。", "en": "Saved."},
    "menu_autostart": {"zh": "开机自启", "en": "Launch at Login"},
    "menu_viewcfg": {"zh": "查看配置…", "en": "View Config…"},
    "menu_about":   {"zh": "关于",      "en": "About"},
    "menu_logs":    {"zh": "查看日志",  "en": "View Logs"},
    "menu_quit":    {"zh": "退出",      "en": "Quit"},
    "menu_system_settings": {"zh": "系统配置", "en": "System Settings…"},
    "settings_msg": {
        "zh": ("编辑下面各项后点【保存】；【恢复默认】会清空全部设置回到初始状态。\n"
               "以 # 开头的行是说明/关于信息，不用改。"),
        "en": ("Edit below, then Save. Restore Defaults resets everything.\n"
               "Lines starting with # are notes/about info; leave them."),
    },
    "settings_saved": {"zh": "已保存。部分项下次进入听写生效。", "en": "Saved."},
    "settings_restored": {"zh": "已恢复默认设置。", "en": "Restored to defaults."},
    "btn_restore": {"zh": "恢复默认", "en": "Restore Defaults"},
    "about_label": {"zh": "关于", "en": "About"},
    "about_asr": {"zh": "当前语音识别", "en": "Current ASR"},
    "about_llm": {"zh": "当前大模型", "en": "Current LLM"},
    # 对话框/提示
    "about_body": {
        "zh": "macOS AI 智能语音输入\n架构：{arch}\n双击 Command 键开始/结束语音输入。",
        "en": "macOS AI Voice Input\nArch: {arch}\nDouble-tap Command to start/stop.",
    },
    "cfg_title": {"zh": "当前配置", "en": "Current Config"},
    "conn_title": {"zh": "连接测试", "en": "Connection Test"},
    "pause_title": {"zh": "停顿检测", "en": "Pause Threshold"},
    "pause_prompt": {
        "zh": "静音超过此时长即判定说完并输入。可填秒或毫秒，如 0.8 或 800ms：",
        "en": "Insert after silence exceeds this. Enter seconds or ms, e.g. 0.8 or 800ms:",
    },
    "pause_set": {"zh": "已设为 {sec} 秒。下次进入听写生效。",
                  "en": "Set to {sec} s. Takes effect on next dictation."},
    "pause_bad": {"zh": "无法识别的数值，请填如 0.8 或 800ms。",
                  "en": "Unrecognized value. Try e.g. 0.8 or 800ms."},
    "btn_save": {"zh": "保存", "en": "Save"},
    "btn_cancel": {"zh": "取消", "en": "Cancel"},
    "online_base_title": {"zh": "在线模型 Base URL", "en": "Online Base URL"},
    "online_base_msg": {"zh": "OpenAI 兼容接口地址：",
                        "en": "OpenAI-compatible endpoint URL:"},
    "online_model_title": {"zh": "在线模型名", "en": "Online Model Name"},
    "online_model_msg": {"zh": "如 gpt-4o-mini / deepseek-chat：",
                         "en": "e.g. gpt-4o-mini / deepseek-chat:"},
    "apikey_title": {"zh": "在线 API Key", "en": "Online API Key"},
    "apikey_msg": {"zh": "将存入 macOS 钥匙串（不写入配置文件）：",
                   "en": "Stored in macOS Keychain (not in config file):"},
    "apikey_ok": {"zh": "已存入钥匙串。", "en": "Saved to Keychain."},
    "apikey_fail": {"zh": "保存失败：keyring 不可用。",
                    "en": "Failed: keyring unavailable."},
    "cfg_field": {  # 查看配置 字段标签
        "zh": ("配置文件：{path}\n语言：{lang}\n连续听写：{cont}\n停顿检测时长：{pause} 秒\n"
               "后处理模式：{ppmode}\nLLM 引擎：{llm}\nOllama 模型：{ollama}\n"
               "Whisper 模型：{whisper}"),
        "en": ("Config file: {path}\nLanguage: {lang}\nContinuous: {cont}\n"
               "Pause threshold: {pause} s\nPost-processing: {ppmode}\nLLM engine: {llm}\n"
               "Ollama model: {ollama}\nWhisper model: {whisper}"),
    },
    "on_label": {"zh": "开", "en": "On"},
    "off_label": {"zh": "关", "en": "Off"},
    "conn_ollama_ok": {"zh": "Ollama 连接正常，{n} 个模型可用。",
                       "en": "Ollama OK — {n} models available."},
    "conn_ollama_fail": {"zh": "未连接到 Ollama，请确认其已运行。",
                         "en": "Cannot reach Ollama — is it running?"},
    "conn_online_ok": {"zh": "在线模型连接正常。", "en": "Online model OK."},
    "conn_fail": {"zh": "连接失败：{err}", "en": "Connection failed: {err}"},
    "autostart_fail": {"zh": "操作失败，请检查权限。",
                       "en": "Operation failed; check permissions."},
}


def tr(language_code: str, string_key: str, **fmt) -> str:
    # 参数名故意取 language_code/string_key，避免与 **fmt 里的占位符(如 lang/key)撞名
    entry = STRINGS.get(string_key)
    if entry is None:
        return string_key
    text = entry.get(language_code) or entry.get("zh") or string_key
    if fmt:
        try:
            text = text.format(**fmt)
        except Exception:
            pass
    return text
