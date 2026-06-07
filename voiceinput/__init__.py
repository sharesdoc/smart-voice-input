"""VoiceInput —— macOS AI 智能语音输入程序。

模块划分（对应 A-系统需求文档）：
- config:   配置加载/保存 + 钥匙串 (FR-11/FR-12)
- state:    应用状态机 (FR-01, §7)
- pipeline: 识别→整理→一次性注入流程编排
- llm:      LLM 后处理 (Ollama / OpenAI 兼容) (FR-07/08/09)
- hotkey:   双击 Command 检测 (FR-03)
- asr:      本地 Whisper 语音识别封装 (FR-05)
- audio:    麦克风录音封装 (FR-03/04)
- injector: 文本注入 / 回删 (FR-10)
- app:      菜单栏应用与 UI 装配 (FR-01/02, §7)

设计原则：纯逻辑模块（config/state/pipeline/llm/hotkey 的判定部分）
不依赖 macOS 专用库，可在任意环境单元测试；GUI/音频/ASR 等重型依赖采用懒加载。
"""

import os as _os

# Intel(x86_64) mac 上 torch / ctranslate2 / numba(llvmlite) 各自静态链接了一份
# OpenMP 运行时(libiomp5 / libomp)，同进程加载多份会触发
#   "OMP: Error #15: Initializing libiomp5.dylib, but found ... already initialized"
# 并以 Abort trap: 6 直接杀进程（首次出现在懒加载 ASR 模型的 _prewarm 线程）。
# 必须在任何重型库导入前设置此环境变量，故放在包初始化最前；setdefault 允许外部覆盖。
_os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

__version__ = "0.1.0"
__app_name__ = "VoiceInput"
