# coding: utf-8
"""
文本输出模块

提供 TextOutput 类用于将识别结果输出到当前窗口。
"""

from __future__ import annotations

import asyncio
import platform
from typing import Optional
import re

import pyclip
from pynput import keyboard as pynput_keyboard

from config_client import ClientConfig as Config
from . import logger



class TextOutput:
    """
    文本输出器
    
    提供文本输出功能，支持模拟打字和粘贴两种方式。
    """
    
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
    def _is_english_text(text: str) -> bool:
        """
        检测文本是否为英文内容（含空格分隔的单词）。
        中文输入法下模拟打字输出英文+空格会导致空格触发选词，
        因此需要自动切换到粘贴模式。
        """
        alpha_chars = sum(1 for c in text if c.isalpha() and c.isascii())
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        has_space = ' ' in text
        return has_space and alpha_chars > 0 and alpha_chars > chinese_chars * 2

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
        
        # 确定输出方式
        if paste is None:
            paste = Config.paste
        
        # 自动检测英文文本，使用粘贴模式避免中文输入法干扰
        if not paste and self._is_english_text(text):
            logger.debug("检测到英文文本，自动使用粘贴模式避免输入法干扰")
            paste = True
        
        if paste:
            await self._paste_text(text)
        else:
            self._type_text(text)
    
    async def _paste_text(self, text: str) -> None:
        """
        通过粘贴方式输出文本
        
        Args:
            text: 要粘贴的文本
        """
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
    
    def _type_text(self, text: str) -> None:
        """
        通过模拟打字方式输出文本

        优先使用 keyboard 库（Windows），
        macOS/Linux 使用 pynput.keyboard.Controller.type()，
        避免与中文输入法冲突。

        Args:
            text: 要输出的文本
        """
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
