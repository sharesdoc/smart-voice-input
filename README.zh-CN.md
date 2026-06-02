# VoiceInput

VoiceInput 是一个面向 macOS 的 AI 智能语音输入工具。它常驻在菜单栏，通过快捷键录音，把语音识别成文字，并可调用本地或在线大模型做纠错、润色、整理或翻译，最后把结果输入到当前光标所在的文本框。

项目当前以 Python 源码后台运行，也提供 `py2app` 打包配置，可打包成无 Dock 图标的菜单栏 `.app`。

## 主要功能

- 菜单栏常驻：启动后在 macOS 菜单栏显示麦克风图标。
- 快捷键触发：默认双击 `Command` 开始或停止听写；也支持配置自定义组合键。
- 连续听写：默认开启。触发一次后持续监听，检测到停顿后自动切成一段并输入，再次触发快捷键停止。
- 静音断句：基于 VAD 检测停顿，默认停顿约 `1.0` 秒判定一句结束。
- 多 ASR 引擎：
  - 本地 `faster-whisper`
  - Apple Silicon 可用的 `MLX Whisper`
  - 本地 `SenseVoice-Small`
  - 阿里云 DashScope Fun-ASR
  - OpenAI 兼容在线 ASR
- 大模型后处理：
  - `raw`：纯转写，不调用 LLM
  - `polish`：纠错、补标点，尽量保持原话
  - `organize`：整理语序、去口头禅
  - `translate`：翻译
- LLM 后端：
  - 本地 Ollama
  - OpenAI 兼容在线接口
  - 关闭 LLM
- 文本注入：默认使用剪贴板加 `Command + V` 粘贴，并在注入后恢复原剪贴板；也支持直接键入模式。
- 系统配置窗口：可在菜单栏里调整语言、ASR 引擎、模型、停顿时间、后处理模式、LLM、API Key、开机自启等。
- 日志与诊断：记录 ASR、LLM、注入和端到端耗时，便于排查延迟或失败。

## 运行环境

- macOS
- Python 3.10+，项目安装脚本默认使用：

```bash
~/ins/miniconda/bin/python
```

- 麦克风
- 首次使用本地模型时需要联网下载模型
- 如使用本地 LLM 后处理，需要安装并启动 Ollama

> 注意：项目依赖 PyObjC、Quartz、sounddevice、pynput 等 macOS 能力，非 macOS 环境只能运行部分纯逻辑测试，无法正常作为桌面语音输入工具使用。

## 安装

进入项目目录：

```bash
cd $HOME/wks/ai/tools/voice-input.github
```

安装依赖并初始化配置：

```bash
./install -i
```

安装脚本会执行：

- 安装 `requirements.txt` 中的依赖
- 初始化应用配置
- 按当前 ASR 配置预下载或预加载本地语音模型
- 如果配置为 Ollama，会尝试拉取默认模型

如果你的 Python 不在 `~/ins/miniconda/bin/python`，需要先修改 `install` 脚本或 `.install.cfg` 里的 `PYTHON_BIN`。

## 启动与停止

启动：

```bash
./install -s
```

启动成功后，菜单栏会出现麦克风图标。

停止：

```bash
./install -k
```

重启：

```bash
./install -r
```

查看状态：

```bash
./install -v
```

查看日志：

```bash
./install -l
```

也可以直接从源码运行：

```bash
~/ins/miniconda/bin/python -m voiceinput
```

## macOS 权限

首次启动后，需要在「系统设置 → 隐私与安全性」里授予相关权限：

- 麦克风：用于录音。
- 辅助功能：用于向当前应用注入文字。
- 输入监控：用于监听全局快捷键。

授权后建议重启 VoiceInput：

```bash
./install -r
```

如果热键无效，通常是「输入监控」或「辅助功能」权限没有授予给当前 Python 解释器、终端或打包后的 App。

## 使用方法

1. 启动 VoiceInput。
2. 把光标放到任意可输入文本的位置，比如编辑器、浏览器、聊天窗口。
3. 双击 `Command` 进入听写。
4. 开始说话。
5. 停顿达到设置时长后，程序会自动识别这一段语音，并把文字输入到当前光标位置。
6. 再次双击 `Command` 停止连续听写。

也可以点击菜单栏里的「开始/停止听写」手动触发。

## 常用配置

点击菜单栏图标，打开「系统配置」。

常见设置项：

- 语言：`中文` 或 `英文`。
- 语音识别引擎：
  - `本地Whisper(faster-whisper)`：通用本地方案。
  - `本地MLX Whisper(Apple加速)`：仅 Apple Silicon Mac 推荐。
  - `本地SenseVoice-Small`：中文速度快，自带标点。
  - `阿里云Fun-ASR`：在线识别，需要 DashScope API Key。
  - `在线OpenAI`：OpenAI 兼容 `/audio/transcriptions` 接口。
- 连续听写：开启后一次触发持续监听；关闭后变为按一次开始、再按一次结束的切换式录音。
- 停顿秒数：控制静音多久算一句说完，支持 `0.8`、`800ms`、`1s` 等格式。
- 后处理模式：纯转写、智能纠错润色、智能整理、翻译。
- 大模型引擎：本地 Ollama、在线、关闭。
- 开机自启：启用或关闭 LaunchAgent。

配置文件位置：

```text
~/Library/Application Support/VoiceInput/config.json
```

日志文件位置：

```text
~/Library/Logs/VoiceInput/voiceinput.log
```

## API Key 配置

在线 LLM 和在线 OpenAI ASR 使用同一套在线 API Key。程序优先从环境变量读取：

```bash
export VOICEINPUT_ONLINE_API_KEY="你的 API Key"
```

也可以在系统配置窗口中填写，程序会尝试保存到 macOS 钥匙串。

DashScope Fun-ASR 支持两种 Key 来源：

- 环境变量：

```bash
export DASHSCOPE_API_KEY="你的 DashScope API Key"
```

- 系统配置窗口手动输入，保存到钥匙串。

## Ollama 后处理

默认 LLM 模式是本地 Ollama，默认模型为：

```text
qwen2.5:7b-instruct
```

需要先安装 Ollama，并确保服务可访问：

```bash
ollama pull qwen2.5:7b-instruct
ollama serve
```

如果不需要 LLM 润色，可以在系统配置里把后处理模式改为「纯转写」，或把大模型引擎改为「关闭」。

## 打包成 macOS App

项目包含 `setup.py`，可用 `py2app` 打包：

```bash
~/ins/miniconda/bin/python -m pip install py2app
~/ins/miniconda/bin/python setup.py py2app
```

产物在：

```text
dist/VoiceInput.app
```

本地语音模型不会打进 App 包里，运行时会下载到用户缓存目录。

## 开发与测试

语法校验和单元测试：

```bash
./install -b
```

直接运行 pytest：

```bash
~/ins/miniconda/bin/python -m pytest tests/ -q
```

ASR 引擎基准测试：

```bash
./install -t asr
```

指定 WAV 文件测试：

```bash
./install -t asr /path/to/audio.wav
```

## 注意事项

- 这是 macOS 桌面应用，不是 Web 服务，没有监听端口。`install` 脚本里的 `-p/--port` 只是兼容保留参数，不会生效。
- 本地模型首次下载体积较大，`faster-whisper`、`SenseVoice`、`MLX Whisper`、`torch` 等依赖也可能占用较多磁盘空间。
- `MLX Whisper` 只适合 Apple Silicon Mac；Intel Mac 请使用 `faster-whisper`、`SenseVoice` 或在线 ASR。
- 默认注入方式会短暂写入剪贴板，再恢复旧剪贴板。大多数应用兼容性最好，但如果目标应用粘贴行为特殊，可能需要改用直接键入模式。
- LLM 后处理失败时，程序会降级输入 ASR 原文，不会因为模型或网络失败阻断输入。
- `organize` 模式会更主动地重组语句，适合长段整理；如果要求严格保留原话，建议使用 `polish` 或 `raw`。
- 如果连续听写中再次触发停止，当前正在处理的一段会被取消注入，队列中未处理的语音段会被丢弃。
- 权限授予对象可能是 Python、终端、IDE 或打包后的 `VoiceInput.app`，取决于你用哪种方式启动。

## 常见问题

### 菜单栏没有图标

先查看状态和日志：

```bash
./install -v
./install -l
```

如果提示依赖缺失，执行：

```bash
./install -i
```

### 双击 Command 没反应

检查「输入监控」和「辅助功能」权限，授权后重启：

```bash
./install -r
```

### 能识别但不能输入文字

通常是「辅助功能」权限不足，或当前输入框不接受模拟粘贴。可先在系统设置中确认权限，再尝试切换输入目标应用。

### 本地 LLM 润色失败

确认 Ollama 正在运行，并已拉取配置中的模型：

```bash
ollama list
ollama pull qwen2.5:7b-instruct
```

也可以临时关闭 LLM，使用纯转写。

### 在线模型不可用

检查 API Key、Base URL 和模型名是否正确。在线 LLM 使用 OpenAI 兼容的 `/chat/completions` 接口，在线 ASR 使用 OpenAI 兼容的 `/audio/transcriptions` 接口。

