-- ============================================
-- CapsWriter UDP 控制器
-- 用 Hammerspoon 监听鼠标侧键和键盘快捷键，绕过 pynput 的限制
-- ============================================

local M = {}

-- 用户配置
M.config = {
    host          = "127.0.0.1",   -- CapsWriter 监听地址
    port          = 6018,          -- CapsWriter 监听端口
    triggerButton = 4,             -- 触发录音的鼠标按钮：3=x1(后退), 4=x2(前进)
    suppress      = true,          -- true=拦截侧键，不让系统触发前进/后退
    alertTimeout  = 0.8,           -- 提示显示时长（秒）
    statusPort    = 6019,          -- 监听 CapsWriter 处理状态回传的 UDP 端口
    -- 弹窗位置：atScreenEdge 0=居中 1=顶部 2=底部；alignment 可设 left/center/right
    alertStyle    = { atScreenEdge = 1, textStyle = { alignment = "right" } },

    -- 键盘快捷键配置（按住录音，松开停止）
    keyMods       = {"shift"},     -- 修饰键数组，如 {"shift"}, {"cmd", "alt"}
    keyTrigger    = "right",       -- 触发键名，如 "right", "f5", "space"
    keyEnabled    = true,          -- 是否启用键盘快捷键
}

-- 内部状态
local isRecording = false
local statusUdp = nil            -- UDP 状态监听对象

-- 发送 UDP 命令（异步，不阻塞 Hammerspoon）
local function sendUDP(cmd)
    local pyScript = string.format(
        "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(b'%s',('%s',%d))",
        cmd, M.config.host, M.config.port
    )
    hs.task.new("/usr/bin/python3", function(exitCode, stdOut, stdErr)
        if exitCode ~= 0 then
            hs.alert.show("❌ CapsWriter UDP 发送失败\n" .. tostring(stdErr), M.config.alertStyle, nil, 2)
        end
    end, {"-c", pyScript}):start()
end

-- UDP 状态监听任务（hs.udp 不可用时用 Python 备选）
M.statusTask = nil

-- 启动 UDP 状态监听（接收 CapsWriter 处理状态）
local function startStatusListener()
    if M.statusTask and M.statusTask:isRunning() then
        return
    end

    local pyScript = [[import socket, sys
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('127.0.0.1', 6019))
sock.settimeout(1.0)
print("UDP_STATUS_LISTENER_READY")
sys.stdout.flush()
while True:
    try:
        data, addr = sock.recvfrom(1024)
        line = data.decode('utf-8', errors='ignore').strip()
        if line.startswith('STATUS:'):
            print(line)
            sys.stdout.flush()
    except socket.timeout:
        pass
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"ERROR:{e}")
        sys.stdout.flush()
        break
sock.close()
]]

    M.statusTask = hs.task.new("/usr/bin/python3", nil, function(task, stdOut, stdErr)
        if stdOut then
            stdOut = stdOut:gsub("^%s*(.-)%s*$", "%1")
            if stdOut:match("^STATUS:") then
                local statusLine = stdOut:match("^STATUS:(.+)$")
                if statusLine then
                    local statusType, message = statusLine:match("^([^|]+)|(.+)$")
                    if message then
                        hs.alert.show(message, M.config.alertStyle, nil, M.config.alertTimeout)
                        print(string.format("[CapsWriter] 状态更新: %s", message))
                    end
                end
            elseif stdOut == "UDP_STATUS_LISTENER_READY" then
                print(string.format("[CapsWriter] Python UDP 状态监听已启动 | port=%d", M.config.statusPort))
            end
        end
        if stdErr and stdErr:match("^%s*(.-)%s*$") ~= "" then
            print(string.format("[CapsWriter] 状态监听 stderr: %s", stdErr:gsub("^%s*(.-)%s*$", "%1")))
        end
        return true
    end, {"-c", pyScript})

    if M.statusTask then
        M.statusTask:start()
    else
        print("[CapsWriter] 状态监听任务创建失败")
    end
end

-- 停止 UDP 状态监听
local function stopStatusListener()
    if M.statusTask then
        if M.statusTask:isRunning() then
            M.statusTask:terminate()
        end
        M.statusTask = nil
        print("[CapsWriter] 状态监听已停止")
    end
end

-- 开始录音（带来源标记防止重复触发）
local function startRecording(source)
    if not isRecording then
        sendUDP("START")
        isRecording = true
        hs.alert.show("录音开始", M.config.alertStyle, nil, M.config.alertTimeout)
        print(string.format("[CapsWriter] 录音开始 | source=%s", source))
    end
end

-- 停止录音（带来源标记）
local function stopRecording(source)
    if isRecording then
        sendUDP("STOP")
        isRecording = false
        hs.alert.show("录音结束", M.config.alertStyle, nil, M.config.alertTimeout)
        print(string.format("[CapsWriter] 录音结束 | source=%s", source))
    end
end

-- ========== 鼠标监听器 ==========

M.mouseTap = hs.eventtap.new({
    hs.eventtap.event.types.otherMouseDown,
    hs.eventtap.event.types.otherMouseUp,
}, function(event)
    local btn = event:getProperty(hs.eventtap.event.properties.mouseEventButtonNumber)
    if btn ~= M.config.triggerButton then
        return false
    end

    local etype = event:getType()

    if etype == hs.eventtap.event.types.otherMouseDown then
        startRecording("mouse")
        return M.config.suppress
    elseif etype == hs.eventtap.event.types.otherMouseUp then
        stopRecording("mouse")
        return M.config.suppress
    end

    return false
end)

-- ========== 键盘监听器 ==========

M.keyBinding = hs.hotkey.new(M.config.keyMods, M.config.keyTrigger, function()
    startRecording("keyboard")
end, function()
    stopRecording("keyboard")
end)

-- ========== 公共接口 ==========

function M.start()
    local started = {}

    if M.mouseTap and not M.mouseTap:isEnabled() then
        M.mouseTap:start()
        table.insert(started, "鼠标 Button " .. M.config.triggerButton)
    end

    if M.keyBinding and M.config.keyEnabled then
        M.keyBinding:enable()
        table.insert(started, "键盘 " .. table.concat(M.config.keyMods, "+") .. "+" .. M.config.keyTrigger)
    end

    -- 启动 UDP 状态监听
    startStatusListener()

    if #started > 0 then
        hs.alert.show("🎙️ CapsWriter 监听已启动 | " .. table.concat(started, ", "), M.config.alertStyle, nil, 2)
    end
end

function M.stop()
    if M.mouseTap and M.mouseTap:isEnabled() then
        M.mouseTap:stop()
    end
    if M.keyBinding then
        M.keyBinding:disable()
    end
    stopStatusListener()
    hs.alert.show("🎙️ CapsWriter 监听已停止", M.config.alertStyle, nil, 2)
end

function M.isRunning()
    local mouseRunning = M.mouseTap and M.mouseTap:isEnabled()
    local keyRunning = M.keyBinding and M.keyBinding.enabled
    return mouseRunning or keyRunning
end

-- ========== 手柄外部调用接口 ==========
-- 供手柄映射工具通过 AppleScript 调用：
-- osascript -e 'tell application "Hammerspoon" to execute lua code "CapsWriterGamepadStart()"'
_G.CapsWriterGamepadStart = function()
    startRecording("gamepad")
end
_G.CapsWriterGamepadStop = function()
    stopRecording("gamepad")
end

-- 启用 AppleScript 支持，允许外部程序（如手柄映射工具）调用 Hammerspoon
local appleScriptResult = hs.allowAppleScript(true)
print("[CapsWriter] hs.allowAppleScript(true) result: " .. tostring(appleScriptResult))

-- 自动启动
M.start()

print(string.format("[CapsWriter] 已加载 | host=%s:%d | button=%d | key=%s+%s | suppress=%s",
    M.config.host, M.config.port, M.config.triggerButton,
    table.concat(M.config.keyMods, "+"), M.config.keyTrigger,
    tostring(M.config.suppress)))

return M
