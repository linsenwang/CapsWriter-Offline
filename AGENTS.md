# CapsWriter-Offline 项目指南（AI 维护版）

> 版本: v2.5-alpha | 更新日期: 2026-04-28
> 本文档面向 AI 编码助手，介绍项目架构、开发规范和维护要点。

---

## 一、项目概述

**CapsWriter-Offline** 是一个专为 Windows / macOS 设计的**完全离线**语音输入工具（C/S 架构）。

核心特性：
- **完全离线**：所有 ASR 模型、标点模型、LLM 均本地运行，无需联网
- **C/S 分离**：服务端运行重型 AI 模型，客户端负责录音、快捷键、上屏
- **多模型支持**：支持 Paraformer、SenseVoice、Fun-ASR-Nano、Qwen3-ASR 等多种 ASR 模型
- **LLM 角色系统**：支持润色、翻译、写作等自定义角色（通过前缀触发）
- **热词系统**：基于音素（Phoneme）的 RAG 模糊匹配，支持中英文统一热词
- **高度可配置**：所有用户配置集中在根目录的 `config_*.py` 和 `hot*.txt` 中

平台支持：
- **Windows 10/11**：完全支持（托盘、窗口管理、事件抑制、DirectML/Vulkan 加速）
- **macOS**：基本功能可用（需授予辅助功能权限），暂不支持单事件抑制（`suppress` 对切换键无效）
- **Linux**：未测试，不保证兼容性

---

## 二、技术栈

| 层级 | 技术/库 |
|------|---------|
| 语言 | Python 3.8+（客户端 Win7 兼容需 3.8） |
| ASR 引擎 | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)（ONNX Runtime） |
| GGUF 解码 | [llama.cpp](https://github.com/ggerganov/llama.cpp)（通过 Python 绑定） |
| 通信协议 | WebSocket（`websockets` 库），子协议 `binary` |
| 音频采集 | `sounddevice`（PortAudio） |
| 快捷键 | `pynput`（跨平台）+ `keyboard`（Windows 仅作辅助） |
| 输出模拟 | `pyclip`（剪贴板）+ `pynput`（模拟按键） |
| UI | `pystray`（托盘）、Tkinter（Toast 弹窗）、`tkhtmlview`（Markdown 渲染） |
| 日志 | 自封装 `util/logger.py`（RotatingFileHandler + 控制台） |
| 打包 | PyInstaller 6.0+（`build.spec` / `build-client.spec`） |
| 进程管理 | PM2（`ecosystem.config.js`，可选） |

---

## 三、项目结构

```
CapsWriter-Offline/
├── config_server.py          # 服务端配置（模型选择、路径、加速选项）
├── config_client.py          # 客户端配置（快捷键、输出模式、热词阈值）
├── core_server.py            # 服务端源码入口（WebSocket + 识别子进程）
├── core_client.py            # 客户端源码入口（麦克风模式 / 文件转录模式）
├── start_server.py           # PyInstaller 打包入口（调用 core_server.init）
├── start_client.py           # PyInstaller 打包入口（调用 core_client）
├── build.spec                # PyInstaller 配置：服务端+客户端一起打包
├── build-client.spec         # PyInstaller 配置：仅客户端（Win7 兼容）
├── zip_release.py            # 打包后用 7zip 压缩 dist 产物
├── ecosystem.config.js       # PM2 进程管理配置（可选）
│
├── util/                     # 核心逻辑模块（不打包进 exe，作为源文件分发）
│   ├── client/               # 客户端工具链
│   │   ├── audio/            # 音频采集、处理、文件管理
│   │   ├── shortcut/         # 快捷键监听与管理（pynput）
│   │   ├── udp/              # UDP 控制监听（外部程序触发录音）
│   │   ├── output/           # 结果处理、文本输出（打字/粘贴）
│   │   ├── transcribe/       # 文件转录（ffmpeg 提取、SRT 生成）
│   │   ├── ui/               # Toast 弹窗、托盘、提示显示
│   │   ├── diary/            # 日记归档（按日期保存 MD）
│   │   ├── clipboard/        # 剪贴板操作封装
│   │   ├── global_hotkey/    # 全局热键（备用方案）
│   │   ├── state.py          # 客户端全局状态（单例）
│   │   ├── startup.py        # 客户端组件初始化
│   │   ├── cleanup.py        # 客户端资源清理
│   │   └── websocket_manager.py  # WebSocket 连接管理
│   ├── server/               # 服务端工具链
│   │   ├── server_ws_recv.py # WebSocket 接收（音频缓冲、分段提交）
│   │   ├── server_ws_send.py # WebSocket 发送（结果回传）
│   │   ├── server_recognize.py   # 识别结果缓存与合并
│   │   ├── server_init_recognizer.py  # 识别器初始化
│   │   ├── service.py        # 识别子进程启动与管理
│   │   ├── state.py          # 服务端全局状态
│   │   ├── cleanup.py        # 服务端资源清理
│   │   ├── text_merge.py     # 文本拼接算法（重叠去重）
│   │   └── ollama_lifecycle.py   # Ollama 模型自动加载/卸载
│   ├── llm/                  # LLM 角色系统
│   │   ├── llm_processor.py  # LLM 调用核心
│   │   ├── llm_process_text.py   # 文本后处理入口
│   │   ├── llm_role_*.py     # 角色加载、检测、格式化
│   │   ├── llm_output_*.py   # 输出方式（打字 / Toast）
│   │   ├── llm_context.py    # 上下文组装（热词+纠错+选中文本+历史）
│   │   └── llm_*.py          # 其他 LLM 相关模块
│   ├── hotword/              # 热词系统（RAG 音素匹配）
│   │   ├── manager.py        # 热词管理器（统一入口）
│   │   ├── rag_fast.py       # FastRAG：倒排索引 + Numba JIT 粗筛
│   │   ├── rag_accu.py       # AccuRAG：精确音素匹配
│   │   ├── hot_rule.py       # 正则规则替换
│   │   ├── hot_rectification.py  # 纠错历史管理
│   │   └── algo_*.py         # 音素计算、相似度算法
│   ├── fun_asr_gguf/         # Fun-ASR-Nano GGUF 模型推理引擎
│   ├── qwen_asr_gguf/        # Qwen3-ASR GGUF 模型推理引擎
│   ├── qwen_asr_hf/          # Qwen3-ASR HuggingFace 后端（transformers/vLLM）
│   ├── common/lifecycle.py   # 应用生命周期管理（信号处理、清理回调）
│   ├── protocol.py           # 通信协议数据类（AudioMessage / RecognitionResult）
│   ├── constants.py          # 内部常量（音频格式、拼接参数）
│   ├── logger.py             # 日志系统封装
│   └── zhconv/               # 繁简转换（内嵌）
│
├── LLM/                      # 用户可自定义的 LLM 角色配置
│   ├── __init__.py           # 角色配置模板与说明
│   ├── default.py            # 默认角色（润色、纠错）
│   ├── 翻译.py               # 翻译角色示例
│   └── 小助理.py             # 助理角色示例
│
├── models/                   # 模型文件目录（Git 忽略子目录，仅保留顶层说明）
│   ├── Paraformer/
│   ├── SenseVoice-Small/
│   ├── Fun-ASR-Nano/
│   ├── Qwen3-ASR/
│   └── Punct-CT-Transformer/
│
├── hot.txt                   # 热词列表（RAG 音素匹配）
├── hot-server.txt            # 服务端热词（Fun-ASR-Nano 语境增强，建议性替换）
├── hot-rule.txt              # 正则规则替换
├── hot-rectify.txt           # 纠错历史记录（供 LLM 参考）
├── configure_shortcuts.py    # 命令行快捷键配置工具
├── block_mouse_forward.py    # 屏蔽鼠标前进键（辅助脚本）
├── assets/                   # 图标、截图、打包指南
├── docs/                     # 文档（算法说明、外部工具集成）
├── logs/                     # 运行日志（自动按日期轮转）
└── readme.md                 # 用户面向的 README（中文）
```

---

## 四、架构与核心流程

### 4.1 C/S 架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Client 客户端                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  │
│  │ 快捷键    │   │ 音频采集  │   │ 热词替换  │   │ 文本上屏  │  │
│  │(pynput)  │   │(sounddev)│   │(RAG)     │   │(打字/粘贴)│  │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘  │
│       └──────────────┴──────────────┴──────────────┘         │
│                          WebSocket                            │
└─────────────────────────────┬───────────────────────────────┘
                              │ 端口 6016
┌─────────────────────────────┴───────────────────────────────┐
│                        Server 服务端                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              主进程（WebSocket I/O）                   │   │
│  │   ws_recv  ← 音频缓冲/分段 →  queue_in  →  识别子进程   │   │
│  │   ws_send  ← 结果合并/去重 →  queue_out ←  识别子进程   │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↑                                    │
│                    独立子进程（CPU 密集）                       │
│              ┌─────────────────────┐                         │
│              │  ASR 模型推理引擎    │                         │
│              │  (Sherpa-ONNX 等)   │                         │
│              └─────────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

**设计要点**：
- 服务端主进程负责 WebSocket I/O，**独立子进程**运行 ASR 模型推理，避免阻塞网络
- 客户端与服务端通过 WebSocket 传输 base64 编码的 float32 音频（16kHz 单声道）
- 音频在客户端按 `seg_duration` + `seg_overlap` 切片流式发送

### 4.2 识别全链路

1. **采集**：按住快捷键 → 开始录音 → 实时流式发送音频 chunk
2. **切片**：客户端按 `mic_seg_duration`（默认 60s）和 `mic_seg_overlap`（默认 4s）分段
3. **服务端处理**：
   - 接收音频 → 缓冲 → 达到分段阈值后提交到识别队列
   - 双重结果：`text`（简单文本拼接，鲁棒）和 `text_accu`（时间戳去重，精确）
   - 拼接算法见 [`docs/text_merge_algorithm.md`](docs/text_merge_algorithm.md)
4. **客户端后处理**：
   - 热词替换（RAG 音素匹配）→ 正则规则替换 → 繁体转换（可选）
   - LLM 润色（可选，按角色配置）→ 文本上屏（打字或粘贴）

### 4.3 通信协议

消息定义位于 [`util/protocol.py`](util/protocol.py)：

- **AudioMessage**（Client → Server）：音频数据、task_id、source（mic/file）、分段参数
- **RecognitionResult**（Server → Client）：识别文本、时间戳、tokens、时延信息

---

## 五、关键配置文件

| 文件 | 说明 |
|------|------|
| `config_server.py` | 服务端核心配置：模型类型、模型路径、加速选项（DirectML/Vulkan）、线程数、Ollama 生命周期 |
| `config_client.py` | 客户端核心配置：服务端地址、快捷键列表、输出模式（paste/typing）、热词阈值、UDP 控制、分段参数 |
| `hot.txt` | 热词列表（一行一个），客户端 RAG 音素匹配后强制替换 |
| `hot-server.txt` | 服务端热词（仅 Fun-ASR-Nano 使用），建议性替换，不具备强制性 |
| `hot-rule.txt` | 正则规则替换（每行 `模式|替换为`） |
| `hot-rectify.txt` | 纠错历史（供 LLM 上下文参考） |
| `LLM/*.py` | 角色配置：API 提供商、模型、System Prompt、输出模式、上下文开关 |

**配置热重载**：
- `hot*.txt` 由 `watchdog` 监视，修改后自动重新加载
- `LLM/*.py` 同样支持热重载
- `config_*.py` 修改后需重启生效

---

## 六、构建与打包

### 6.1 环境准备

```bash
# 安装服务端依赖
pip install -r requirements-server.txt

# 安装客户端依赖
pip install -r requirements-client.txt

# 安装打包工具
pip install pyinstaller
```

注意：
- Windows 服务端默认使用 `onnxruntime-directml`，macOS/Linux 使用 `onnxruntime`
- `sherpa-onnx` 是核心 ASR 依赖，体积较大

### 6.2 打包命令

```bash
# 完整打包（服务端 + 客户端）
pyinstaller build.spec

# 仅打包客户端（用于 Win7 等老旧系统）
pyinstaller build-client.spec

# 打包后用 7zip 压缩
python zip_release.py
```

### 6.3 打包策略

- **第三方依赖**放入 `dist/CapsWriter-Offline/internal/`（PyInstaller 自动管理）
- **用户代码**（`util/`、`config_*.py`、`core_*.py`、`LLM/`）作为源文件复制到根目录，方便用户修改
- **模型文件**通过 Windows 目录连接符（`mklink /j`）链接，避免复制大文件
- 排除 CUDA DLL（`INCLUDE_CUDA_PROVIDER = False`），减小体积

### 6.4 运行方式

**开发调试**（源码运行）：
```bash
# 终端 1：启动服务端
python core_server.py

# 终端 2：启动客户端（麦克风模式）
python core_client.py

# 终端 2：启动客户端（文件转录模式）
python core_client.py file.mp4
```

**生产部署**（PyInstaller 产物）：
```bash
./start_server.exe
./start_client.exe
```

**PM2 后台管理**（可选）：
```bash
pm2 start ecosystem.config.js
```

---

## 七、代码规范与开发约定

### 7.1 语言与注释

- **所有代码注释、文档、日志、用户提示均使用中文**
- 文件头统一标注 `# coding: utf-8`
- 函数和类使用 Google Style Docstring（中文描述）

### 7.2 模块组织

- `util/client/`：仅客户端使用的模块
- `util/server/`：仅服务端使用的模块
- `util/common/`：客户端和服务端共享的模块（如生命周期管理）
- `util/protocol.py`：通信协议数据类（双方共享）
- 根目录保留 `config_*.py` 和 `core_*.py` 作为用户可直接修改的入口

### 7.3 状态管理

- 客户端使用 `ClientState`（`util/client/state.py`，单例模式）管理全局状态
- 服务端使用 `Cosmic`（`util/server/server_cosmic.py`，类变量全局对象）管理全局状态
- 生命周期统一由 `util/common/lifecycle.py` 的 `LifecycleManager`（单例）管理

### 7.4 日志规范

- 使用 `util/logger.py` 的 `setup_logger(name, level)` 初始化
- 服务端 logger 名称为 `'server'`，客户端为 `'client'`
- 日志文件按日期存储在 `logs/` 目录，自动轮转（默认 10MB / 保留 5 个）
- 格式：`时间 - 名称 - 级别 - [文件名:行号] - 消息`

### 7.5 异步编程

- 客户端和服务端均使用 `asyncio`
- WebSocket I/O 为异步，识别子进程为同步（通过 `multiprocessing.Process` 隔离）
- 清理回调注册到 `lifecycle.register_on_shutdown(callback)`，按 LIFO 顺序执行

---

## 八、测试策略

**本项目没有传统的单元测试套件**（无 `pytest`、`unittest` 等）。

验证方式以**手动集成测试**为主：

1. **源码运行测试**：
   ```bash
   python core_server.py  # 检查模型加载、WebSocket 启动
   python core_client.py  # 检查音频流、快捷键、连接
   ```

2. **文件转录测试**：
   ```bash
   python core_client.py test.mp3  # 检查端到端识别流程
   ```

3. **打包后测试**：
   ```bash
   pyinstaller build.spec
   ./dist/CapsWriter-Offline/start_server.exe
   ./dist/CapsWriter-Offline/start_client.exe
   ```

4. **关键日志检查**：
   - `logs/server_YYYYMMDD.log`：模型加载、识别时延、异常
   - `logs/client_YYYYMMDD.log`：连接状态、录音状态、热词替换、LLM 调用

**注意**：`.gitignore` 中排除了 `test_*.py`、`test_*.ipynb` 等测试文件，开发临时测试脚本请使用其他命名。

---

## 九、安全与隐私

1. **完全离线**：所有识别、LLM 推理均在本地完成（除非用户主动配置在线 API）
2. **音频本地存储**：录音默认保存到 `年/月/assets/` 目录，由用户掌控
3. **无遥测**：代码中不包含任何数据上报、统计收集逻辑
4. **WebSocket 局域网**：默认监听 `0.0.0.0:6016`，同一局域网内设备可连接，请注意防火墙配置
5. **UDP 广播**：客户端可将识别结果通过 UDP 广播到局域网（默认关闭，可配置）
6. **UDP 控制**：外部程序可通过 UDP 6018 发送 `START`/`STOP` 控制录音（默认开启，监听 127.0.0.1）

---

## 十、常见问题与维护要点

### 10.1 快捷键体系（重点）

本项目支持**两套并存的触发体系**：

**pynput 方案**（键盘 + 鼠标）：
- 配置：`config_client.py` 中的 `shortcuts` 列表
- 代码：`util/client/shortcut/`
- 限制：macOS 上 pynput 对鼠标侧键支持极差，只能识别为 `Button.unknown`

**Hammerspoon + UDP 方案**（macOS 鼠标侧键推荐）：
- 原理：Hammerspoon EventTap 捕获鼠标侧键 → UDP `START`/`STOP` → `util/client/udp/udp_control.py`
- 配置：`config_client.py` 中 `udp_control = True`，`shortcuts` 中注释鼠标键
- 文档：[`docs/hammerspoon_udp_control.md`](docs/hammerspoon_udp_control.md)
- **注意**：不要同时让 pynput 和 Hammerspoon 监听同一个鼠标键，会冲突

### 10.2 模型切换

在 `config_server.py` 中修改 `model_type`：
- `'qwen_asr'`：Qwen3-ASR GGUF 本地推理（需下载转换后的模型）
- `'qwen_asr_hf'`：Qwen3-ASR HuggingFace 原始权重（支持 transformers / vLLM）
- `'fun_asr_nano'`：Fun-ASR-Nano GGUF（Encoder DirectML + Decoder Vulkan 加速）
- `'sensevoice'`：SenseVoice-Small（CPU 超快，多语言）
- `'paraformer'`：Paraformer（CPU 超快，需外挂标点模型）

### 10.3 显卡加速

- **DirectML**：仅 Fun-ASR-Nano 和 Qwen3-ASR 的 ONNX Encoder 支持，默认关闭（AMD 显卡可能变慢）
- **Vulkan**：GGUF Decoder 默认通过 llama.cpp 的 Vulkan 后端加速，默认开启
- **注意**：Intel 集显在 FP16 矩阵计算时可能出现数值溢出，可将 `vulkan_force_fp32` 设为 `True`

### 10.4 修改历史速查

| 时间 | 修改内容 |
|------|---------|
| 2026-04-28 | 新增 Ollama 模型生命周期管理（服务启停自动加载/卸载）；默认模型切换为 gemma4:e4b；新增 AGENTS.md |
| 2026-04-23 | 引入 Hammerspoon UDP 控制方案；重构 `configure_shortcuts.py`；粘贴模式修复输入法问题；SwiftBar 状态支持 |
| 2026-04-23 | 新增 Qwen3-ASR-HF 后端（`util/qwen_asr_hf/`），支持 transformers / vLLM |
| 2026-04 | Qwen3-ASR GGUF 初步引入；Fun-ASR-Nano 改进 Encoder DirectML 加速 |

更详细的修改历史见 [`docs/AGENTS.md`](docs/AGENTS.md)。

---

## 十一、外部工具集成

### 11.1 SwiftBar 菜单栏插件

- CapsWriter 在录音开始/结束时写入 `status.json`（项目根目录）
- SwiftBar 插件读取 `status.json` 显示录音状态和时长
- 状态写入代码：`util/client/state.py` 中的 `ClientState._write_status_file()`

### 11.2 Hammerspoon（macOS）

- 配置文件路径：`~/.hammerspoon/lib/capswriter.lua`（不在本仓库内）
- 功能：监听鼠标侧键，通过 UDP 控制录音
- 详见 [`docs/hammerspoon_udp_control.md`](docs/hammerspoon_udp_control.md)

---

## 十二、参考资料

- 用户文档：[`readme.md`](readme.md)
- 打包指南：[`assets/BUILD_GUIDE.md`](assets/BUILD_GUIDE.md)
- 开发指南：[`CLAUDE.md`](CLAUDE.md)
- 文本拼接算法：[`docs/text_merge_algorithm.md`](docs/text_merge_algorithm.md)
- Hammerspoon 集成：[`docs/hammerspoon_udp_control.md`](docs/hammerspoon_udp_control.md)
