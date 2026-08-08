"""
LLM Typing 输出模式

直接打字输出，根据 paste 参数或 Config.paste 选择：
- paste=True: 等流式输出完成后一次性粘贴
- paste=False: 实时流式 write，每个字都打出来
"""
import asyncio
import platform
import re
from pynput import keyboard as pynput_keyboard

from config_client import ClientConfig as Config
from util.tools.asyncio_to_thread import to_thread
from util.client.output.text_output import TextOutput, SWITCH_SETTLE_DELAY
from util.client.clipboard import paste_text
from util.llm.llm_stop_monitor import reset, should_stop
from . import logger


# 复用 TextOutput 的输入法切换逻辑（打字前切到英文 ABC，完成后恢复）
_text_output = TextOutput()


def _has_english(text: str) -> bool:
    """判断文本中是否包含英文单词（连续 ASCII 字母）"""
    return bool(re.search(r'[A-Za-z]{2,}', text or ''))


def _type_text(content: str) -> None:
    """跨平台模拟打字"""
    if platform.system() == 'Windows':
        try:
            import keyboard
            keyboard.write(content)
            return
        except Exception as e:
            logger.warning(f"keyboard.write 失败，回退到 pynput: {e}")
    
    # macOS / Linux / 回退
    try:
        controller = pynput_keyboard.Controller()
        controller.type(content)
    except Exception as e:
        logger.error(f"pynput 打字失败: {e}")


async def handle_typing_mode(text: str, paste: bool = None, matched_hotwords=None, role_config=None, content=None) -> tuple:
    """打字输出模式"""
    from util.llm.llm_handler import get_handler
    from util.llm.llm_error_handler import handle_llm_error

    handler = get_handler()
    # 如果没传，则现场检测一次（兼容性）
    if not role_config or content is None:
        role_config, content = handler.detect_role(text)
    
    if not role_config:
        # 不应发生，但作为防守
        result_text = TextOutput.strip_punc(text)
        await output_text(result_text, paste)
        return (result_text, 0, 0.0)

    reset()  # 重置停止标志

    try:
        if paste:
            return await _process_paste(handler, role_config, content, matched_hotwords)
        else:
            return await _process_streaming(handler, role_config, content, matched_hotwords)

    except Exception as e:
        result_text, _ = handle_llm_error(e, content, role_config.name if role_config else "LLM")
        result_text = TextOutput.strip_punc(result_text)
        await output_text(result_text, paste)
        return (result_text, 0, 0.0)


async def _process_paste(handler, role_config, content, matched_hotwords) -> tuple:
    """处理粘贴模式：获取全文后一次性粘贴"""
    polished_text, token_count, gen_time = await to_thread(
        handler.process, role_config, content, matched_hotwords, None, should_stop
    )
    if should_stop():
        return ("", 0, 0.0)

    final_text = TextOutput.strip_punc(polished_text or content)
    await paste_text(final_text, restore_clipboard=Config.restore_clip)
    return (final_text, token_count, gen_time)


async def _process_streaming(handler, role_config, content, matched_hotwords) -> tuple:
    """处理流式打字模式：边生成边模拟按键打字"""
    # 打字模式：先切换到英文输入法，避免中文输入法干扰英文输出
    switched = False
    if Config.switch_input_method:
        switched = _text_output.switch_to_english()
        if switched:
            # 等待输入法切换真正生效，避免开头字符被中文输入法拦截
            await asyncio.sleep(SWITCH_SETTLE_DELAY)
        elif _has_english(content):
            # 切换失败且内容含英文：回退到粘贴模式，避免英文被中文输入法吞掉
            logger.warning("英文输入法切换失败且内容含英文，回退到粘贴模式")
            return await _process_paste(handler, role_config, content, matched_hotwords)

    try:
        return await _streaming_inner(handler, role_config, content, matched_hotwords)
    finally:
        if switched:
            _text_output.restore_input()


async def _streaming_inner(handler, role_config, content, matched_hotwords) -> tuple:
    """流式打字输出主体逻辑（已在 _process_streaming 中完成输入法切换与恢复）"""
    chunks = []
    pending_buffer = ""

    def stream_write_chunk(chunk: str):
        nonlocal pending_buffer
        if not chunk: return
        chunks.append(chunk)

        full_current = pending_buffer + chunk
        content_to_write = full_current
        trailing = ""
        
        # 从右向左寻找第一个非 trash 字符
        for i in range(len(full_current) - 1, -1, -1):
            char = full_current[i]
            if char == '\n' or char in Config.trash_punc:
                continue
            else:
                content_to_write = full_current[:i+1]
                trailing = full_current[i+1:]
                break
        else:
            content_to_write = ""
            trailing = full_current

        if content_to_write:
            logger.debug(f"output_text: type '{content_to_write}'")
            _type_text(content_to_write)
            pending_buffer = trailing
        else:
            pending_buffer = trailing

    # 执行流式处理
    polished_text, token_count, gen_time = await to_thread(
        handler.process, role_config, content, matched_hotwords, stream_write_chunk, should_stop
    )

    # 阻塞，直到正常结束，或用户按下 ESC
    if should_stop():
        final_text = TextOutput.strip_punc(''.join(chunks) or content)
        return (final_text, 0, 0.0)

    # 如果模型没有任何输出，直接打出原文字
    if not chunks:
        final_text = TextOutput.strip_punc(content)
        logger.debug(f"output_text: type '{final_text}' (降级)")
        _type_text(final_text)
        return (final_text, 0, 0.0)
    
    # 如果 LLM 只输出标点，会被拦截，就要做补偿输出
    full_output = ''.join(chunks).strip()
    if len(full_output) == 1 and full_output in Config.trash_punc:
        _type_text(full_output)
    
    return (TextOutput.strip_punc(polished_text), token_count, gen_time)


async def output_text(text: str, paste: bool = None):
    """输出文本（根据 paste 或 Config.paste 选择方式）"""
    if paste:
        await paste_text(text, restore_clipboard=Config.restore_clip)
        return

    # 打字模式：先切换到英文输入法，避免中文输入法干扰英文输出
    switched = False
    if Config.switch_input_method:
        switched = _text_output.switch_to_english()
        if switched:
            # 等待输入法切换真正生效，避免开头字符被中文输入法拦截
            await asyncio.sleep(SWITCH_SETTLE_DELAY)
        elif _has_english(text):
            # 切换失败且文本含英文：回退到粘贴模式，避免英文被中文输入法吞掉
            logger.warning("英文输入法切换失败且文本含英文，回退到粘贴模式")
            await paste_text(text, restore_clipboard=Config.restore_clip)
            return
    try:
        logger.debug(f"output_text: type '{text}'")
        _type_text(text)
    finally:
        if switched:
            _text_output.restore_input()
