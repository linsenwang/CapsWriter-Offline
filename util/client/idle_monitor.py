# coding: utf-8
"""
空闲监控模块

在后台线程中定期检查客户端的活动时间，
如果超过配置的空闲超时时间，则关闭音频流以释放麦克风权限。

客户端进程保持在后台运行，保留 WebSocket、热词、LLM 等状态，
需要使用时（收到 START 命令）会自动重新打开音频流。
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from config_client import ClientConfig as Config
from util.common.lifecycle import lifecycle

if TYPE_CHECKING:
    from util.client.state import ClientState

import logging
logger = logging.getLogger('client.idle')


class IdleMonitor:
    """
    空闲监控器

    定期检查客户端的最后活动时间，超时则关闭音频流释放麦克风。
    """

    def __init__(self, state: 'ClientState', check_interval: int = None):
        """
        初始化空闲监控器

        Args:
            state: 客户端状态实例
            check_interval: 检查间隔（秒），默认使用 Config.idle_check_interval
        """
        self.state = state
        self.check_interval = check_interval or Config.idle_check_interval or 5
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """启动空闲监控"""
        if not Config.idle_exit_enabled or Config.idle_timeout <= 0:
            logger.info("空闲释放麦克风已禁用")
            return

        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="IdleMonitor")
        self._thread.start()
        logger.info(f"空闲监控已启动: {Config.idle_timeout}秒无操作将自动释放麦克风 (检查间隔: {self.check_interval}秒)")

    def stop(self) -> None:
        """停止空闲监控"""
        self._running = False
        logger.debug("空闲监控已停止")

    def _loop(self) -> None:
        """监控循环"""
        # 使用实例化时的检查间隔
        interval = self.check_interval
        while self._running:
            time.sleep(interval)

            if not self._running or lifecycle.is_shutting_down:
                break

            if not Config.idle_exit_enabled or Config.idle_timeout <= 0:
                continue

            # 如果音频流已经关闭，说明麦克风已释放，不需要再检查
            if self.state.stream is None:
                continue

            # 如果正在录音中，不要释放麦克风（避免长录音被中断）
            if self.state.recording:
                continue

            elapsed = time.time() - self.state.last_activity_time
            remaining = Config.idle_timeout - elapsed

            if remaining <= 60 and remaining > 0:
                # 提前 1 分钟提醒
                logger.info(f"即将释放麦克风: 还剩 {remaining:.0f} 秒")

            if elapsed > Config.idle_timeout:
                logger.info(f"空闲超时: {elapsed:.0f}秒未使用，释放麦克风...")

                # 关闭音频流释放麦克风
                if self.state.stream_manager:
                    self.state.stream_manager.close()
                    logger.info("麦克风已释放（空闲超时），客户端仍在后台运行")

                # 继续监控，等待下次使用时重新打开
