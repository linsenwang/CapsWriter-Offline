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

---

## 六、常见故障排查速查

| 现象 | 排查点 |
|------|--------|
| 鼠标侧键没反应 | `udp_control = True`？`shortcuts` 中鼠标键是否已禁用？Hammerspoon 是否 Reload Config？ |
| Hammerspoon 提示录音开始但客户端没录 | `udp_control = True`？CapsWriter 是否已启动？防火墙是否拦截 UDP 6018？ |
| 中文输入法下英文输出变中文 | `paste = True`？`text_output.py` 的 `_is_english_text` 是否生效？ |
| SwiftBar 不显示录音状态 | `status.json` 是否存在？CapsWriter 是否重启过（使 state.py 修改生效）？ |
| 配置脚本保存后格式错乱 | `configure_shortcuts.py` 的 `write_shortcuts` 使用括号深度匹配，支持多行列表和注释 |
