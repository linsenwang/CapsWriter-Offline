# CapsWriter-Offline 项目指南（AI 维护版）

本文档汇总了项目的关键架构、配置逻辑和最近的自定义修改，方便后续 AI 维护和修改。

---

## 一、快捷键体系（重点）

本项目支持**两套并存的触发体系**，均由 `config_client.py` 中的 `shortcuts` 列表和 `udp_control` 开关控制。

### 1. pynput 方案（键盘 + 鼠标）

**代码位置**：
- 事件监听：`util/client/shortcut/shortcut_manager.py`
- 按键检测：`util/client/shortcut/key_mapper.py`
- 任务执行：`util/client/shortcut/task.py`
- 配置工具：`configure_shortcuts.py`

**配置格式**（`config_client.py` 中的 `shortcuts`）：
```python
shortcuts = [
    {
        'key': 'f5',           # 按键名称
        'type': 'keyboard',    # 'keyboard' 或 'mouse'
        'suppress': True,      # 是否拦截按键（不让其他程序收到）
        'hold_mode': True,     # True=按住录音松开停止；False=单击开始再次单击停止
        'enabled': True,       # 是否启用
        # 鼠标键额外字段：
        # 'mouse_button': 'x2'  # 仅 type='mouse' 时使用
    },
]
```

**可用按键名称**：见 `config_client.py` 底部注释（字母、数字、功能键、方向键、`x1`/`x2` 鼠标侧键等）。

**已知限制**：
- **macOS 上 pynput 对鼠标侧键支持极差**：只能识别为 `Button.unknown`，无法区分 `x1`/`x2`。
- Windows 和 Linux 的鼠标支持正常。

### 2. Hammerspoon + UDP 方案（macOS 鼠标侧键推荐）

为了解决 macOS 鼠标侧键问题，项目引入了 **Hammerspoon 监听 + UDP 控制** 的替代方案。

**原理**：
```
鼠标侧键按下 → Hammerspoon EventTap 捕获 → UDP "START" → CapsWriter UDPController → 开始录音
鼠标侧键松开 → Hammerspoon EventTap 捕获 → UDP "STOP"  → CapsWriter UDPController → 停止录音
```

**配置文件**：

| 文件 | 作用 |
|------|------|
| `config_client.py` | `udp_control = True` 启用 UDP 监听；`shortcuts` 中注释/禁用鼠标键，避免冲突 |
| `~/.hammerspoon/lib/capswriter.lua` | Hammerspoon 模块：监听鼠标侧键，发送 UDP 命令 |
| `~/.hammerspoon/init.lua` | 加载 `require("capswriter")` |

**UDP 协议**：
- 地址：`127.0.0.1:6018`
- 命令：`START` / `STOP`
- 实现代码：`util/client/udp/udp_control.py`

** Hammerspoon 配置项**（`capswriter.lua` 顶部 `M.config`）：
```lua
M.config = {
    host          = "127.0.0.1",   -- CapsWriter 监听地址
    port          = 6018,          -- CapsWriter 监听端口
    triggerButton = 4,             -- 4=x2(前进键), 3=x1(后退键)
    suppress      = true,          -- true=拦截侧键系统默认行为（防止浏览器前进/后退）
    alertTimeout  = 0.8,           -- 屏幕提示显示时长
}
```

**⚠️ 修改快捷键时的注意事项**：
- 如果用户说"鼠标不好用"或"macOS 侧键没反应"，首先检查 `udp_control` 是否为 `True`，以及 `shortcuts` 中的鼠标键是否已禁用。
- 不要同时让 pynput 和 Hammerspoon 监听同一个鼠标键，会冲突。

**⚠️ macOS 麦克风权限（2026-10-10 补充，排查"没采到声音"必读）**：

- macOS 只给 **GUI 应用**（Hammerspoon / 终端等）授予麦克风权限。**由 launchd 服务（pm2、开机启动项）拉起的进程拿不到权限**，CoreAudio 会静默返回全 0 采样。
  典型现象：提示「麦克风 XXX 完全没有采到声音，请检查设备」，但设备本身完全正常（终端里同一设备能正常采音）。
- 因此 macOS 上**不要把客户端挂到 pm2 / 开机启动项**。要么在终端里跑 `python core_client.py`，要么交给 `capswriter.lua` 自动拉起。
- `capswriter.lua` 会在 Hammerspoon 启动/重载时、以及每次按键触发时，用 **UDP `PING` / `PONG` 心跳**判断客户端是否真的可用（不要只看端口：进程卡死时 6018 还在监听，但不会回包）；不回包就先用 `lsof` 找到占端口的 `core_client.py` 杀掉，再用 `hs.execute` 拉起并轮询等待就绪。相关配置在 `~/.hammerspoon/lib/config.lua` 的 `CapsWriterConfig`。
- 拉起命令必须写成：
  ```
  (cd "工作目录" && exec 3>&- … 63>&- && exec "python" "脚本") >> "日志绝对路径" 2>&1 < /dev/null &
  ```
  三个坑：
  1. `hs.execute` 会同步等待子进程的 stdout 管道关闭。若不把后台子进程的标准流全部接管，子 shell 会一直攥着管道，**Hammerspoon 主线程会永久卡死**（所有功能失效，`hs -c` 报 send/receive timeout）。
  2. 对 `(...)` 的重定向是由**外层 shell 的工作目录**解析的，不受括号里的 `cd` 影响，所以日志路径必须用绝对路径，否则客户端根本起不来。
  3. 子进程会**继承 Hammerspoon 的全部 FD**，包括 Hammerspoon 监听 `6019` 的状态 socket。不关掉的话客户端一直攥着这个端口，Hammerspoon 下次重载时新监听绑不上（`hs.socket` 绑定失败不报错，只返回 `localPort = 0` 的空 socket），`处理中`/`完成` 弹窗就全丢了。所以 exec 前要先关掉 3~63 号 FD。

---

## 二、输出系统

**代码位置**：`util/client/output/text_output.py`

**两种输出方式**：

1. **模拟打字**（`paste=False`）：使用 `pynput` 或 `keyboard` 库逐字模拟按键输入。
   - 缺点：中文输入法下输出英文+空格时，空格会触发输入法选词。
   - 当前代码已自动检测英文文本并切换到粘贴模式（见 `_is_english_text`）。

2. **剪贴板粘贴**（`paste=True`）：将文本复制到剪贴板，模拟 `Cmd+V`/`Ctrl+V` 粘贴。
   - 优点：完全绕过输入法，中英文都稳定。
   - 当前 `config_client.py` 中 `paste = True`（全部走粘贴）。

**配置项**（`config_client.py`）：
```python
paste        = True          # True=粘贴模式, False=模拟打字
restore_clip = True          # 粘贴后是否恢复剪贴板原有内容
```

---

## 三、外部工具集成

### 1. SwiftBar 菜单栏插件

**文件位置**：`~/Library/CloudStorage/OneDrive-Personal/102_config/SwiftBar/capswriter.5s.py`
（注意：该路径不在本项目 Git 仓库内，修改后需提醒用户备份）

**功能**：
- 菜单栏显示 CapsWriter 运行状态（离线/在线/录音中）
- 点击开始/停止录音（模拟 F5 或 UDP 命令）
- 启动/停止客户端进程
- 每 5 秒刷新（由文件名 `.5s.` 控制）

**录音状态显示原理**：
- CapsWriter 在录音开始/结束时写入 `status.json`（项目根目录）
- SwiftBar 读取 `status.json` 判断当前是否录音及录音时长
- 图标颜色：🔴 红色=录音中（带秒数），🎤 绿色=在线未录音，⚪️ 灰色=离线

**状态文件**（`status.json`）：
```json
{
    "recording": true,
    "recording_start_time": 1713881200.0,
    "timestamp": 1713881215.0
}
```
- 写入代码：`util/client/state.py` 中的 `ClientState._write_status_file()`
- 如果文件超过 30 秒未更新，SwiftBar 会认为客户端已崩溃，显示未录音。

### 2. Hammerspoon（macOS 窗口管理器）

**文件位置**：`~/.hammerspoon/lib/capswriter.lua`（同上，不在 Git 仓库内）

**功能**：监听鼠标侧键，通过 UDP 控制 CapsWriter 录音。

---

## 四、配置文件清单

| 配置项 | 文件 | 说明 |
|--------|------|------|
| 服务端地址 | `config_client.py` | `addr`, `port` |
| 快捷键 | `config_client.py` | `shortcuts` 列表 |
| UDP 控制 | `config_client.py` | `udp_control`, `udp_control_addr`, `udp_control_port` |
| 输出模式 | `config_client.py` | `paste`, `restore_clip` |
| 录音阈值 | `config_client.py` | `threshold`（秒） |
| 日志级别 | `config_client.py` | `log_level` |
| 热词/LLM | `config_client.py` | `hot`, `llm_enabled` 等 |
| 快捷键交互配置 | `configure_shortcuts.py` | 命令行工具，自动修改 `config_client.py` |

---

## 五、关键代码修改历史

### 2026-04-23: macOS 鼠标侧键方案 + 粘贴模式 + SwiftBar 状态

1. **Hammerspoon UDP 控制**
   - 新增 `util/client/udp/udp_control.py`（已有，启用配置）
   - 新增 `docs/hammerspoon_udp_control.md`
   - 修改 `config_client.py`：`udp_control = True`，注释鼠标快捷键
   - 用户本地新增 `~/.hammerspoon/lib/capswriter.lua`

2. **configure_shortcuts.py 重构**
   - 支持配置 Hammerspoon 方案（选项 `[3]`）
   - 修复 `write_shortcuts()` 多行列表替换 bug（使用括号深度匹配）
   - 新增 `write_udp_control()` / `read_udp_control()`
   - 自动禁用 pynput 鼠标键以避免冲突

3. **粘贴模式修复输入法问题**
   - 修改 `util/client/output/text_output.py`：自动检测英文文本并切换到粘贴模式
   - 修改 `config_client.py`：`paste = True`（全部走粘贴）

4. **SwiftBar 录音状态**
   - 修改 `util/client/state.py`：`start_recording()` / `stop_recording()` 写入 `status.json`
   - 修改 SwiftBar 插件：读取 `status.json` 显示录音时长和状态

### 2026-10-10: macOS 麦克风权限导致"没采到声音" + Hammerspoon 自动拉起客户端

**现象**：客户端一直提示「未识别：麦克风 External Microphone 完全没有采到声音，请检查设备」，但设备本身正常（终端里直接读同一设备电平正常）。

**根因**：客户端当时由 **pm2** 托管，而 pm2 守护进程是开机时由 launchd（`~/Library/LaunchAgents/pm2.yangqian.plist`）拉起的，没有 GUI 应用身份，macOS 拒绝授予麦克风权限，CoreAudio 静默返回全 0 采样。

**处理**：
1. `pm2 delete capswriter` + `pm2 save`，客户端不再由 pm2 托管
2. 改为由 Hammerspoon 负责自动拉起客户端（见 `docs/AGENTS.md` 第一节的 macOS 麦克风权限说明）
3. 顺带修掉两个坑：`hs.execute` 的管道阻塞（会让 Hammerspoon 主线程卡死）、后台子进程重定向的日志路径必须用绝对路径

### 2026-11-12: 客户端整体冻结 + 状态弹窗消失 + 子线程 Tkinter 崩溃

**现象**：
1. 按侧键没有反应，Hammerspoon 的「录音开始」照常弹出，但既没录音也没结果；
2. 后来的修复过程中发现「处理中 / 润色 / 完成」这些状态弹窗全都没了，只剩 Hammerspoon 自己发的开始/结束提示。

**根因**：
1. 客户端进程卡死——所有线程都在等 GIL，其中一个线程卡在 `Tk_CreateConsoleWindow → NSMenu insertItem → NSOperation waitUntilFinished`。macOS 的 AppKit 要求窗口只能在**主线程**创建，`ToastMessageManager` / `*_menu_handler` 却在子线程里 `tk.Tk()`（触发点之一是 `llm_stop_monitor` 的 ESC 中断键回调），NSMenu 初始化要等主线程、主线程在 asyncio 里等 I/O，互相死等，且死等时攥着 GIL → 整个进程冻结。端口 6018 还在监听，所以 Hammerspoon 的 `lsof` 判定"已就绪"，`START` 全石沉大海。
2. 状态弹窗消失：`hs.socket.udp.server(6019, …)` 绑定失败**不报错**，只返回一个 `localPort = 0` 的空 socket。当时 6019 被"客户端继承的 Hammerspoon FD"占着（见第一节坑 3），绑定静默失败，而代码把"拿到对象"当成"已启动"并保存下来，之后再也不会重试。

**处理**：
1. `util/ui/toast_manager.py`、`util/ui/{context,hotword,rectify}_menu_handler.py` 增加 `self.available = sys.platform != 'darwin'`，macOS 上不启动 Tk 线程；Toast 输出模式自动降级为打字输出，对话框只从托盘进入（托盘在 macOS 本来就关着）。
2. `~/.hammerspoon/lib/capswriter.lua`：
   - 就绪判断改成 UDP `PING`/`PONG` 心跳，并在拉起前杀掉占着 6018 的僵尸 `core_client.py`；
   - 绑定状态端口后校验 `sock:info().localPort`，失败每 5 秒重试；
   - 拉起客户端时关闭 3~63 号继承 FD；
   - 加 `clientStarting` 闸门，避免并发拉起两个客户端。
3. 排查手段记录：`lsof -nP -iUDP:6018` 看端口归属、`sample <pid> 2` 看线程栈、`python -c "import socket; … sendto(b'PING', ('127.0.0.1',6018))"` 验证客户端是否还有响应。
4. `config_client.py` 关闭非核心功能：`llm_enabled = False`（不再初始化 LLM、不注册 ESC 中断键，识别结果直接输出，无润色/翻译/小助理）、清空 `voice_commands`。热词、标点、日记、录音保存、状态回传、空闲释放麦克风都保留。
5. 顺带修掉 `capswriter.lua` 的一个老 bug：`hs.socket.udp:send` 必须显式传 host/port，只传消息会报 `argument 3 (expected string)`；原代码发送失败后仍把 `isRecording` 置真，导致之后所有按键被开头的 `if isRecording` 吞掉（侧键"没反应"）。现改为显式 host/port，且发送失败不置位。

### 2026-11-22: 聚焦窗口截图辅助 LLM 后处理

**目的**：把当前聚焦窗口的截图一并交给支持视觉输入的后处理模型，利用界面里的术语、文件名、代码等上下文纠正 ASR 同音字。

**实现**：
1. `capswriter.lua` 在松开录音键时（`stopRecording`）用 `hs.task` 异步执行 `screencapture -x -o -l <windowId>`，把截图和 `{app, title, ts, path}` 写入 `~/Library/Caches/CapsWriter/last_shot.{png,json}`。用 `hs.task` 而不是 `hs.execute`，避免阻塞 Hammerspoon 主线程。
2. 客户端新增 `util/tools/window_capture.py`：优先读取并删除上述文件；没有可用截图时回退到 Quartz + `screencapture` 直接抓前台窗口（需要屏幕录制权限）。图片按长边 `screenshot_max_edge` 缩小后转 base64；默认 **1024**（实测 4 次全部保留 `fun_asr_nano` 等代码写法，约 1.2s；896 偶尔会归一化成 `Fun-ASR-Nano`，1280 更慢且更容易忽略截图）。
3. `RoleConfig` 增加 `enable_screenshot` / `screenshot_max_edge`；`LLM/default.py` 默认开启。`MessageBuilder` 负责按 provider 组装图片：Ollama 用 `images` 数组，OpenAI 兼容接口用 `image_url` data URI。
4. 附图时在 system prompt 末尾追加约束：截图可用于查证术语、理解上下文，也可以回答用户关于当前窗口的问题；不要整段抄代码，代码标识符按截图中的大小写/下划线/连字符原样使用；只输出最终结果，不输出分析过程。
5. 新增 `util/debug/bench_screenshot_llm.py`，可对不同 `screenshot_max_edge` 跑同一段语音，统计编码耗时、模型耗时和术语命中数，方便换模型/换窗口后重新选值。
6. 重新开启 `llm_enabled`；LLM 输出先缓冲，再由 `util/llm/llm_text_cleaner.py` 去掉「根据规则/当前文本/因此」这类过程性段落，换行替换为空格，并去掉常见 Markdown 标记，避免打字时把思考过程打出去或触发回车发送。
7. 顺带修复新版 pynput 的 `GlobalHotKeys._on_press` / `_on_release` 签名不兼容：macOS 后端只传 `key`，但方法需要 `injected`，用 `_CompatGlobalHotKeys` 补上可选参数，避免 ESC 中断键监听报 `TypeError`。
8. 实测 Qwen3.5 图片 token 公式：`ceil(width/32) * ceil(height/32) + 2`。例如 1024×640≈642、1024×1024≈1026、896×560≈506；`MessageBuilder` 会按截图实际尺寸估算并在日志打印 `附图 tokens`，不再固定按 800 计算。
9. 新增中断链路：开始新录音（`ShortcutTask.launch`）、按 `ESC`、或发送 UDP `CANCEL` / `STOP_LLM` 都会设置停止事件；Ollama/OpenAI 流在 chunk 间检查并关闭连接，缓冲后的打字按 16 字分段检查，避免长回答或卡住的请求阻塞下一条识别结果。
10. 截图预取：`ShortcutTask.finish` 启动 `start_prefetch`，在 ASR 处理期间完成读图/缩放/base64；LLM 请求优先 `take_prefetched`。实测 973KB 原生截图现场编码约 75ms，预取后取用约 0ms。另测 Ollama 预热：纯文本和带图都一样，预热后真实请求的 `prompt_eval_duration` 仍约 347ms，说明没有跨请求前缀缓存，因此不采用提前发 LLM 请求的方案。

**注意**：截图会随每次 LLM 处理发送到 Ollama 服务端，可能包含隐私内容；不需要时把角色配置改成 `enable_screenshot = False`，或在 Hammerspoon 配置里设 `screenshotEnabled = false`。

### 2026-11-22: 修复首次触发误报「未就绪」

**现象**：Hammerspoon 的 10 秒可达缓存过期后，第一次按快捷键会提示「未就绪」，要等一次远程唤醒或按第二次才能录音。

**根因**：`checkRemoteServer` 用 `nc -z -G 2 rmsh 6016` 探测远端，但 `rmsh` 只是 `~/.ssh/config` 里的 SSH 别名，`nc` 不读 SSH 配置，永远解析失败；于是第一次触发必然走 `wakeRemoteServer`，第二次因为 `remoteLastOk` 缓存才正常。

**处理**：
1. 客户端 PING 回包从 `PONG` 改成 `PONG <addr> <port>`（`util/client/udp/udp_control.py`）。
2. `capswriter.lua` 的 `checkClientReady` 解析并缓存这个地址；`checkRemoteServer` 优先用缓存地址，`remoteProbeHost` 作为可选后备。
3. 仍然保留 `ssh rmsh` 做远程唤醒——SSH 别名只用于 ssh，不用于 nc。

---

## 六、常见故障排查速查

| 现象 | 排查点 |
|------|--------|
| 鼠标侧键没反应 | `udp_control = True`？`shortcuts` 中鼠标键是否已禁用？Hammerspoon 是否 Reload Config？ |
| Hammerspoon 提示录音开始但客户端没录 | `udp_control = True`？CapsWriter 是否已启动？防火墙是否拦截 UDP 6018？ |
| **录音全程静音，提示「麦克风 XXX 完全没有采到声音」** | 客户端是不是被 pm2 / 开机启动项（launchd）拉起的？换成终端启动或让 Hammerspoon 拉起。用 `ps -o ppid= -p <客户端PID>` 看父进程，父进程是 launchd(1) 且不是终端起的 → 无麦克风权限 |
| Hammerspoon 所有功能突然卡死、`hs -c` 超时 | 是不是用 `hs.execute` 起了长期后台进程且没重定向 stdout？管道不关闭会阻塞主线程 |
| 侧键「录音开始」正常弹出，但没有识别结果 | 客户端是不是卡死了：`lsof -nP -iUDP:6018` 看端口在不在、`sample <pid> 2` 看线程栈；向 6018 发 `PING` 看有没有 `PONG` |
| 「处理中 / 润色 / 完成」弹窗消失 | 6019 被谁占着？`lsof -nP -iUDP:6019` 应该只有 Hammerspoon。若被 `core_client.py` 占着，说明它继承了 Hammerspoon 的 FD，重启客户端即可 |
| 中文输入法下英文输出变中文 | `paste = True`？`text_output.py` 的 `_is_english_text` 是否生效？ |
| SwiftBar 不显示录音状态 | `status.json` 是否存在？CapsWriter 是否重启过（使 state.py 修改生效）？ |
| 配置脚本保存后格式错乱 | `configure_shortcuts.py` 的 `write_shortcuts` 使用括号深度匹配，支持多行列表和注释 |
