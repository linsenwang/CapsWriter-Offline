# coding: utf-8
"""
交互式快捷键配置工具

用法：
    python configure_shortcuts.py

功能：
    1. 按键测试模式：按任意键/鼠标，查看 pynput 识别到的名称
    2. 生成配置：自动将识别到的按键写入 config_client.py

注意：
    - macOS 上 pynput 对鼠标侧键支持有限，通常只能识别为 "unknown"
    - 如果侧键无法识别，建议在 Karabiner-Elements 中将侧键映射为不常用的键盘键（如 f13-f19）
"""

import ast
import platform
import sys
from pathlib import Path

from pynput import keyboard, mouse

CONFIG_PATH = Path(__file__).parent / "config_client.py"


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
            return False  # 停止监听

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        name = self._button_to_name(button)
        if name:
            self.last_key = name
            self.last_type = "mouse"
            self._stopped = True
            return False  # 停止监听

    @staticmethod
    def _key_to_name(key):
        """将 pynput Key 转换为内部名称"""
        if hasattr(key, 'name') and key.name:
            return key.name
        elif hasattr(key, 'char') and key.char:
            return key.char.lower()
        return str(key)

    @staticmethod
    def _button_to_name(button):
        """将 pynput Button 转换为内部名称"""
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
        """启动监听，等待用户按下一个键"""
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


def print_banner():
    print("=" * 50)
    print("  CapsWriter 快捷键配置工具")
    print("=" * 50)
    print()


def print_macos_warning():
    if platform.system() == "Darwin":
        print("⚠️  macOS 检测提示：")
        print("    pynput 在 macOS 上通常无法区分鼠标侧键（x1/x2），")
        print("    侧键可能被识别为 'unknown'。")
        print("    建议：在 Karabiner-Elements 中将侧键映射为键盘键（如 f13/f14），")
        print("    然后在此工具中按该键盘键进行配置。")
        print()


def read_current_shortcuts():
    """读取 config_client.py 中的当前 shortcuts 配置"""
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


def write_shortcuts(shortcuts):
    """将 shortcuts 写回 config_client.py"""
    content = CONFIG_PATH.read_text(encoding="utf-8")

    # 找到 shortcuts = [...] 的位置并替换
    import re
    pattern = r"(shortcuts\s*=\s*)\[.*?\]"
    new_value = f"shortcuts = {repr(shortcuts)}"

    if re.search(pattern, content, re.DOTALL):
        new_content = re.sub(pattern, new_value, content, count=1, flags=re.DOTALL)
        CONFIG_PATH.write_text(new_content, encoding="utf-8")
        return True
    return False


def interactive_menu():
    detector = KeyDetector()
    shortcuts = read_current_shortcuts()

    while True:
        print()
        print("-" * 40)
        print("当前已配置的快捷键：")
        if shortcuts:
            for i, sc in enumerate(shortcuts, 1):
                enabled = "✅" if sc.get("enabled", True) else "❌"
                print(f"  {i}. [{sc.get('key', '?')}] type={sc.get('type', 'keyboard')}, "
                      f"hold_mode={sc.get('hold_mode', True)}, suppress={sc.get('suppress', False)} {enabled}")
        else:
            print("  （无）")
        print()
        print("操作选项：")
        print("  [1] 测试按键 / 添加新快捷键")
        print("  [2] 删除快捷键")
        print("  [3] 保存并退出")
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

            if key_type == "mouse" and key == "unknown":
                print()
                print("    ⚠️  注意：鼠标按钮被识别为 'unknown'")
                print("        这在 macOS 上很常见，意味着 pynput 无法区分具体是哪个侧键。")
                print("        如果你坚持使用鼠标侧键，目前无法在 macOS 上可靠区分 x1/x2。")
                print("        强烈建议改用键盘键（如 f13/f14）替代。")
                print()
                use_anyway = input("    仍要继续添加吗？(y/N): ").strip().lower()
                if use_anyway != "y":
                    continue
                # 如果用户坚持用 unknown，默认当作 x2
                key = "x2"
                print(f"    已将 unknown 映射为 '{key}'")

            # 询问配置参数
            print()
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

            # 如果是鼠标，添加 mouse_button 字段
            if key_type == "mouse":
                new_sc["mouse_button"] = key if key in ("x1", "x2") else "x2"

            shortcuts.append(new_sc)
            print(f"\n    ✅ 已添加: {new_sc}")

        elif choice == "2":
            if not shortcuts:
                print("    当前没有可删除的快捷键")
                continue
            idx = input("    输入要删除的序号: ").strip()
            try:
                idx = int(idx) - 1
                if 0 <= idx < len(shortcuts):
                    removed = shortcuts.pop(idx)
                    print(f"    ✅ 已删除: {removed}")
                else:
                    print("    ❌ 无效的序号")
            except ValueError:
                print("    ❌ 请输入数字")

        elif choice == "3":
            if write_shortcuts(shortcuts):
                print("\n✅ 配置已保存到 config_client.py")
                print("   请重新启动 CapsWriter 客户端以生效。")
            else:
                print("\n❌ 保存失败，未能找到 shortcuts 配置块")
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
