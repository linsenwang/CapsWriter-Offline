# coding: utf-8
"""
文本输出模块

提供 TextOutput 类用于将识别结果输出到当前窗口。
"""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import time
from typing import Optional
import re

import pyclip
from pynput import keyboard as pynput_keyboard

from config_client import ClientConfig as Config, BASE_DIR
from . import logger

# 输入法切换工具路径
_SWITCH_INPUT_TOOL = os.path.join(BASE_DIR, 'util', 'tools', 'switch_input')
# 英文输入法 ID
_ENGLISH_INPUT_SOURCE = 'com.apple.keylayout.ABC'
# 切换到英文输入法后，等待其真正生效的延迟（TIS 切换是异步应用到前台应用的）
SWITCH_SETTLE_DELAY = 0.15
# 验证输入法切换是否生效的最大轮询次数
_SWITCH_MAX_VERIFY_TRIES = 10



class TextOutput:
    """
    文本输出器
    
    提供文本输出功能，支持模拟打字和粘贴两种方式。
    """
    
    def __init__(self):
        self._previous_input_source = None
        self._switched = False
        self._tool_available = self._check_tool_available()
    
    @staticmethod
    def strip_punc(text: str) -> str:
        """
        消除末尾最后一个标点
        
        Args:
            text: 原始文本
            
        Returns:
            去除末尾标点后的文本
        """
        if not text or not Config.trash_punc:
            return text
        clean_text = re.sub(f"(?<=.)[{Config.trash_punc}]$", "", text)
        return clean_text

    @staticmethod
    def sanitize_output(text: str) -> str:
        """
        把换行/回车替换为空格。

        模拟打字时 `\\n` 会被 pynput 当成回车键发出，可能触发聊天窗口发送；
        粘贴时也不希望把多行文本原样带进去。
        """
        if not text:
            return text
        text = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
        return re.sub(r'[ \t]+', ' ', text).strip()

    @staticmethod
    def has_english(text: str) -> bool:
        """
        检测文本中是否包含英文单词（含空格分隔的英文句子，或混杂在中文中的英文单词）。
        中文输入法下模拟打字输出英文+空格会导致空格触发选词，
        因此无法确保英文输入法时，含英文的文本需要回退到粘贴模式。
        """
        return bool(re.search(r'[A-Za-z]{2,}', text))

    async def output(self, text: str, paste: Optional[bool] = None) -> None:
        """
        输出识别结果
        
        根据配置选择使用模拟打字或粘贴方式输出文本。
        
        Args:
            text: 要输出的文本
            paste: 是否使用粘贴方式（None 表示使用配置值）
        """
        if not text:
            return

        text = self.sanitize_output(text)

        # 确定输出方式
        if paste is None:
            paste = Config.paste
        
        # 自动检测英文文本，若未开启输入法切换则回退到粘贴模式
        if not paste and self.has_english(text) and not Config.switch_input_method:
            logger.debug("检测到英文文本，自动使用粘贴模式避免输入法干扰")
            paste = True
        
        if paste:
            await self._paste_text(text)
            return
        
        # 打字模式：先切换到英文输入法，再打字，最后恢复
        switched = False
        if Config.switch_input_method:
            switched = self.switch_to_english()
            if switched:
                # 等待输入法切换真正生效，避免开头字符被中文输入法拦截
                await asyncio.sleep(SWITCH_SETTLE_DELAY)
            elif self.has_english(text):
                # 切换失败且文本含英文：回退到粘贴模式，避免英文被中文输入法吞掉
                logger.warning("切换到英文输入法失败且文本含英文，回退到粘贴模式")
                await self._paste_text(text)
                return
        try:
            self._type_text(text)
            # 打字完成后等待一小段时间，确保系统事件队列中的按键事件被处理完
            # 再恢复输入法，避免恢复事件追上打字事件导致末尾字符被中文输入法拦截
            if switched:
                await asyncio.sleep(min(1.0, 0.5 + len(text) * 0.01))
        finally:
            if switched:
                self.restore_input()
    
    async def _paste_text(self, text: str) -> None:
        """
        通过粘贴方式输出文本
        
        Args:
            text: 要粘贴的文本
        """
        text = self.sanitize_output(text)
        logger.debug(f"使用粘贴方式输出文本，长度: {len(text)}")
        
        # 保存剪贴板
        try:
            temp = pyclip.paste().decode('utf-8')
        except Exception:
            temp = ''
        
        # 复制结果
        pyclip.copy(text)
        
        # 粘贴结果（使用 pynput 模拟 Ctrl+V / Cmd+V）
        controller = pynput_keyboard.Controller()
        if platform.system() == 'Darwin':
            # macOS: Command+V
            with controller.pressed(pynput_keyboard.Key.cmd):
                controller.tap('v')
        else:
            # Windows/Linux: Ctrl+V
            with controller.pressed(pynput_keyboard.Key.ctrl):
                controller.tap('v')
        
        logger.debug("已发送粘贴命令 (Ctrl+V / Cmd+V)")
        
        # 还原剪贴板
        if Config.restore_clip:
            await asyncio.sleep(0.1)
            pyclip.copy(temp)
            logger.debug("剪贴板已恢复")
    
    def _check_tool_available(self) -> bool:
        """检查输入法切换工具是否可用"""
        if platform.system() != 'Darwin':
            return False
        return os.path.isfile(_SWITCH_INPUT_TOOL) and os.access(_SWITCH_INPUT_TOOL, os.X_OK)

    def _get_current_input_source(self) -> Optional[str]:
        """获取当前输入法 ID"""
        try:
            result = subprocess.run(
                [_SWITCH_INPUT_TOOL, 'current'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                # 输出格式: com.apple.keylayout.ABC (ABC)
                line = result.stdout.strip()
                if ' ' in line:
                    return line.split(' ')[0]
                return line
        except Exception as e:
            logger.warning(f"获取当前输入法失败: {e}")
        return None

    def _select_input_source(self, source_id: str) -> bool:
        """切换到指定输入法"""
        try:
            result = subprocess.run(
                [_SWITCH_INPUT_TOOL, 'select', source_id],
                capture_output=True, text=True, timeout=2
            )
            # 诊断输出（会被 pm2-out.log 捕获）
            print(f"[SWITCH_INPUT] select {source_id} -> rc={result.returncode} stdout={result.stdout.strip()} stderr={result.stderr.strip()}", flush=True)
            return result.returncode == 0
        except Exception as e:
            print(f"[SWITCH_INPUT] exception: {e}", flush=True)
            logger.warning(f"切换输入法失败: {e}")
            return False

    def switch_to_english(self) -> bool:
        """
        切换到英文输入法（打字前调用）
        
        使用 Carbon TIS API 精确切换到英文 ABC 输入法，并验证切换是否真正生效
        （TIS 切换是异步应用到前台应用的）。

        Returns:
            True: 当前已处于英文输入法（原本就是，或切换成功）
            False: 切换失败，当前可能仍停留在原输入法
        """
        logger.info(f"准备切换到英文输入法，工具可用: {self._tool_available}")
        # 重置切换状态，避免上一次残留状态干扰本次切换/恢复
        self._switched = False
        self._previous_input_source = None
        
        if not self._tool_available:
            # 回退到 Ctrl+Space 模拟
            self._switch_to_english_fallback()
            self._switched = True
            return True
        
        # 记录当前输入法
        self._previous_input_source = self._get_current_input_source()
        logger.info(f"当前输入法: {self._previous_input_source}")
        
        # 如果当前已经是英文，不需要切换
        if self._previous_input_source == _ENGLISH_INPUT_SOURCE:
            logger.info("当前已经是英文输入法，无需切换")
            return True
        
        if not self._select_input_source(_ENGLISH_INPUT_SOURCE):
            logger.warning("切换到英文输入法失败")
            return False
        
        # 验证切换是否真正生效（TIS 切换异步生效，轮询当前输入法确认）
        for _ in range(_SWITCH_MAX_VERIFY_TRIES):
            if self._get_current_input_source() == _ENGLISH_INPUT_SOURCE:
                self._switched = True
                logger.info("已切换到英文输入法 (ABC)")
                return True
            time.sleep(0.03)
        
        logger.warning("切换到英文输入法未生效，可能仍停留在原输入法")
        return False

    def restore_input(self) -> None:
        """
        恢复之前的输入法（打字完成后调用）
        
        使用 Carbon TIS API 精确恢复到之前的输入法。
        """
        logger.info(f"准备恢复输入法，工具可用: {self._tool_available}")
        
        # 只有真正发生了切换才恢复
        if not self._switched:
            logger.info("本次未发生输入法切换，无需恢复")
            return
        
        if not self._tool_available:
            self._switch_back_input_fallback()
            self._switched = False
            return
        
        if not self._previous_input_source:
            logger.info("没有记录的输入法需要恢复")
            self._switched = False
            return
        
        # 如果之前就是英文，不需要恢复
        if self._previous_input_source == _ENGLISH_INPUT_SOURCE:
            logger.info("之前就是英文输入法，无需恢复")
            self._previous_input_source = None
            self._switched = False
            return
        
        if self._select_input_source(self._previous_input_source):
            logger.info(f"已恢复输入法: {self._previous_input_source}")
        else:
            logger.warning(f"恢复输入法失败: {self._previous_input_source}")
        
        self._previous_input_source = None
        self._switched = False

    def _switch_to_english_fallback(self) -> None:
        """回退方案：模拟 Ctrl+Space 切换输入法"""
        if platform.system() != 'Darwin':
            return
        try:
            controller = pynput_keyboard.Controller()
            with controller.pressed(pynput_keyboard.Key.ctrl):
                controller.tap(pynput_keyboard.Key.space)
            logger.debug("已切换到英文输入法 (Ctrl+Space 回退)")
        except Exception as e:
            logger.warning(f"切换输入法失败: {e}")

    def _switch_back_input_fallback(self) -> None:
        """回退方案：模拟 Ctrl+Space 恢复输入法"""
        if platform.system() != 'Darwin':
            return
        try:
            controller = pynput_keyboard.Controller()
            with controller.pressed(pynput_keyboard.Key.ctrl):
                controller.tap(pynput_keyboard.Key.space)
            logger.debug("已恢复输入法 (Ctrl+Space 回退)")
        except Exception as e:
            logger.warning(f"恢复输入法失败: {e}")

    def _type_text(self, text: str) -> None:
        """
        通过模拟打字方式输出文本

        优先使用 keyboard 库（Windows），
        macOS/Linux 使用 pynput.keyboard.Controller.type()，
        避免与中文输入法冲突。

        Args:
            text: 要输出的文本
        """
        text = self.sanitize_output(text)
        logger.debug(f"使用打字方式输出文本，长度: {len(text)}")
        
        if platform.system() == 'Windows':
            # Windows: 使用 keyboard 库（效果更好）
            try:
                import keyboard
                keyboard.write(text)
                return
            except Exception as e:
                logger.warning(f"keyboard.write 失败，回退到 pynput: {e}")
        
        # macOS / Linux / 回退: 使用 pynput
        try:
            controller = pynput_keyboard.Controller()
            controller.type(text)
        except Exception as e:
            logger.error(f"pynput 打字失败: {e}")
