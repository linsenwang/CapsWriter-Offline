# coding: utf-8
"""
语音命令模块

提供 VoiceCommandManager 类，用于根据识别结果匹配并执行预设命令。

典型用法：
    在 config_client.py 中配置 voice_commands，当识别结果匹配到对应模式时，
    执行打开网页/应用等操作，而不是输出文本。

配置示例：
    voice_commands = [
        {'pattern': r'打开\s*It\s*之家', 'action': 'open', 'target': 'https://www.ithome.com'},
        {'pattern': r'打开\s*GitHub',   'action': 'open', 'target': 'https://github.com'},
        {'pattern': r'打开\s*微信',     'action': 'open', 'target': '/Applications/WeChat.app'},
    ]
"""

from __future__ import annotations

import platform
import re
import subprocess
import webbrowser
from typing import List, Optional

from . import logger



class VoiceCommand:
    """单个语音命令"""

    def __init__(self, config: dict):
        """
        初始化语音命令

        Args:
            config: 配置字典，包含 pattern、action、target 等字段
        """
        self.raw_pattern = config.get('pattern', '')
        self.action = config.get('action', '')
        self.target = config.get('target', '')
        self.enabled = config.get('enabled', True)

        # 编译正则表达式
        self._regex: Optional[re.Pattern] = None
        if self.raw_pattern:
            try:
                self._regex = re.compile(self.raw_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning(f"语音命令正则编译失败: {self.raw_pattern} -> {e}")

    def match(self, text: str) -> bool:
        """
        检查文本是否匹配此命令

        Args:
            text: 识别结果文本

        Returns:
            是否匹配
        """
        if not self.enabled or self._regex is None:
            return False
        return self._regex.search(text) is not None



class VoiceCommandManager:
    """语音命令管理器"""

    def __init__(self, commands: Optional[List[dict]] = None):
        """
        初始化语音命令管理器

        Args:
            commands: 配置命令列表
        """
        self.commands: List[VoiceCommand] = []
        if commands:
            for cfg in commands:
                cmd = VoiceCommand(cfg)
                if cmd._regex is not None:
                    self.commands.append(cmd)
                    logger.debug(f"注册语音命令: pattern={cmd.raw_pattern}, action={cmd.action}, target={cmd.target}")
                else:
                    logger.warning(f"跳过无效的语音命令配置: {cfg}")

        if self.commands:
            logger.info(f"已加载 {len(self.commands)} 条语音命令")
        else:
            logger.debug("未配置语音命令")

    def match(self, text: str) -> Optional[VoiceCommand]:
        """
        在文本中查找匹配的第一个语音命令

        Args:
            text: 识别结果文本

        Returns:
            匹配的 VoiceCommand，未匹配则返回 None
        """
        for cmd in self.commands:
            if cmd.match(text):
                return cmd
        return None

    def execute(self, cmd: VoiceCommand) -> bool:
        """
        执行语音命令

        Args:
            cmd: 要执行的命令

        Returns:
            是否执行成功
        """
        if cmd.action == 'open':
            return self._do_open(cmd.target)
        else:
            logger.warning(f"未知的语音命令 action: {cmd.action}")
            return False

    def _do_open(self, target: str) -> bool:
        """
        执行打开操作

        根据 target 类型自动判断：
        - 以 http:// 或 https:// 开头：使用浏览器打开
        - 以 / 开头（macOS/Linux）或是 .app 结尾：使用 open 命令
        - 其他：尝试使用系统默认方式打开

        Args:
            target: 要打开的目标（网址或路径）

        Returns:
            是否执行成功
        """
        if not target:
            logger.warning("打开目标为空")
            return False

        try:
            # 网址：使用 webbrowser
            if target.startswith(('http://', 'https://', 'file://')):
                logger.info(f"使用浏览器打开: {target}")
                webbrowser.open(target, new=2)  # new=2 表示在新标签页打开
                return True

            system = platform.system()

            # macOS
            if system == 'Darwin':
                logger.info(f"使用 open 打开: {target}")
                subprocess.run(['open', target], check=True)
                return True

            # Windows
            if system == 'Windows':
                logger.info(f"使用 start 打开: {target}")
                subprocess.run(['cmd', '/c', 'start', '', target], check=True)
                return True

            # Linux
            logger.info(f"使用 xdg-open 打开: {target}")
            subprocess.run(['xdg-open', target], check=True)
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"打开失败: {target} -> {e}")
            return False
        except Exception as e:
            logger.error(f"打开时发生异常: {target} -> {e}")
            return False
