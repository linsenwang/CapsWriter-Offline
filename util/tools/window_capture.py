# coding: utf-8
"""
当前聚焦窗口截图

优先读取 Hammerspoon 在录音结束时写入的截图（时机和屏幕录制权限最可靠），
没有可用截图时回退到 Python 直接抓取前台窗口（仅 macOS）。

截图只保留在内存中返回 base64，Hammerspoon 的临时文件读取后即删除。
"""

from __future__ import annotations

import base64
import io
import json
import platform
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from util import get_logger

logger = get_logger('client')

# 与 Hammerspoon 约定好的缓存目录
CACHE_DIR = Path.home() / 'Library' / 'Caches' / 'CapsWriter'
HANDOFF_META = CACHE_DIR / 'last_shot.json'

# 截图超过这个年龄就认为不是本次录音的，避免复用到上一次的图。
# 截图在 START 时抓，长录音可能持续几分钟，所以放宽到 5 分钟。
HANDOFF_MAX_AGE = 300.0

# 过小的图（窗口最小化、空白）直接丢弃
MIN_WIDTH = 80
MIN_HEIGHT = 80

# 截图读取/编码的串行锁，避免预取线程和主线程同时消费 last_shot 文件
_capture_lock = threading.Lock()

# 预取缓存：{(timestamp, result)}，以及正在跑的预取线程
_prefetch_lock = threading.Lock()
_prefetch_thread: Optional[threading.Thread] = None
_prefetched: Optional[tuple] = None


def _capture_focused_window(
    max_edge: int = 1024,
    wait_for_handoff: float = 0.3,
) -> Optional[Dict[str, object]]:
    """获取当前聚焦窗口截图。

    Args:
        max_edge: 长边最大像素，超过则等比缩小（0 表示不缩小）。
        wait_for_handoff: 等待 Hammerspoon 写入截图的最长秒数。语音识别通常
            比截图慢，这里只处理极端情况。

    Returns:
        成功时返回字典：
            image_b64: PNG 的 base64（不含 data URI 前缀）
            mime: 图片 MIME 类型
            app: 窗口所属应用名
            title: 窗口标题
            source: 'hammerspoon' 或 'live'
        失败返回 None。
    """
    if platform.system() != 'Darwin':
        logger.debug("当前平台不支持聚焦窗口截图，跳过")
        return None

    deadline = time.time() + max(0.0, wait_for_handoff)
    while True:
        result = _read_handoff(max_edge)
        if result:
            return result
        if time.time() >= deadline:
            break
        time.sleep(0.05)

    return _capture_live(max_edge)


def capture_focused_window(
    max_edge: int = 1024,
    wait_for_handoff: float = 0.3,
) -> Optional[Dict[str, object]]:
    """获取当前聚焦窗口截图（串行化，避免预取线程和主线程竞争）。"""
    with _capture_lock:
        return _capture_focused_window(max_edge, wait_for_handoff)


def _prefetch_worker(max_edge: int) -> None:
    global _prefetched
    result = capture_focused_window(max_edge=max_edge, wait_for_handoff=1.0)
    with _prefetch_lock:
        _prefetched = (time.time(), result)


def start_prefetch(max_edge: int = 1024) -> None:
    """在录音结束时提前读取/缩放截图。

    这段编码耗时（约 0.1s）会与 ASR 处理重叠，不再等 LLM 请求时才做。
    """
    global _prefetch_thread
    with _prefetch_lock:
        if _prefetch_thread and _prefetch_thread.is_alive():
            # 上一次预取还没结束，先让它跑完；新的 STOP 会写新的 handoff
            return
        _prefetch_thread = threading.Thread(
            target=_prefetch_worker,
            args=(max_edge,),
            daemon=True,
            name='ScreenshotPrefetch',
        )
        _prefetch_thread.start()


def take_prefetched(
    max_edge: int = 1024,
    wait: float = 0.3,
    max_age: float = 30.0,
) -> Optional[Dict[str, object]]:
    """取出预取结果；没有、失败或过期时返回 None。"""
    global _prefetched
    with _prefetch_lock:
        thread = _prefetch_thread
    if thread and thread.is_alive():
        thread.join(timeout=wait)

    with _prefetch_lock:
        item = _prefetched
        _prefetched = None

    if not item:
        return None

    timestamp, result = item
    if not result or time.time() - timestamp > max_age:
        return None

    width = result.get('width') or 0
    height = result.get('height') or 0
    if max_edge and max(width, height) > max_edge:
        logger.debug(
            f"预取截图长边 {max(width, height)} > 请求的 {max_edge}，继续使用预取图"
        )
    return result


# ======================================================================
# Hammerspoon 截图交接
# ======================================================================

def _read_handoff(max_edge: int) -> Optional[Dict[str, object]]:
    """读取 Hammerspoon 写入的截图和元数据。"""
    try:
        meta = json.loads(HANDOFF_META.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None

    try:
        timestamp = float(meta.get('ts') or 0)
    except (TypeError, ValueError):
        timestamp = 0.0

    if time.time() - timestamp > HANDOFF_MAX_AGE:
        _remove_handoff()
        return None

    try:
        path = Path(meta.get('path') or '').resolve()
        path.relative_to(CACHE_DIR.resolve())
    except (OSError, ValueError):
        _remove_handoff()
        return None

    result = _encode_image(path, max_edge)
    if not result:
        _remove_handoff()
        return None

    image_b64, width, height = result
    app = str(meta.get('app') or '')
    title = str(meta.get('title') or '')
    logger.info(
        f"已读取 Hammerspoon 截图: {app} - {title} "
        f"({width}x{height}, {len(image_b64) // 1024}KB base64)"
    )
    _remove_handoff()
    return {
        'image_b64': image_b64,
        'mime': 'image/png',
        'app': app,
        'title': title,
        'source': 'hammerspoon',
        'width': width,
        'height': height,
    }


def _remove_handoff() -> None:
    """删除本次截图文件，避免被下一次处理误用。"""
    try:
        meta = json.loads(HANDOFF_META.read_text(encoding='utf-8'))
        path = Path(meta.get('path') or '').resolve()
        path.relative_to(CACHE_DIR.resolve())
        if path.is_file():
            path.unlink()
    except (OSError, ValueError):
        pass

    try:
        HANDOFF_META.unlink()
    except OSError:
        pass


# ======================================================================
# Python 直接抓取（回退方案）
# ======================================================================

def _capture_live(max_edge: int) -> Optional[Dict[str, object]]:
    """通过 Quartz + screencapture 抓取最前面的普通窗口。"""
    try:
        import Quartz
    except ImportError:
        logger.debug("未安装 pyobjc/Quartz，无法直接抓取窗口")
        return None

    try:
        options = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []

        # CGWindowList 按前后顺序返回，第一个 layer==0 的窗口就是最前面的普通窗口
        target = None
        for window in windows:
            if window.get('kCGWindowLayer', 0) != 0:
                continue
            bounds = window.get('kCGWindowBounds') or {}
            if bounds.get('Width', 0) < MIN_WIDTH or bounds.get('Height', 0) < MIN_HEIGHT:
                continue
            if not window.get('kCGWindowNumber'):
                continue
            target = window
            break

        if target is None:
            logger.debug("没有找到可截图的普通窗口，跳过截图")
            return None

        window_id = target['kCGWindowNumber']
        app_name = target.get('kCGWindowOwnerName') or ''
        title = target.get('kCGWindowName') or ''

        with tempfile.NamedTemporaryFile(
            suffix='.png', prefix='capswriter-shot-', delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            subprocess.run(
                ['/usr/sbin/screencapture', '-x', '-o', '-l', str(window_id), str(tmp_path)],
                check=False,
                timeout=10,
            )
            result = _encode_image(tmp_path, max_edge)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

        if not result:
            logger.warning(
                "聚焦窗口截图失败或为空，请确认客户端已获得屏幕录制权限"
            )
            return None

        image_b64, width, height = result
        logger.info(
            f"已抓取聚焦窗口截图: {app_name} - {title} "
            f"({width}x{height}, {len(image_b64) // 1024}KB base64)"
        )
        return {
            'image_b64': image_b64,
            'mime': 'image/png',
            'app': app_name,
            'title': title,
            'source': 'live',
            'width': width,
            'height': height,
        }

    except Exception as e:
        logger.warning(f"抓取聚焦窗口截图失败: {e}")
        return None


# ======================================================================
# 图片处理
# ======================================================================

def _encode_image(path: Path, max_edge: int) -> Optional[tuple]:
    """读取 PNG，检查是否全黑/空白，按长边缩小后返回 (base64, width, height)。"""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("未安装 Pillow，无法处理截图")
        return None

    try:
        if not path.is_file() or path.stat().st_size < 1024:
            return None

        with Image.open(path) as image:
            image = image.convert('RGB')
            width, height = image.size
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                return None

            # 屏幕录制权限缺失时 screencapture 会产出全黑图
            gray_min, gray_max = image.convert('L').getextrema()
            if gray_max <= 4:
                logger.warning("截图全黑，可能缺少屏幕录制权限")
                return None

            if max_edge and max(width, height) > max_edge:
                image.thumbnail((max_edge, max_edge), Image.LANCZOS)
                width, height = image.size

            buffer = io.BytesIO()
            # 不用 optimize=True：实测只省几 KB，却多花约 50ms CPU
            image.save(buffer, format='PNG')
            return (
                base64.b64encode(buffer.getvalue()).decode('ascii'),
                width,
                height,
            )

    except Exception as e:
        logger.warning(f"读取或压缩截图失败: {e}")
        return None
