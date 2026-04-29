import os
from platform import system
import asyncio
import websockets
from config_server import ServerConfig as Config, __version__
from util.server.server_ws_recv import ws_recv
from util.server.server_ws_send import ws_send
from util.tools.empty_working_set import empty_current_working_set
from util.logger import setup_logger
from util.common.lifecycle import lifecycle
from util.server.cleanup import setup_tray, print_banner, cleanup_server_resources, console
from util.server.service import start_recognizer_process
from util.server.ollama_lifecycle import ollama_lifecycle
import logging

BASE_DIR = os.path.dirname(__file__); os.chdir(BASE_DIR)

# 初始化日志系统
logger = setup_logger('server', level=Config.log_level)

# 手动接管 websockets 日志
ws_logger = logging.getLogger('websockets')
ws_logger.setLevel(logging.WARNING) # 仅记录 WARNING 及以上
ws_logger.propagate = False
for handler in logger.handlers:
    ws_logger.addHandler(handler)




async def watchdog():
    """监控识别子进程健康，卡死则自动重启"""
    import time
    from util.server.state import get_state
    from util.server.service import restart_recognizer_process
    
    # 等待模型首次加载完成
    await asyncio.sleep(15)
    
    while True:
        await asyncio.sleep(30)
        
        state = get_state()
        process = state.recognize_process
        if not process:
            continue
        
        # 情况 A：子进程已崩溃
        if not process.is_alive():
            logger.error(f"识别子进程已退出 (exitcode={process.exitcode})，准备重启...")
            try:
                restart_recognizer_process()
            except Exception as e:
                logger.error(f"重启失败: {e}")
            continue
        
        # 情况 B：子进程活着但卡死
        # 只有当「有任务已提交但未完成」时才检查超时，空闲状态不算
        pending = Cosmic.last_task_submit_time - Cosmic.last_result_time
        if pending > 0:
            idle = time.time() - Cosmic.last_result_time
            # 文件转录或长音频可能单次就需要数分钟，阈值必须足够大
            if idle > 600:
                logger.warning(
                    f"识别子进程疑似卡死（有未完成任务已闲置 {idle:.0f} 秒，"
                    f"最后提交={Cosmic.last_task_submit_time:.0f}，最后结果={Cosmic.last_result_time:.0f}），强制重启..."
                )
                try:
                    restart_recognizer_process()
                except Exception as e:
                    logger.error(f"重启失败: {e}")


async def run_websocket_server():
    """运行 WebSocket 服务器"""
    loop = asyncio.get_running_loop()
    
    # 1. 更新生命周期管理器的事件循环
    lifecycle._loop = loop
    # 如果在启动前就已请求退出（例如启动时按了 Ctrl+C），则不再启动服务
    if lifecycle.is_shutting_down:
        logger.info("检测到退出标记，停止启动")
        return

    from util.concurrency.daemon_executor import SimpleDaemonExecutor
    loop.set_default_executor(SimpleDaemonExecutor())

    # 清空物理内存工作集
    # if system() == 'Windows':
    #     empty_current_working_set()

    # 2. 启动服务器
    logger.info(f"WebSocket 服务器正在启动，监听地址: {Config.addr}:{Config.port}")
    async with websockets.serve(ws_recv,
                                Config.addr,
                                Config.port,
                                subprotocols=["binary"],
                                max_size=None):
        
        send_task = asyncio.create_task(ws_send())
        watchdog_task = asyncio.create_task(watchdog())
        
        # 3. 等待退出信号
        # 如果已经处于 shutting down 状态，ensure event is set
        if lifecycle.is_shutting_down:
            lifecycle._shutdown_event.set()

        wait_shutdown_task = asyncio.create_task(lifecycle.wait_for_shutdown())

        done, pending = await asyncio.wait(
            [send_task, watchdog_task, wait_shutdown_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        if wait_shutdown_task in done:
            logger.info("收到退出信号，正在关闭服务...")
        
        # 4. 取消所有相关任务
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        if send_task in done and not send_task.cancelled():
            try:
                await send_task
            except Exception as e:
                logger.error(f"发送任务异常退出: {e}")


def init():
    """初始化并启动服务"""
    # 尽早初始化生命周期以激活信号处理（防手抖）
    lifecycle.initialize(logger=logger, exit_on_signal=False)
    lifecycle.register_on_shutdown(cleanup_server_resources)

    logger.info("=" * 50)
    logger.info("CapsWriter Offline Server 正在启动")
    logger.info(f"版本: {__version__}")
    logger.info(f"日志级别: {Config.log_level}")

    setup_tray()
    print_banner()

    try:
        start_recognizer_process()

        # 启动 Ollama 模型生命周期管理（加载模型并设为常驻）
        if Config.ollama_model:
            ollama_lifecycle.initialize(Config.ollama_model)

        asyncio.run(run_websocket_server())
        # 正常退出后的显式清理
        lifecycle.cleanup()

    except KeyboardInterrupt:
        logger.warning("收到停止信号，正在停止服务...")
        console.print('\n[yellow]正在停止服务...')
        lifecycle.cleanup()
    except OSError as e:
        logger.error(f"OSError 错误: {e}")
        console.print(f'出错了：{e}', style='bright_red'); console.input('...')
        lifecycle.cleanup()
    except Exception as e:
        logger.error(f"未处理的异常: {e}", exc_info=True)
        print(e)
        lifecycle.cleanup()
        raise
     
        
if __name__ == "__main__":
    init()
