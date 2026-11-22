"""
LLM Typing 输出模式

直接打字输出，根据 paste 参数或 Config.paste 选择：
- paste=True: 等模型输出完成后，清理思考过程再一次性粘贴
- paste=False: 等模型输出完成后，清理思考过程再统一打字
  （不再边生成边打，避免把“根据规则……”这类分析过程打进输入框）
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
from util.llm.llm_text_cleaner import clean_llm_output
from . import logger


# 复用 TextOutput 的输入法切换逻辑（打字前切到英文 ABC，完成后恢复）
_text_output = TextOutput()


def _has_english(text: str) -> bool:
    """判断文本中是否包含英文单词（连续 ASCII 字母）"""
    return bool(re.search(r'[A-Za-z]{2,}', text or ''))


def _type_text(content: str) -> None:
    """跨平台模拟打字"""
    content = TextOutput.sanitize_output(content)
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

    final_text = TextOutput.strip_punc(clean_llm_output(polished_text or content))
    if not final_text:
        final_text = TextOutput.strip_punc(content)
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
    """收集完整输出，清理掉思考过程后再统一打字。

    不再边生成边打字：模型偶尔会把“根据规则……因此……”的分析写进
    content，实时打字会把这些过程一起打进输入框。先缓冲、清理，
    再一次性输出，能保证只打最终文本。
    """
    chunks = []

    def collect_chunk(chunk: str):
        if chunk:
            chunks.append(chunk)

    polished_text, token_count, gen_time = await to_thread(
        handler.process, role_config, content, matched_hotwords, collect_chunk, should_stop
    )

    # 用户按 ESC 中断时，不把半截思考过程打出去
    if should_stop():
        return ("", 0, 0.0)

    raw_text = polished_text or ''.join(chunks) or content
    final_text = TextOutput.strip_punc(clean_llm_output(raw_text))
    if not final_text:
        final_text = TextOutput.strip_punc(content)

    logger.debug(f"output_text: type '{final_text}'")
    _type_text(final_text)
    return (final_text, token_count, gen_time)


async def output_text(text: str, paste: bool = None):
    """输出文本（根据 paste 或 Config.paste 选择方式）"""
    text = TextOutput.sanitize_output(text)
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
