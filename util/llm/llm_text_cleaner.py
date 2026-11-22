# coding: utf-8
"""
LLM 输出清理

模型偶尔会在 content 里输出“根据规则……因此……”这类过程性话语，
直接打字会把思考过程也打出去。这里做两件事：

1. 去掉明显的分析/规则说明段落
2. 把换行替换为空格，避免模拟打字时触发回车发送
"""

from __future__ import annotations

import re

# 只匹配明显的元话语，避免误删正常文本
_META_PATTERNS = (
    r'^根据规则',
    r'^按照规则',
    r'^根据要求',
    r'^当前文本',
    r'^唯一可优化',
    r'^我只需',
    r'^我只需要',
    r'^分析[:：]',
    r'^思考[:：]',
    r'^说明[:：]',
    r'^直接输出修正后文本',
    r'^修正后文本[:：]',
    r'^最终输出[:：]',
    r'^因此[，,].*(?:输出|修正|文本)',
)
_META_RE = re.compile('|'.join(f'(?:{pattern})' for pattern in _META_PATTERNS))


def sanitize_for_typing(text: str) -> str:
    """把换行/回车替换为空格，并合并连续空白。"""
    if not text:
        return text
    text = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    return re.sub(r'[ \t]+', ' ', text).strip()


def _strip_markdown(text: str) -> str:
    """去掉常见的 Markdown 标记，保留代码内容。

    只在输出明显像 Markdown 时处理，避免误改正常文本里的星号或井号。
    """
    if '```' not in text and '**' not in text and not re.search(r'^#{1,6}\s', text, re.M):
        return text

    # 代码围栏：去掉 ```python / ```，保留中间代码
    text = re.sub(r'```[a-zA-Z0-9_+-]*\s*', '', text)
    text = text.replace('```', '')
    # 标题、分隔线、粗体、行内代码
    text = re.sub(r'^\s*#{1,6}\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.M)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text


def clean_llm_output(text: str) -> str:
    """去掉模型输出里的思考过程，只保留最终结果。"""
    if not text:
        return text

    normalized = _strip_markdown(text.replace('\r\n', '\n').replace('\r', '\n'))
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', normalized) if p.strip()]
    if not paragraphs:
        return sanitize_for_typing(text)

    kept = []
    for paragraph in paragraphs:
        if not _META_RE.match(paragraph):
            kept.append(paragraph)
            continue

        # “因此，直接输出修正后文本：最终文本” 这种写法保留冒号后的内容
        parts = re.split(r'[：:]\s*', paragraph, maxsplit=1)
        if len(parts) == 2:
            tail = parts[1].strip()
            if tail and not _META_RE.match(tail):
                kept.append(tail)

    # 全是元话语时不要输出空，回退到原文（至少让用户看到内容）
    if not kept:
        return sanitize_for_typing(text)

    return sanitize_for_typing(' '.join(kept))
