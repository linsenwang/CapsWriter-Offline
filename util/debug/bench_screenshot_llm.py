# coding: utf-8
"""
截图辅助 LLM 后处理的基准测试

用途：
1. 生成一张模拟代码窗口截图（或使用 --image 指定真实截图）
2. 在多个 screenshot_max_edge 下跑同一段语音文本
3. 统计编码耗时、模型耗时、命中术语数，帮助选择“效果够用且最快”的分辨率

用法（在项目根目录）：
    python -m util.debug.bench_screenshot_llm
    python -m util.debug.bench_screenshot_llm --edges 640,768,896,1024,1280 --runs 2
    python -m util.debug.bench_screenshot_llm --image /path/to/window.png

注意：脚本会直接调用 LLM/default.py 里配置的模型；默认角色需要支持视觉输入。
"""

from __future__ import annotations

import argparse
import base64
import copy
import io
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from util.llm.llm_message_builder import MessageBuilder
from util.llm.llm_role_loader import RoleLoader

# 基准用的语音文本与目标术语
USER_TEXT = (
    '这个项目里 model type 是 fun asr nano，decoder 用的是 sherpa onnx，'
    'provider 是 allama，模型是 qwen 三点五 9b，截图长边是 1024。'
)
TARGETS = ['model_type', 'fun_asr_nano', 'sherpa-onnx', 'qwen3.5:9b', 'ollama']

# 模拟窗口里的内容
CODE_LINES = [
    "model_type = 'fun_asr_nano'",
    "decoder_gguf_path = 'sherpa-onnx-decoder.q5_k.gguf'",
    "provider = 'ollama'",
    "model = 'qwen3.5:9b'",
    "enable_screenshot = True",
    "screenshot_max_edge = 1024",
]
SIDEBAR = [
    'core_server.py',
    'llm_handler.py',
    'window_capture.py',
    'config_client.py',
    'LLM/default.py',
]


def _load_font(size: int):
    """找一个可用的等宽字体，找不到就退回默认字体。"""
    candidates = [
        '/System/Library/Fonts/Menlo.ttc',
        '/System/Library/Fonts/Supplemental/Courier New.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_window_image(path: Path, width: int = 2400, height: int = 1500) -> None:
    """生成一张模拟 VSCode 的窗口截图。"""
    image = Image.new('RGB', (width, height), '#1e1e1e')
    draw = ImageDraw.Draw(image)

    mono = _load_font(34)
    mono_small = _load_font(28)
    title_font = _load_font(42)

    draw.rectangle([0, 0, width, 70], fill='#2d2d2d')
    draw.text((30, 16), 'config_server.py — CapsWriter-Offline', font=title_font, fill='#cccccc')

    draw.rectangle([0, 70, 420, height], fill='#252526')
    y = 110
    for name in SIDEBAR:
        color = '#9cdcfe' if name == 'config_server.py' else '#cccccc'
        draw.text((30, y), name, font=mono_small, fill=color)
        y += 58

    x0, y0 = 480, 120
    for line in CODE_LINES:
        draw.text((x0, y0), line, font=mono, fill='#ce9178')
        y0 += 72

    draw.rectangle([480, 760, width - 40, height - 40], fill='#181818')
    draw.text((510, 790), 'ASR models: Fun-ASR-Nano | Paraformer | SenseVoice',
              font=mono, fill='#d4d4d4')
    draw.text((510, 870), 'vision model: qwen3.5:9b  (ollama /api/chat)',
              font=mono, fill='#d4d4d4')
    draw.text((510, 950), 'screenshot_max_edge: 1280  ->  1024',
              font=mono, fill='#6a9955')

    image.save(path)


def encode_image(path: Path, max_edge: int) -> Tuple[str, int, int, float, int]:
    """按长边缩小并编码为 base64，返回 (b64, w, h, 编码耗时, PNG 字节数)。"""
    start = time.perf_counter()
    with Image.open(path) as image:
        image = image.convert('RGB')
        if max_edge and max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.LANCZOS)
        width, height = image.size
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        raw = buffer.getvalue()
    return base64.b64encode(raw).decode('ascii'), width, height, time.perf_counter() - start, len(raw)


def build_role():
    """取默认角色，并关掉与本次基准无关的热词/纠错上下文。"""
    roles = RoleLoader().get_roles()
    if '默认' not in roles:
        raise SystemExit('没有找到默认角色，请先配置 LLM/default.py')
    role = copy.copy(roles['默认'])
    role.enable_hotwords = False
    role.enable_rectify = False
    role.enable_history = False
    role.enable_screenshot = False  # 图片由基准显式传入
    return role


def run_once(role, builder: MessageBuilder, image_path: Optional[Path],
             max_edge: Optional[int]) -> Dict:
    """跑一次请求，返回统计信息。"""
    if max_edge is None:
        image_data = None
        image_b64 = ''
        width = height = 0
        encode_s = 0.0
        png_kb = 0
    else:
        image_b64, width, height, encode_s, raw_size = encode_image(image_path, max_edge)
        image_data = {
            'image_b64': image_b64,
            'mime': 'image/png',
            'app': 'BenchApp',
            'title': 'config_server.py',
        }
        png_kb = raw_size // 1024

    messages = builder.build_messages(role, USER_TEXT, image_data=image_data)

    start = time.perf_counter()
    if role.provider == 'ollama':
        from ollama import Client as OllamaClient
        client = OllamaClient(host=role.api_url, timeout=120, trust_env=False)
        response = client.chat(
            model=role.model,
            messages=messages,
            stream=False,
            think=role.enable_thinking,
            options={'temperature': role.temperature, 'num_predict': role.max_tokens},
            keep_alive=-1,
        )
        reply = (response.get('message') or {}).get('content') or ''
        prompt_tokens = response.get('prompt_eval_count')
        output_tokens = response.get('eval_count')
    else:
        from openai import OpenAI
        client = OpenAI(base_url=role.api_url, api_key=role.api_key, timeout=120)
        response = client.chat.completions.create(
            model=role.model,
            messages=messages,
            temperature=role.temperature,
            max_tokens=role.max_tokens,
        )
        reply = response.choices[0].message.content or ''
        prompt_tokens = response.usage.prompt_tokens if response.usage else None
        output_tokens = response.usage.completion_tokens if response.usage else None
    api_s = time.perf_counter() - start

    hits = [target for target in TARGETS if target.lower() in reply.lower()]
    misses = [target for target in TARGETS if target not in hits]
    code_lines = sum(1 for line in reply.splitlines() if '=' in line)

    return {
        'edge': max_edge,
        'size': f'{width}x{height}' if width else '-',
        'png_kb': png_kb,
        'encode_s': round(encode_s, 3),
        'api_s': round(api_s, 3),
        'prompt_tokens': prompt_tokens,
        'output_tokens': output_tokens,
        'hits': len(hits),
        'misses': misses,
        'code_lines': code_lines,
        'reply': reply,
    }


def print_row(row: Dict) -> None:
    print(json.dumps(row, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description='截图辅助 LLM 后处理的分辨率/耗时基准')
    parser.add_argument('--edges', default='512,640,768,896,1024,1280',
                        help='逗号分隔的 screenshot_max_edge 列表')
    parser.add_argument('--runs', type=int, default=2, help='每个分辨率跑几次')
    parser.add_argument('--image', default='', help='使用真实截图（留空则生成模拟窗口）')
    parser.add_argument('--verbose', action='store_true', help='显示 LLM 消息日志')
    args = parser.parse_args()

    if not args.verbose:
        logging.getLogger('client').setLevel(logging.WARNING)

    role = build_role()
    builder = MessageBuilder()

    with tempfile.TemporaryDirectory(prefix='cw-bench-') as tmp:
        if args.image:
            image_path = Path(args.image)
            if not image_path.is_file():
                raise SystemExit(f'图片不存在: {image_path}')
        else:
            image_path = Path(tmp) / 'window.png'
            make_window_image(image_path)
            print(f'模拟窗口: {image_path} ({image_path.stat().st_size // 1024} KB)')

        print(f'模型: {role.model} | provider: {role.provider} | API: {role.api_url}')
        print(f'语音文本: {USER_TEXT}')
        print(f'目标术语: {", ".join(TARGETS)}')
        print('---')

        print('=== 无截图基线 ===')
        for _ in range(max(1, args.runs)):
            print_row(run_once(role, builder, None, None))

        edges = [int(x) for x in args.edges.split(',') if x.strip()]
        print('=== 分辨率矩阵 ===')
        for edge in edges:
            for _ in range(max(1, args.runs)):
                print_row(run_once(role, builder, image_path, edge))


if __name__ == '__main__':
    main()
