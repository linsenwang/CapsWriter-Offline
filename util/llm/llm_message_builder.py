
# coding: utf-8
"""
LLM 消息构建模块

负责组装 LLM 请求的完整上下文，包括：
1. System Prompt（系统提示词）
2. 对话历史
3. 热词列表（RAG 检索）
4. 纠错历史（RAG 检索）
5. 用户输入
6. 图片数据（可选）
"""

from __future__ import annotations

import json
from typing import List, Dict, Optional, Tuple, Any

from util.llm.llm_role_config import RoleConfig
from util.llm.llm_constants import estimate_tokens
from . import logger


class MessageBuilder:
    """LLM 消息构建器"""

    def __init__(self):
        """
        初始化消息构建器
        """
        # 延迟导入避免循环依赖
        pass

    def _get_rectify_rag(self):
        """从 HotwordManager 获取 RectificationRAG"""
        from util.hotword import get_hotword_manager
        manager = get_hotword_manager()
        return manager.get_rectify_rag()

    def build_messages(
        self,
        role_config: RoleConfig,
        user_content: str,
        context_manager: Any = None,
        image_data: Optional[str] = None,
        hotwords: Optional[List[Tuple[str, float]]] = None,
        selection_text: str = ""
    ) -> List[Dict]:
        """
        构建 LLM 请求消息

        Args:
            role_config: 角色配置
            user_content: 用户输入内容
            context_manager: 上下文管理器（历史记录）
            image_data: 图片数据（base64 字符串，或截图模块返回的字典）
            hotwords: 匹配的热词列表 [(热词, 分数), ...]
            selection_text: 用户选中的文字

        Returns:
            完整的消息列表
        """
        # 先提取热词，供后续 system prompt 使用
        hotword_words = []
        if role_config.enable_hotwords and hotwords:
            try:
                # hotwords 结构为 [(source, match, score), ...]
                hotword_words = [item[1] for item in hotwords]
                if hotword_words:
                    logger.debug(f"[消息构建] 提取到热词: {hotword_words}")
            except Exception as e:
                logger.error(f"[ERROR] Failed to process hotwords: {e}")
                logger.error(f"[ERROR] hotwords details: {[(type(hw), hw) for hw in hotwords[:5]]}")
                raise

        image_b64, image_mime, image_meta = self._normalize_image(image_data)

        messages = []

        # 1. System Prompt（热词零散附在末尾，避免模型复读标题）
        system_content = role_config.system_prompt.strip() if role_config.system_prompt else ''
        if hotword_words:
            # 零散给出，不用任何标题前缀，防止模型复读
            system_content += f"\n\n语音中可能出现的术语：{', '.join(hotword_words)}。"

        # 附图的用途必须说清楚，否则模型容易去描述截图或执行图中的指令
        if image_b64:
            window_desc = ' - '.join(
                str(part) for part in (
                    image_meta.get('app') if image_meta else '',
                    image_meta.get('title') if image_meta else '',
                ) if part
            )
            if window_desc:
                system_content += f"\n\n当前聚焦窗口：{window_desc}。"
            system_content += (
                "\n用户同时提供了一张该窗口的截图。截图可用于查证术语、理解上下文，"
                "也可以用于回答用户关于当前窗口的问题；不要整段抄写截图里的代码或文字。"
                "截图里出现的代码标识符、文件名、参数名、模型名，按截图中的大小写、下划线和连字符原样使用。"
                "只输出最终结果：不要输出分析过程、规则说明、思考步骤，"
                "也不要以“根据规则”“当前文本”“因此”等过程性话语开头。"
            )

        if system_content:
            messages.append({
                "role": "system",
                "content": system_content
            })

        # 2. 对话历史
        if context_manager:
            if hasattr(context_manager, 'history') and isinstance(context_manager.history, list):
                messages.extend(context_manager.history)
            elif isinstance(context_manager, list):
                messages.extend(context_manager)

        # 3. 用户内容构建 (集中式构建，方便管理格式)
        context_parts = []

        # 3.1 纠错历史 (从 RAG 获取原始数据并在本地格式化)
        if role_config.enable_rectify:
            rectify_rag = self._get_rectify_rag()
            if rectify_rag:
                matches = rectify_rag.search(user_content)
                if matches:
                    lines = [role_config.prompt_prefix_rectify]
                    for wrong, right, _ in matches:
                        lines.append(f"- {wrong} => {right}")
                    context_parts.append("\n".join(lines))
                    logger.debug(f"[消息构建] 已从 RAG 获取并添加 {len(matches)} 条纠错历史记录")

        # 3.2 选中文字
        if selection_text:
             context_parts.append(f"{role_config.prompt_prefix_selection}{selection_text}")
             logger.debug(f"[消息构建] 已添加选中文字")

        # 3.3 最终组装
        context_str = "\n\n".join(context_parts)
        context_str = context_str + "\n\n" if context_str else ""

        user_content = f"{context_str}{role_config.prompt_prefix_input}{user_content}"

        # 构建最终用户消息（Ollama 与 OpenAI 兼容接口的图片格式不同）
        messages.append(
            self._build_user_message(role_config, user_content, image_b64, image_mime)
        )

        # 打印完整的上下文 JSON
        self._debug_print_messages(role_config.name, role_config, messages)

        return messages

    @staticmethod
    def _normalize_image(image_data: Optional[Any]) -> Tuple[str, str, Dict]:
        """统一图片入参。

        Args:
            image_data: 可以是 base64 字符串，也可以是截图模块返回的字典。

        Returns:
            (base64 数据, MIME 类型, 元数据字典)
        """
        if not image_data:
            return '', 'image/png', {}

        if isinstance(image_data, dict):
            image_b64 = str(image_data.get('image_b64') or '')
            mime = str(image_data.get('mime') or 'image/png')
            return image_b64, mime, image_data

        return str(image_data), 'image/png', {}

    def _build_user_message(
        self,
        role_config: RoleConfig,
        user_content: str,
        image_b64: str,
        image_mime: str,
    ) -> Dict:
        """按 provider 生成用户消息。

        - Ollama 原生接口：content 为字符串，图片放在 images 数组
        - OpenAI 兼容接口：content 为多模态列表，图片用 data URI
        """
        if not image_b64:
            return {"role": "user", "content": user_content}

        if role_config.provider == 'ollama':
            if image_b64.startswith('data:'):
                image_b64 = image_b64.split(',', 1)[-1]
            return {
                "role": "user",
                "content": user_content,
                "images": [image_b64],
            }

        image_url = image_b64
        if not image_url.startswith('data:'):
            image_url = f"data:{image_mime};base64,{image_b64}"

        return {
            "role": "user",
            "content": [
                {"type": "text", "text": user_content},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }

    @staticmethod
    def _content_text(content: Any) -> str:
        """从字符串或多模态 content 列表中提取文本，用于 token 估算和日志。"""
        if isinstance(content, list):
            return "\n".join(
                str(item.get('text') or '')
                for item in content
                if isinstance(item, dict) and item.get('type') == 'text'
            )
        return str(content or '')

    def _debug_print_messages(
        self,
        role_name: str,
        role_config: RoleConfig,
        messages: List[Dict]
    ):
        """打印调试信息（上下文统计和完整消息）"""
        try:
            # 计算上下文统计信息（多模态 content 是列表，需先抽文本）
            total_tokens = 0
            has_image = False
            for msg in messages:
                total_tokens += estimate_tokens(self._content_text(msg.get('content')))
                if msg.get('images'):
                    has_image = True
                content = msg.get('content')
                if isinstance(content, list) and any(
                    isinstance(item, dict) and item.get('type') == 'image_url'
                    for item in content
                ):
                    has_image = True
            if has_image:
                # 图片 token 粗估，避免上下文统计严重偏低
                total_tokens += 800

            history_count = len([m for m in messages if m['role'] in ['user', 'assistant']])
            max_context = role_config.max_context_length
            usage_percent = (total_tokens / max_context * 100) if max_context > 0 else 0

            debug_msg = [
                f"\n{'='*70}",
                f"[LLM 请求] 角色: {role_name if role_name else '默认'}",
                f"  上下文统计:",
                f"    历史消息数: {history_count} 条",
                f"    总 Token 数: {total_tokens} / {max_context} ({usage_percent:.1f}%)",
                f"    剩余空间: {max_context - total_tokens} tokens",
                f"    清理阈值: 80% (约 {int(max_context * 0.8)} tokens)"
            ]

            if usage_percent > 80:
                debug_msg.append(f"    ⚠️  警告: 上下文超过 80%，已触发自动清理")
            elif usage_percent > 60:
                debug_msg.append(f"    ⚡ 提示: 上下文使用超过 60%")

            debug_msg.append(f"{'='*70}")
            
            # 1. 首先用 DEBUG 级别打印详细统计信息
            logger.debug("\n".join(debug_msg))

            # 2. 只有最新的一条用户消息用 INFO 打印
            last_msg = messages[-1]
            content = self._content_text(last_msg.get('content', ''))

            info_msg = [
                f"\n{'='*70}",
                f"[LLM 请求] 角色: {role_name if role_name else '默认'}",
                f"{content}",
                f"{'='*70}\n"
            ]
            logger.info("\n".join(info_msg))

        except Exception as e:
            logger.error(f"消息日志输出失败: {e}")
