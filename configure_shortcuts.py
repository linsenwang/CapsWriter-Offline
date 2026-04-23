# coding: utf-8
"""
交互式快捷键配置工具

用法：
    python configure_shortcuts.py

功能：
    1. 按键测试模式：按任意键/鼠标，查看 pynput 识别到的名称
    2. 生成配置：自动将识别到的按键写入 config_client.py
    3. Hammerspoon 鼠标侧键配置（macOS）：绕过 pynput 鼠标限制，通过 UDP 控制录音

注意：
    - macOS 上 pynput 对鼠标侧键支持有限，通常只能识别为 "unknown"
    - 如果侧键无法识别，建议使用 Hammerspoon 方案（选项 [3]）
"""

import ast
import platform
import re
import sys
from pathlib import Path

from pynput import keyboard, mouse

CONFIG_PATH = Path(__file__).parent / "config_client.py"
HAMMERSPOON_DIR = Path.home() / ".hammerspoon"
CAPSWRITER_LUA = HAMMERSPOON_DIR / "lib" / "capswriter.lua"
INIT_LUA = HAMMERSPOON_DIR / "init.lua"

CAPSWRITER_LUA_TEMPLATE = '''-- ============================================
-- CapsWriter UDP 控制器（由 configure_shortcuts.py 自动生成）
-- 用 Hammerspoon 监听鼠标侧键，通过 UDP 控制 CapsWriter 录音
-- ============================================

local M = {{}}

-- 用户配置
M.config = {{
    host          = "127.0.0.1",   -- CapsWriter 监听地址
    port          = 6018,          -- CapsWriter 监听端口
    triggerButton = {trigger_button}, -- {button_desc}
    suppress      = {suppress},    -- true=拦截侧键，false=放行
    alertTimeout  = 0.8,           -- 提示显示时长（秒）
}}

-- 内部状态
local isRecording = false

-- 发送 UDP 命令（异步，不阻塞 Hammerspoon）
local function sendUDP(cmd)
    local pyScript = string.format(
        "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(b'%s',('%s',%d))",
        cmd, M.config.host, M.config.port
    )
    hs.task.new("/usr/bin/python3", function(exitCode, stdOut, stdErr)
        if exitCode ~= 0 then
            hs.alert.show("❌ CapsWriter UDP 发送失败\\n" .. tostring(stdErr), 2)
        end
    end, {{"-c", pyScript}}):start()
end

-- 创建全局鼠标事件监听器
M.tap = hs.eventtap.new({{
    hs.eventtap.event.types.otherMouseDown,
    hs.eventtap.event.types.otherMouseUp,
}}, function(event)
    local btn = event:getProperty(hs.eventtap.event.properties.mouseEventButtonNumber)
    if btn ~= M.config.triggerButton then
        return false
    end

    local etype = event:getType()

    if etype == hs.eventtap.event.types.otherMouseDown then
        if not isRecording then
            sendUDP("START")
            isRecording = true
            hs.alert.show("🎤 录音开始", M.config.alertTimeout)
        end
        return M.config.suppress

    elseif etype == hs.eventtap.event.types.otherMouseUp then
        if isRecording then
            sendUDP("STOP")
            isRecording = false
            hs.alert.show("⏹ 录音结束", M.config.alertTimeout)
        end
        return M.config.suppress
    end

    return false
end)

function M.start()
    if M.tap and not M.tap:isEnabled() then
        M.tap:start()
        hs.alert.show("🎙️ CapsWriter 监听已启动 (Button " .. M.config.triggerButton .. ")", 2)
    end
end

function M.stop()
    if M.tap and M.tap:isEnabled() then
        M.tap:stop()
        hs.alert.show("🎙️ CapsWriter 监听已停止", 2)
    end
end

function M.isRunning()
    return M.tap and M.tap:isEnabled()
end

-- 自动启动
M.start()

print(string.format("[CapsWriter] 已加载 | host=%s:%d | button=%d | suppress=%s",
    M.config.host, M.config.port, M.config.triggerButton, tostring(M.config.suppress)))

return M
'''


# ==================== 按键检测 ====================

class KeyDetector:
    """按键检测器"""

    def __init__(self):
        self.last_key = None
        self.last_type = None
        self._stopped = False

    def _on_keyboard_press(self, key):
        name = self._key_to_name(key)
        if name:
            self.last_key = name
            self.last_type = "keyboard"
            self._stopped = True
            return False

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        name = self._button_to_name(button)
        if name:
            self.last_key = name
            self.last_type = "mouse"
            self._stopped = True
            return False

    @staticmethod
    def _key_to_name(key):
        if hasattr(key, 'name') and key.name:
            return key.name
        elif hasattr(key, 'char') and key.char:
            return key.char.lower()
        return str(key)

    @staticmethod
    def _button_to_name(button):
        if button == mouse.Button.left:
            return "left"
        elif button == mouse.Button.right:
            return "right"
        elif button == mouse.Button.middle:
            return "middle"
        elif hasattr(mouse.Button, 'x1') and button == mouse.Button.x1:
            return "x1"
        elif hasattr(mouse.Button, 'x2') and button == mouse.Button.x2:
            return "x2"
        elif button == mouse.Button.unknown:
            return "unknown"
        return str(button)

    def detect(self):
        self.last_key = None
        self.last_type = None
        self._stopped = False

        k_listener = keyboard.Listener(on_press=self._on_keyboard_press)
        m_listener = mouse.Listener(on_click=self._on_click)
        k_listener.start()
        m_listener.start()

        try:
            while not self._stopped:
                import time
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            k_listener.stop()
            m_listener.stop()

        return self.last_key, self.last_type


# ==================== config_client.py 读写 ====================

def read_current_shortcuts():
    if not CONFIG_PATH.exists():
        return []
    content = CONFIG_PATH.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "shortcuts":
                        return ast.literal_eval(node.value)
    except Exception:
        pass
    return []


def _find_bracket_block(text, start_idx):
    """从 [ 开始，找到匹配的闭合 ]，返回结束位置（不含）"""
    bracket_pos = text.find("[", start_idx)
    if bracket_pos == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[bracket_pos:], start=bracket_pos):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def write_shortcuts(shortcuts):
    content = CONFIG_PATH.read_text(encoding="utf-8")
    match = re.search(r"shortcuts\s*=\s*\[", content)
    if not match:
        return False

    start = match.start()
    end = _find_bracket_block(content, start)
    if end is None:
        return False

    # content[:start] 已经保留了 shortcuts 前面的缩进空格，
    # 所以 new_value 只需要从 shortcuts 开始即可
    repr_str = repr(shortcuts)
    new_value = f"shortcuts = {repr_str}"

    new_content = content[:start] + new_value + content[end:]
    CONFIG_PATH.write_text(new_content, encoding="utf-8")
    return True


def read_udp_control():
    if not CONFIG_PATH.exists():
        return False
    content = CONFIG_PATH.read_text(encoding="utf-8")
    match = re.search(r"udp_control\s*=\s*(True|False)", content)
    if match:
        return match.group(1) == "True"
    return False


def write_udp_control(enabled):
    content = CONFIG_PATH.read_text(encoding="utf-8")
    pattern = r"(udp_control\s*=\s*)(True|False)"
    if not re.search(pattern, content):
        return False
    new_content = re.sub(pattern, f"\\g<1>{'True' if enabled else 'False'}", content, count=1)
    CONFIG_PATH.write_text(new_content, encoding="utf-8")
    return True


# ==================== Hammerspoon 读写 ====================

def hammerspoon_available():
    return HAMMERSPOON_DIR.exists() and INIT_LUA.exists()


def read_hammerspoon_config():
    """读取 capswriter.lua 中的配置，返回 dict 或 None"""
    if not CAPSWRITER_LUA.exists():
        return None
    content = CAPSWRITER_LUA.read_text(encoding="utf-8")
    cfg = {}
    m = re.search(r'triggerButton\s*=\s*(\d+)', content)
    cfg['trigger_button'] = int(m.group(1)) if m else 4
    m = re.search(r'suppress\s*=\s*(true|false)', content)
    cfg['suppress'] = m.group(1) == 'true' if m else True
    return cfg


def write_hammerspoon_config(button='x2', suppress=True):
    """修改 capswriter.lua 的配置值"""
    if not CAPSWRITER_LUA.exists():
        return False
    content = CAPSWRITER_LUA.read_text(encoding="utf-8")
    trigger_num = 3 if button == 'x1' else 4
    content = re.sub(r'(triggerButton\s*=\s*)\d+', f'\\g<1>{trigger_num}', content)
    content = re.sub(r'(suppress\s*=\s*)(true|false)', f'\\g<1>{"true" if suppress else "false"}', content)
    CAPSWRITER_LUA.write_text(content, encoding="utf-8")
    return True


def ensure_hammerspoon_files(button='x2', suppress=True):
    """确保 capswriter.lua 存在且 init.lua 已加载它"""
    # 创建 lib 目录
    CAPSWRITER_LUA.parent.mkdir(parents=True, exist_ok=True)

    # 创建 capswriter.lua（如果不存在）
    if not CAPSWRITER_LUA.exists():
        trigger_num = 3 if button == 'x1' else 4
        button_desc = 'x1/后退键' if button == 'x1' else 'x2/前进键'
        lua_content = CAPSWRITER_LUA_TEMPLATE.format(
            trigger_button=trigger_num,
            suppress='true' if suppress else 'false',
            button_desc=button_desc,
        )
        CAPSWRITER_LUA.write_text(lua_content, encoding="utf-8")

    # 确保 init.lua 中有 require("capswriter")
    if INIT_LUA.exists():
        init_content = INIT_LUA.read_text(encoding="utf-8")
        if 'require("capswriter")' not in init_content and "require('capswriter')" not in init_content:
            with open(INIT_LUA, "a", encoding="utf-8") as f:
                f.write('\nrequire("capswriter")  -- CapsWriter 鼠标侧键触发录音（UDP 控制）\n')

    return True


def remove_hammerspoon_from_init():
    """从 init.lua 中移除 require("capswriter")"""
    if not INIT_LUA.exists():
        return
    content = INIT_LUA.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    new_lines = [ln for ln in lines if 'capswriter' not in ln.lower()]
    INIT_LUA.write_text(''.join(new_lines), encoding="utf-8")


# ==================== 交互界面 ====================

def print_banner():
    print("=" * 55)
    print("  CapsWriter 快捷键配置工具")
    print("=" * 55)
    print()


def print_macos_warning():
    if platform.system() == "Darwin":
        print("⚠️  macOS 检测提示：")
        print("    pynput 在 macOS 上通常无法区分鼠标侧键（x1/x2），")
        print("    侧键可能被识别为 'unknown'。")
        print("    建议：使用 [3] 配置 Hammerspoon 方案，绕过此限制。")
        print()


def print_status(shortcuts):
    udp_on = read_udp_control()
    hs_cfg = read_hammerspoon_config()

    print()
    print("-" * 55)
    print("当前触发方式：")

    # pynput 键盘
    kb_shortcuts = [s for s in shortcuts if s.get("type") == "keyboard"]
    if kb_shortcuts:
        print("  [pynput 键盘]")
        for i, sc in enumerate(kb_shortcuts, 1):
            enabled = "✅" if sc.get("enabled", True) else "❌"
            print(f"    {i}. [{sc.get('key', '?')}] hold={sc.get('hold_mode', True)}, "
                  f"suppress={sc.get('suppress', False)} {enabled}")
    else:
        print("  [pynput 键盘] （无）")

    # Hammerspoon 鼠标
    if hs_cfg and udp_on:
        btn = hs_cfg.get('trigger_button', 4)
        btn_name = 'x1/后退' if btn == 3 else 'x2/前进'
        suppress = '是' if hs_cfg.get('suppress', True) else '否'
        print(f"  [Hammerspoon 鼠标侧键] Button {btn} ({btn_name}), 拦截={suppress} ✅")
    else:
        print("  [Hammerspoon 鼠标侧键] 未启用")

    print()


def configure_hammerspoon():
    """配置 Hammerspoon 鼠标侧键"""
    if platform.system() != "Darwin":
        print("    Hammerspoon 方案仅适用于 macOS，当前系统不支持。")
        return

    if not hammerspoon_available():
        print("    ❌ 未检测到 Hammerspoon 配置目录 (~/.hammerspoon/init.lua)")
        print("       请先安装 Hammerspoon: https://www.hammerspoon.org/")
        return

    print()
    print(">>> Hammerspoon 鼠标侧键配置")
    print("    此方案用 Hammerspoon 底层 EventTap 监听鼠标侧键，")
    print("    通过 UDP 命令控制 CapsWriter 录音，绕过 pynput 限制。")
    print()

    # 选择按钮
    print("    选择要绑定的鼠标按钮：")
    print("      [1] x1 - 后退键 (Button 3)")
    print("      [2] x2 - 前进键 (Button 4) ← 推荐")
    btn_choice = input("    请选择 [1/2] (默认 2): ").strip()
    button = "x1" if btn_choice == "1" else "x2"

    # 是否拦截
    suppress = input("    是否拦截侧键系统默认行为？(不让浏览器前进/后退) [Y/n]: ").strip().lower()
    suppress = suppress != "n"

    # 写入文件
    ensure_hammerspoon_files(button=button, suppress=suppress)
    write_hammerspoon_config(button=button, suppress=suppress)

    # 修改 config_client.py
    write_udp_control(True)

    # 把 shortcuts 里的鼠标键禁用（避免冲突）
    shortcuts = read_current_shortcuts()
    changed = False
    for sc in shortcuts:
        if sc.get("type") == "mouse":
            sc["enabled"] = False
            changed = True
    if changed:
        write_shortcuts(shortcuts)

    print()
    print("    ✅ Hammerspoon 配置已更新！")
    print(f"       触发按钮: {button} (Button {3 if button == 'x1' else 4})")
    print(f"       拦截系统行为: {'是' if suppress else '否'}")
    print("       UDP 控制: 已启用")
    print()
    print("    ⚠️  请 Reload Hammerspoon 配置以生效（菜单栏图标 → Reload Config）")


def remove_hammerspoon():
    """移除 Hammerspoon 配置，切回纯 pynput"""
    print()
    print(">>> 移除 Hammerspoon 配置")

    # 关闭 UDP
    write_udp_control(False)

    # 从 init.lua 移除 require
    remove_hammerspoon_from_init()

    print("    ✅ 已关闭 UDP 控制并从 init.lua 移除加载")
    print("    ℹ️  capswriter.lua 文件已保留（如需彻底删除请手动删除）")
    print("    ℹ️  如需恢复鼠标快捷键，请用 [1] 重新添加")


def interactive_menu():
    detector = KeyDetector()
    shortcuts = read_current_shortcuts()

    while True:
        print_status(shortcuts)

        print("操作选项：")
        print("  [1] 添加 pynput 键盘快捷键")
        print("  [2] 删除 pynput 快捷键")

        if platform.system() == "Darwin" and hammerspoon_available():
            hs_cfg = read_hammerspoon_config()
            if hs_cfg and read_udp_control():
                print("  [3] 重新配置 Hammerspoon 鼠标侧键")
                print("  [4] 移除 Hammerspoon 配置（切回纯 pynput）")
            else:
                print("  [3] 配置 Hammerspoon 鼠标侧键触发（推荐 macOS）")
        elif platform.system() == "Darwin":
            print("  [3] 安装 Hammerspoon 后可配置鼠标侧键")

        print("  [5] 保存并退出")
        print("  [q] 直接退出（不保存）")
        print()

        choice = input("请选择: ").strip().lower()

        if choice == "1":
            print()
            print(">>> 请按下你想配置的按键（支持键盘和鼠标）...")
            print("    按 Ctrl+C 取消")
            key, key_type = detector.detect()

            if key is None:
                print("    未检测到按键")
                continue

            print(f"\n    检测到: key='{key}', type='{key_type}'")

            if key_type == "mouse" and key in ("unknown", "middle"):
                print()
                if key == "unknown":
                    print("    ⚠️  注意：鼠标按钮被识别为 'unknown'")
                    print("        这在 macOS 上很常见，意味着 pynput 无法区分具体是哪个侧键。")
                else:
                    print("    ⚠️  注意：鼠标按钮被识别为 'middle'（中键）")
                    print("        在 macOS 上，pynput 经常把侧键也误识别为 middle，")
                    print("        导致侧键和中键无法区分！")
                print("        强烈建议改用键盘键（如 f13/f14），")
                print("        或使用 [3] Hammerspoon 方案绑定鼠标侧键。")
                print()
                use_anyway = input("    仍要继续添加吗？(y/N): ").strip().lower()
                if use_anyway != "y":
                    continue
                key = "x2"
                print(f"    已映射为 '{key}'")

            hold_mode = input("    是否长按模式？(按住录音，松开停止) [Y/n]: ").strip().lower()
            hold_mode = hold_mode != "n"

            suppress = input("    是否阻塞按键？(不让其他程序收到) [y/N]: ").strip().lower()
            suppress = suppress == "y"

            new_sc = {
                "key": key,
                "type": key_type,
                "suppress": suppress,
                "hold_mode": hold_mode,
                "enabled": True,
            }

            if key_type == "mouse":
                new_sc["mouse_button"] = key if key in ("x1", "x2") else "x2"

            shortcuts.append(new_sc)
            print(f"\n    ✅ 已添加: {new_sc}")

        elif choice == "2":
            kb_shortcuts = [s for s in shortcuts if s.get("type") == "keyboard"]
            if not kb_shortcuts:
                print("    当前没有可删除的键盘快捷键")
                continue

            print("    可删除的键盘快捷键：")
            for i, sc in enumerate(kb_shortcuts, 1):
                print(f"      {i}. [{sc.get('key', '?')}]")
            idx = input("    输入要删除的序号: ").strip()
            try:
                idx = int(idx) - 1
                if 0 <= idx < len(kb_shortcuts):
                    target = kb_shortcuts[idx]
                    shortcuts.remove(target)
                    print(f"    ✅ 已删除: {target}")
                else:
                    print("    ❌ 无效的序号")
            except ValueError:
                print("    ❌ 请输入数字")

        elif choice == "3":
            if platform.system() == "Darwin":
                configure_hammerspoon()
                shortcuts = read_current_shortcuts()  # 刷新（可能有鼠标键被禁用）
            else:
                print("    此功能仅适用于 macOS")

        elif choice == "4":
            remove_hammerspoon()
            shortcuts = read_current_shortcuts()

        elif choice == "5":
            ok1 = write_shortcuts(shortcuts)
            ok2 = True  # udp_control 已在操作过程中写入
            if ok1 and ok2:
                print("\n✅ 配置已保存到 config_client.py")
                print("   请重新启动 CapsWriter 客户端以生效。")
                if platform.system() == "Darwin" and read_udp_control():
                    print("   并请 Reload Hammerspoon 配置（菜单栏图标 → Reload Config）。")
            else:
                print("\n❌ 保存失败")
            break

        elif choice == "q":
            print("   已退出，未保存修改")
            break
        else:
            print("   无效选项")


def main():
    print_banner()
    print_macos_warning()

    if not CONFIG_PATH.exists():
        print(f"❌ 未找到配置文件: {CONFIG_PATH}")
        sys.exit(1)

    interactive_menu()


if __name__ == "__main__":
    main()
