# coding: utf-8
"""
音频流管理模块

提供 AudioStreamManager 类用于管理音频输入流，包括流的创建、
启动、停止和设备检测。
"""

from __future__ import annotations

import sys
import time
import threading
from typing import TYPE_CHECKING, Optional

import numpy as np
import sounddevice as sd

from util.client.state import console, get_state
from . import logger
from util.common.lifecycle import lifecycle

if TYPE_CHECKING:
    from util.client.state import ClientState



class AudioStreamManager:
    """
    音频流管理器
    
    负责管理音频输入流的生命周期，包括：
    - 检测和选择音频设备
    - 创建和启动音频流
    - 处理音频数据回调
    - 流的重启和关闭
    
    Attributes:
        state: 客户端状态实例
        sample_rate: 采样率（默认 48000Hz）
        block_duration: 每个数据块的时长（秒，默认 0.05s）
    """
    
    SAMPLE_RATE = 48000
    BLOCK_DURATION = 0.05  # 50ms
    
    def __init__(self, state: 'ClientState'):
        """
        初始化音频流管理器
        
        Args:
            state: 客户端状态实例
        """
        self.state = state
        self._channels = 1
        self._running = False  # 标志是否应该运行
        self._current_device_index: Optional[int] = None  # 当前使用的设备索引
    
    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags
    ) -> None:
        """
        音频数据回调函数
        
        当音频流接收到新数据时调用，将数据放入异步队列中。
        """
        # 只在录音状态时处理数据
        if not self.state.recording:
            return
        
        import asyncio
        
        # 将数据放入队列
        if self.state.loop and self.state.queue_in:
            asyncio.run_coroutine_threadsafe(
                self.state.queue_in.put({
                    'type': 'data',
                    'time': time.time(),
                    'data': indata.copy(),
                }),
                self.state.loop
            )
    
    def _on_stream_finished(self) -> None:
        """音频流结束回调"""
        if not threading.main_thread().is_alive():
            return
        
        # 只有在应该运行且不是手动停止、且系统未处于关闭状态的情况下才重启
        if self._running and not lifecycle.is_shutting_down:
            logger.info("音频流意外结束，正在尝试重启...")
            self.reopen()
        else:
            logger.debug("音频流已正常结束")
    
    def get_default_device_index(self) -> Optional[int]:
        """获取当前系统默认输入设备索引"""
        try:
            return sd.default.device[0]
        except Exception:
            return None
    
    def _resolve_device(self) -> tuple[Optional[int], str]:
        """
        根据配置解析要使用的设备索引和名称
        
        如果配置了 mic_device_name，优先查找匹配的设备（不区分大小写，部分匹配）。
        找不到时自动回落到系统默认设备。
        
        Returns:
            (设备索引, 设备名称)。索引为 None 表示使用系统默认。
        """
        from config_client import ClientConfig as Config
        
        if Config.mic_device_name:
            try:
                devices = sd.query_devices()
                for i, d in enumerate(devices):
                    if d.get('max_input_channels', 0) > 0:
                        name = d.get('name', '')
                        if Config.mic_device_name.lower() in name.lower():
                            return i, name
            except Exception as e:
                logger.warning(f"查找指定麦克风时出错: {e}")
            logger.warning(f"未找到配置的麦克风 '{Config.mic_device_name}'，将使用系统默认设备")
        
        try:
            device = sd.query_devices(kind='input')
            default_idx = self.get_default_device_index()
            return default_idx, device.get('name', '默认设备')
        except UnicodeDecodeError:
            return None, '未知设备（编码问题）'
        except sd.PortAudioError:
            return None, ''
    
    def is_device_changed(self) -> bool:
        """检测当前应使用的音频输入设备是否已发生变化"""
        if self._current_device_index is None:
            return True
        new_index, _ = self._resolve_device()
        return new_index != self._current_device_index
    
    def open(self) -> Optional[sd.InputStream]:
        """
        打开音频流
        
        Returns:
            创建的音频输入流，如果失败返回 None
        """
        # 解析目标设备（优先使用配置的 mic_device_name，找不到则回落到默认）
        device_index, device_name = self._resolve_device()
        
        if device_name == '':
            console.print("没有找到麦克风设备", end='\n\n', style='bright_red')
            logger.error("未找到麦克风设备")
            input('按回车键退出')
            sys.exit(1)
        
        # 获取设备详情以确定声道数
        try:
            if device_index is not None:
                device_info = sd.query_devices(device_index)
                self._channels = min(2, device_info['max_input_channels'])
            else:
                device_info = sd.query_devices(kind='input')
                self._channels = min(2, device_info['max_input_channels'])
        except Exception:
            self._channels = 1
        
        console.print(
            f'使用音频设备：[italic]{device_name}，声道数：{self._channels}',
            end='\n\n'
        )
        logger.info(f"找到音频设备: {device_name}, 声道数: {self._channels}")
        
        # 创建音频流
        try:
            stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                blocksize=int(self.BLOCK_DURATION * self.SAMPLE_RATE),
                device=device_index,
                dtype="float32",
                channels=self._channels,
                callback=self._audio_callback,
                finished_callback=self._on_stream_finished,
            )
            stream.start()
            
            self.state.stream = stream
            self._running = True
            self._current_device_index = device_index
            logger.debug(
                f"音频流已启动: 采样率={self.SAMPLE_RATE}, "
                f"块大小={int(self.BLOCK_DURATION * self.SAMPLE_RATE)}, "
                f"设备索引={device_index}"
            )
            return stream
            
        except Exception as e:
            logger.error(f"创建音频流失败: {e}", exc_info=True)
            return None
    
    def close(self) -> None:
        """关闭音频流"""
        self._running = False  # 标记为停止
        if self.state.stream is not None:
            try:
                self.state.stream.close()
                logger.debug("音频流已关闭")
            except Exception as e:
                logger.debug(f"关闭音频流时发生错误: {e}")
            finally:
                self.state.stream = None
    
    def reopen(self) -> Optional[sd.InputStream]:
        """
        重新打开音频流
        
        Returns:
            新创建的音频输入流
        """
        logger.info("正在重启音频流...")
        
        # 关闭旧流
        self.close()
        
        # 重载 PortAudio，更新设备列表
        try:
            sd._terminate()
            sd._ffi.dlclose(sd._lib)
            sd._lib = sd._ffi.dlopen(sd._libname)
            sd._initialize()
        except Exception as e:
            logger.warning(f"重载 PortAudio 时发生警告: {e}")
        
        # 等待设备稳定
        time.sleep(0.1)
        
        # 打开新流
        return self.open()
