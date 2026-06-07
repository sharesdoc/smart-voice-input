# VoiceInput —— macOS AI 智能语音输入

常驻菜单栏的 AI 语音输入工具：**双击 Command 键**说话，语音被本地 Whisper 识别为文字，再由大模型（本地 Ollama 或在线 OpenAI 兼容接口）做**意图识别与智能整理**，自动注入到当前光标处。支持**讯飞式动态重写**：先即时显示原始文本，整理完成后自动删除并替换为通顺的书面句。

> 完整需求见 [`A-系统需求文档.md`](./A-系统需求文档.md)，设计见 [`B-系统设计文档.md`](./B-系统设计文档.md)。

## 特性

- 🎙️ **全局语音输入**：任意 App 输入框，双击 ⌘ 触发
- 🧠 **AI 智能整理**：纠错、加标点、删冗余、语序重组（FR-16）
- ♻️ **动态重写**：删除已注入的不通顺文本，替换为整理版（讯飞式）
- 🔒 **删除安全边界**：只删本程序注入的字符，绝不误删用户原有文字（FR-17）
- 🏠 **本地优先**：本地 Whisper + 本地 Ollama，全程可离线
- ☁️ **在线可选**：可配置 OpenAI 兼容 Base URL / API Key / 模型
- 🖥️ **双架构**：代码兼容 Apple Silicon (arm64) 与 Intel (x86_64)

## 快速开始

```bash
# 1) 安装全部依赖（含 5 个 ASR 引擎；conda base 环境）
./install -i

# 2) 校验（py_compile + 单元测试，无需 GUI/麦克风）
./install -b

# 3) 启动菜单栏应用（nohup 后台）
./install -s            # 停止 ./install -k；重启 ./install -r
```

首次启动需在「系统设置 → 隐私与安全性」授予：
- **麦克风**（录音）
- **辅助功能** 与 **输入监控**（全局热键 + 模拟键盘注入）

## 使用

1. 启动后菜单栏出现 🎙️ 图标。
2. 在任意输入框中**双击 Command 键**进入连续听写。
3. 说话，停顿约 1 秒自动成段并输入；继续说继续输入；再次**双击 Command** 退出听写。
4. 点击图标 →「**系统配置…**」打开统一设置页（语言/ASR引擎/后处理/大模型等，含保存/恢复默认）。

## 配置

全部设置集中在菜单「**系统配置…**」一个对话框里（分门别类 + 保存/取消/恢复默认）。
配置文件：`~/Library/Application Support/VoiceInput/config.json`；API Key 存于 **macOS 钥匙串**，不写入配置文件。

| 项 | 默认 | 说明 |
|----|------|------|
| 语音识别引擎 | 本地 Whisper | 本地Whisper / 本地MLX Whisper / 本地SenseVoice / 阿里云Fun-ASR / 在线OpenAI |
| 后处理模式 | polish | 纯转写 / 智能纠错润色 / 智能整理 / 翻译 |
| 重写方式 | rewrite_once | 整理后注入 / 即时预览重写 |
| 大模型引擎 | ollama | 本地 Ollama / 在线 / 关闭 |
| Ollama 模型 | qwen2.5:7b-instruct-q4_K_M | 未安装时执行 `ollama pull qwen2.5:7b-instruct-q4_K_M; ollama list` |
| 加工参数 | 低温度/关闭思考 | 默认少改写原话、限制输出长度、清理 thinking 内容 |
| 停顿秒数 | 1.0 | 静音多久算一句说完 |
| 语言 | 中文 | 中文 / 英文（界面 + 识别同时切换） |

## 架构

```
双击⌘(hotkey) → 录音(audio) → Whisper(asr) → 原始文本
   → LLM整理(llm: ollama/online) → 注入/动态重写(pipeline + injector + session 安全计数)
   状态贯穿 state → 菜单栏(app)
```

纯逻辑模块（config/state/session/pipeline/llm/hotkey 判定）零 macOS 依赖、可单测；
GUI/音频/ASR/注入为懒加载的薄封装。

## 测试

```bash
./install -b                                   # 校验 + 单元测试
~/ins/miniconda/bin/python -m pytest tests/ --cov=voiceinput   # 覆盖率报告
```

核心安全逻辑（会话计数、动态重写、双击检测、降级）由 138 单测覆盖。
