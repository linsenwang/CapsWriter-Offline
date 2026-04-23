# Hammerspoon + UDP 控制 CapsWriter 录音（macOS 鼠标侧键方案）

## 背景

macOS 上 `pynput` 对鼠标侧键（x1/x2）的支持极差，无法区分侧键，只能得到 `Button.unknown`。  
此方案用 **Hammerspoon** 直接监听底层鼠标事件，通过 **UDP** 命令控制 CapsWriter 开始/停止录音，彻底绕过 `pynput` 的鼠标限制。

---

## 已完成的改动

### 1. CapsWriter 配置 (`config_client.py`)

- `udp_control = True` —— 启用 UDP 控制监听
- 鼠标快捷键已注释/禁用，避免与 Hammerspoon 冲突
- 键盘快捷键（如 `F5`）仍保留，不受影响

### 2. Hammerspoon 配置

新增 `~/.hammerspoon/lib/capswriter.lua` 并在 `init.lua` 中加载。

**功能：**
- 监听鼠标侧键（默认 `Button 4`，即前进键 `x2`）
- **按下** → 发送 UDP `START` → 录音开始
- **松开** → 发送 UDP `STOP` → 录音结束
- 支持 `suppress` 选项拦截侧键，防止浏览器触发前进/后退
- **自动启动客户端**：如果 CapsWriter 客户端未运行（如已空闲自动退出），按下侧键时会自动通过 `pm2` 启动

**完整配置示例 (`~/.hammerspoon/lib/capswriter.lua`)：**

```lua
local M = {}

M.config = {
    host          = "127.0.0.1",   -- CapsWriter 监听地址（本机不改）
    port          = 6018,          -- CapsWriter 监听端口（与 config_client.py 一致）
    triggerButton = 4,             -- 4 = x2(前进键), 3 = x1(后退键)
    suppress      = true,          -- true=拦截侧键（推荐）, false=同时触发系统前进/后退
    alertTimeout  = 0.8,           -- 屏幕提示显示时长
}

-- UDP 套接字（复用）
local udp = hs.socket.udp()
udp:connect(M.config.host, M.config.port)

-- 发送 UDP 命令
local function sendCommand(cmd)
    udp:send(cmd)
end

-- 鼠标事件处理
local function handleMouseEvent(event)
    local button = event:getProperty(hs.eventtap.event.properties.mouseEventButtonNumber)
    local type = event:getType()

    if button ~= M.config.triggerButton then
        return false
    end

    if type == hs.eventtap.event.types.otherMouseDown then
        -- 按下侧键 → 开始录音
        sendCommand("START")
        hs.alert.show("🎙️ 录音开始", M.config.alertTimeout)
        return M.config.suppress

    elseif type == hs.eventtap.event.types.otherMouseUp then
        -- 松开侧键 → 结束录音
        sendCommand("STOP")
        hs.alert.show("✅ 录音结束", M.config.alertTimeout)
        return M.config.suppress
    end

    return false
end

-- 启动监听
function M.start()
    M.tap = hs.eventtap.new({
        hs.eventtap.event.types.otherMouseDown,
        hs.eventtap.event.types.otherMouseUp,
    }, handleMouseEvent)
    M.tap:start()
    hs.alert.show("🎙️ CapsWriter 监听已启动 (Button " .. M.config.triggerButton .. ")", 1.5)
end

-- 自动启动
M.start()

return M
```

在 `~/.hammerspoon/init.lua` 中添加：

```lua
capswriter = require("capswriter")
```

然后 **Reload Config** 即可生效。

---

## 快速开始

### 前提

1. 已安装 [Hammerspoon](https://www.hammerspoon.org/)
2. CapsWriter Client 已能正常运行（或已配置好 pm2 管理）
3. macOS 已授予 Hammerspoon **辅助功能（Accessibility）** 权限

### 步骤

1. **确认 Hammerspoon 配置已生效**
   ```bash
   # 重新加载 Hammerspoon 配置（或点击菜单栏图标 → Reload Config）
   ```
   看到提示 "🎙️ CapsWriter 监听已启动 (Button 4)" 即表示成功。

2. **启动 CapsWriter Client（保持后台运行）**
   ```bash
   cd /Users/yangqian/Downloads/local_asr/CapsWriter-Offline
   pm2 start ecosystem.config.js
   ```
   客户端会一直在后台运行，空闲 10 分钟后自动释放麦克风权限，但进程不退出。

3. **按下鼠标侧键**（默认是前进键 x2），即可开始录音；松开后自动停止。
   - 如果麦克风已释放，客户端会自动重新打开麦克风，然后录音
   - 重新打开麦克风只需要几秒钟，远快于重新启动整个程序

---

## 自定义配置

编辑 `~/.hammerspoon/lib/capswriter.lua` 顶部的 `M.config`：

```lua
M.config = {
    host          = "127.0.0.1",   -- CapsWriter 监听地址（本机不改）
    port          = 6018,          -- CapsWriter 监听端口（与 config_client.py 一致）
    triggerButton = 4,             -- 4 = x2(前进键), 3 = x1(后退键)
    suppress      = true,          -- true=拦截侧键（推荐）, false=同时触发系统前进/后退
    alertTimeout  = 0.8,           -- 屏幕提示显示时长
}
```

改完后 **Reload Config** 即可生效。

---

## 如何恢复纯 pynput 方案

若不想用 Hammerspoon，回退步骤：

1. 编辑 `~/.hammerspoon/init.lua`，删除或注释掉：
   ```lua
   require("capswriter")
   ```
2. 编辑 `CapsWriter-Offline/config_client.py`：
   - `udp_control = False`
   - 恢复 `shortcuts` 中的鼠标快捷键条目

---

## 故障排查

| 现象 | 排查方法 |
|------|---------|
| 按下侧键没反应 | 检查 Hammerspoon 是否有 **Accessibility** 权限；在控制台查看 Hammerspoon 日志 |
| 提示 "录音开始" 但 CapsWriter 没录 | 确认 CapsWriter 日志出现 `UDP 控制器已启动`；检查防火墙是否拦截了 UDP 6018 |
| 侧键仍触发浏览器前进/后退 | 确认 `suppress = true`；某些鼠标驱动（如 Logi Options+）会先于 Hammerspoon 拦截事件，需在驱动里把侧键设为"默认"或"不执行操作" |
| 只想用键盘快捷键 | 把 `triggerButton` 改成一个不存在的数字（如 `99`）， Hammerspoon 就不会拦截任何鼠标键 |
| 按下侧键无反应 | 检查 CapsWriter 客户端是否正在运行（`pm2 status`）；检查防火墙是否拦截 UDP 6018 |
| 麦克风没有被释放 | 检查 `config_client.py` 中 `idle_exit_enabled = True` 且 `idle_timeout` 已设置；检查客户端日志是否有"释放麦克风"字样 |
| 录音开始前有延迟 | 正常现象——麦克风被释放后，首次录音需要 1~3 秒重新初始化音频流 |

---

## 原理图

### 录音流程

```
鼠标侧键按下
    ↓
Hammerspoon 底层 EventTap 捕获 (macOS Quartz)
    ↓
UDP "START" → 127.0.0.1:6018
    ↓
CapsWriter UDPController
    ↓
如果麦克风已释放 → 自动重新打开音频流（1~3 秒）
    ↓
ShortcutTask.launch() → 开始录音
```

### 空闲自动释放麦克风机制

```
客户端启动（pm2 后台常驻）
    ↓
IdleMonitor 后台线程启动（每 30 秒检查一次）
    ↓
录音/收到 UDP 命令 → 更新 last_activity_time
    ↓
超过 idle_timeout（默认 600 秒）无活动
    ↓
IdleMonitor 调用 stream_manager.close() 关闭音频流
    ↓
麦克风权限释放，其他应用可使用麦克风
    ↓
客户端进程仍在后台运行（保留 WebSocket/LLM/热词等状态）
```
