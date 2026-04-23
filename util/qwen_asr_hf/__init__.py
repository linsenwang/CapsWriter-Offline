# coding=utf-8
"""
Qwen3-ASR HuggingFace 后端适配包
"""

from .asr_engine import create_asr_engine, QwenASRHFEngine

__all__ = ['create_asr_engine', 'QwenASRHFEngine']
