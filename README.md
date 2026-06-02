# VoiceInput

VoiceInput is an AI-powered voice input tool for macOS. It runs as a menu bar app, records audio through a global hotkey, transcribes speech into text, optionally uses a local or online LLM to fix, polish, organize, or translate the text, and then inserts the final result into the currently focused text field.

The project currently supports running from Python source in the background. It also includes a `py2app` configuration for building a menu bar `.app` without a Dock icon.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

## Features

- Menu bar app: shows a microphone icon in the macOS menu bar after startup.
- Hotkey trigger: double-tap `Command` by default to start or stop dictation; custom hotkey combinations are also supported.
- Continuous dictation: enabled by default. Trigger once to keep listening, automatically segment speech after a pause, and trigger again to stop.
- Silence-based segmentation: uses VAD to detect pauses; the default pause threshold is about `1.0` second.
- Multiple ASR engines:
  - Local `faster-whisper`
  - `MLX Whisper` for Apple Silicon
  - Local `SenseVoice-Small`
  - Aliyun DashScope Fun-ASR
  - OpenAI-compatible online ASR
- LLM post-processing:
  - `raw`: direct transcription without LLM
  - `polish`: fix typos and punctuation while preserving the original wording as much as possible
  - `organize`: clean up fillers and reorganize longer text
  - `translate`: translate the transcribed text
- LLM backends:
  - Local Ollama
  - OpenAI-compatible online API
  - Disabled
- Text injection: uses clipboard plus `Command + V` by default, then restores the previous clipboard content; direct keystroke injection is also supported.
- System settings window: configure language, ASR engine, model, pause duration, post-processing mode, LLM backend, API keys, launch at login, and more.
- Logs and diagnostics: records ASR, LLM, injection, and end-to-end timing to help debug latency or failures.

## Requirements

- macOS
- Python 3.10+. The install script uses this Python by default:

```bash
~/ins/miniconda/bin/python
```

- A microphone
- Network access for the first local model download
- Ollama, if you want local LLM post-processing

> Note: this project depends on macOS-specific capabilities such as PyObjC, Quartz, sounddevice, and pynput. On non-macOS systems, only part of the pure logic test suite can run; the desktop voice input app will not work normally.

## Installation

Enter the project directory:

```bash
cd $HOME/wks/ai/tools/voice-input.github
```

Install dependencies and initialize the app configuration:

```bash
./install -i
```

The install script will:

- install dependencies from `requirements.txt`
- initialize the app configuration
- pre-download or preload the local speech model for the current ASR configuration
- try to pull the default Ollama model if Ollama is configured

If your Python interpreter is not located at `~/ins/miniconda/bin/python`, update `PYTHON_BIN` in the `install` script or `.install.cfg`.

## Start And Stop

Start the app:

```bash
./install -s
```

After startup, a microphone icon should appear in the macOS menu bar.

Stop the app:

```bash
./install -k
```

Restart:

```bash
./install -r
```

Check status:

```bash
./install -v
```

View logs:

```bash
./install -l
```

You can also run it directly from source:

```bash
~/ins/miniconda/bin/python -m voiceinput
```

## macOS Permissions

After the first launch, grant the required permissions in "System Settings -> Privacy & Security":

- Microphone: required for audio recording.
- Accessibility: required to inject text into the active app.
- Input Monitoring: required to listen for the global hotkey.

After granting permissions, restart VoiceInput:

```bash
./install -r
```

If the hotkey does not work, the usual cause is that Input Monitoring or Accessibility permission has not been granted to the current Python interpreter, terminal app, IDE, or packaged app.

## Usage

1. Start VoiceInput.
2. Place the cursor in any editable text field, such as an editor, browser, or chat window.
3. Double-tap `Command` to enter dictation mode.
4. Start speaking.
5. After the configured pause duration, VoiceInput transcribes the speech segment and inserts the text at the cursor.
6. Double-tap `Command` again to stop continuous dictation.

You can also click "Start/Stop Dictation" from the menu bar menu.

## Configuration

Click the menu bar icon and open "System Settings".

Common settings:

- Language: `Chinese` or `English`.
- Speech recognition engine:
  - `Local Whisper (faster-whisper)`: general local ASR option.
  - `Local MLX Whisper (Apple)`: recommended only for Apple Silicon Macs.
  - `Local SenseVoice-Small`: fast Chinese ASR with punctuation.
  - `Aliyun Fun-ASR`: online ASR that requires a DashScope API key.
  - `Online OpenAI`: OpenAI-compatible `/audio/transcriptions` endpoint.
- Continuous dictation: when enabled, one trigger keeps listening; when disabled, dictation becomes a start/stop toggle.
- Pause seconds: controls how long silence must last before a segment is considered complete. Supported formats include `0.8`, `800ms`, and `1s`.
- Post-processing mode: raw transcription, polish, organize, or translate.
- LLM engine: local Ollama, online, or disabled.
- Launch at login: enable or disable the LaunchAgent.

Configuration file:

```text
~/Library/Application Support/VoiceInput/config.json
```

Log file:

```text
~/Library/Logs/VoiceInput/voiceinput.log
```

## API Keys

Online LLM and OpenAI-compatible online ASR share the same online API key. The app reads this environment variable first:

```bash
export VOICEINPUT_ONLINE_API_KEY="your API key"
```

You can also enter the key in the system settings window. The app will try to store it in the macOS Keychain.

DashScope Fun-ASR supports two key sources:

- Environment variable:

```bash
export DASHSCOPE_API_KEY="your DashScope API key"
```

- Manual entry in the system settings window, stored in the Keychain.

## Ollama Post-Processing

The default LLM mode is local Ollama. The default model is:

```text
qwen2.5:7b-instruct
```

Install Ollama and make sure the service is reachable:

```bash
ollama pull qwen2.5:7b-instruct
ollama serve
```

If you do not need LLM polishing, set the post-processing mode to `raw` or set the LLM engine to `off` in the system settings.

## Build A macOS App

The project includes `setup.py` and can be packaged with `py2app`:

```bash
~/ins/miniconda/bin/python -m pip install py2app
~/ins/miniconda/bin/python setup.py py2app
```

The output app is:

```text
dist/VoiceInput.app
```

Local speech models are not bundled into the app. They are downloaded into the user's cache directory at runtime.

## Development And Testing

Run syntax checks and unit tests:

```bash
./install -b
```

Run pytest directly:

```bash
~/ins/miniconda/bin/python -m pytest tests/ -q
```

Run the ASR benchmark:

```bash
./install -t asr
```

Benchmark with a specific WAV file:

```bash
./install -t asr /path/to/audio.wav
```

## Notes

- This is a macOS desktop app, not a web service. It does not listen on any port. The `-p/--port` option in the `install` script is kept only for compatibility and has no effect.
- Local model downloads can be large. `faster-whisper`, `SenseVoice`, `MLX Whisper`, `torch`, and related dependencies may also use significant disk space.
- `MLX Whisper` is only suitable for Apple Silicon Macs. On Intel Macs, use `faster-whisper`, `SenseVoice`, or an online ASR engine.
- The default injection method briefly writes to the clipboard and then restores the previous clipboard content. This is the most compatible option for most apps, but apps with unusual paste behavior may need direct keystroke injection.
- If LLM post-processing fails, the app falls back to the raw ASR text instead of blocking input.
- `organize` mode rewrites more actively and is better for longer text. Use `polish` or `raw` if you need to preserve the original wording strictly.
- If continuous dictation is stopped while a segment is being processed, the current segment will be canceled before injection, and queued unprocessed segments will be discarded.
- The permission target may be Python, Terminal, your IDE, or `VoiceInput.app`, depending on how you start the app.

## FAQ

### The menu bar icon does not appear

Check status and logs:

```bash
./install -v
./install -l
```

If dependencies are missing, run:

```bash
./install -i
```

### Double-tapping Command does nothing

Check Input Monitoring and Accessibility permissions, then restart:

```bash
./install -r
```

### Speech is recognized but text is not inserted

This is usually caused by missing Accessibility permission, or by the target input field rejecting simulated paste events. Confirm macOS permissions first, then try another target app.

### Local LLM polishing fails

Make sure Ollama is running and the configured model has been pulled:

```bash
ollama list
ollama pull qwen2.5:7b-instruct
```

You can also disable LLM temporarily and use raw transcription.

### Online models do not work

Check the API key, Base URL, and model name. Online LLM uses an OpenAI-compatible `/chat/completions` endpoint, and online ASR uses an OpenAI-compatible `/audio/transcriptions` endpoint.

