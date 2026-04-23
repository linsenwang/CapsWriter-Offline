# coding=utf-8
"""
Qwen3-ASR HuggingFace 模型适配器 (qwen-asr 包后端)

兼容 transformers / vLLM 两种后端，使用 HuggingFace 缓存中的原始权重。
在导入 qwen_asr 前自动应用必要的 monkey-patch 以适配较新版本的 transformers。
"""

import os
import sys
import warnings
import numpy as np
from typing import Optional, List

# ──────────────────────────────────────────────────────────────────────────────
# 1. Monkey-patch: 修复 qwen_asr 与 transformers >= 5.x 的 check_model_inputs 兼容性
# ──────────────────────────────────────────────────────────────────────────────
try:
    import transformers.utils.generic as _generic
    _orig_check_model_inputs = _generic.check_model_inputs

    class _CheckModelInputsCompat:
        """使 check_model_inputs 同时支持 @check_model_inputs 和 @check_model_inputs()"""
        def __call__(self, func=None):
            if func is not None:
                return _orig_check_model_inputs(func)
            return _orig_check_model_inputs

    _generic.check_model_inputs = _CheckModelInputsCompat()
except Exception:
    pass  # 如果 transformers 版本较旧，无需 patch

# ──────────────────────────────────────────────────────────────────────────────
# 2. 延迟导入 qwen_asr，避免在模块顶层触发兼容性问题
# ──────────────────────────────────────────────────────────────────────────────
_qwen_asr_imported = False
_Qwen3ASRModel = None


def _ensure_qwen_asr():
    global _qwen_asr_imported, _Qwen3ASRModel
    if _qwen_asr_imported:
        return
    try:
        from qwen_asr import Qwen3ASRModel as _QModel
        _Qwen3ASRModel = _QModel
        _qwen_asr_imported = True
    except ImportError as e:
        raise ImportError(
            "无法导入 qwen_asr 包。请执行安装命令：\n"
            "  pip install -U 'qwen-asr'\n"
            "如需 vLLM 后端加速：\n"
            "  pip install -U 'qwen-asr[vllm]'\n"
            f"原始错误: {e}"
        ) from e


# ──────────────────────────────────────────────────────────────────────────────
# 3. 兼容 CapsWriter-Offline 的识别结果结构
# ──────────────────────────────────────────────────────────────────────────────
class RecognitionResult:
    """兼容 sherpa-onnx / fun_asr_gguf 的识别结果结构"""
    def __init__(self):
        self.text = ""
        self.tokens = []
        self.timestamps = []


class RecognitionStream:
    """兼容 sherpa-onnx / fun_asr_gguf 的识别流结构"""
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.audio_data: Optional[np.ndarray] = None
        self.result = RecognitionResult()

    def accept_waveform(self, sample_rate: int, audio: np.ndarray):
        self.sample_rate = sample_rate
        self.audio_data = audio.astype(np.float32, copy=False)


# ──────────────────────────────────────────────────────────────────────────────
# 4. 引擎主体
# ──────────────────────────────────────────────────────────────────────────────
class QwenASRHFEngine:
    """
    Qwen3-ASR HuggingFace 引擎适配器

    对外接口与 fun_asr_gguf / qwen_asr_gguf 保持一致：
      - create_stream()
      - decode_stream(stream, context=None, language=None, temperature=0.4)
    """

    def __init__(
        self,
        model_path: str = "Qwen/Qwen3-ASR-1.7B",
        backend: str = "transformers",  # "transformers" | "vllm"
        device_map: str = "auto",
        gpu_memory_utilization: float = 0.8,
        max_new_tokens: int = 512,
        max_inference_batch_size: int = 32,
        dtype: Optional[str] = None,
        verbose: bool = False,
        **backend_kwargs,
    ):
        _ensure_qwen_asr()
        self.verbose = verbose
        self.backend = backend.lower()
        self.model_path = model_path

        if self.verbose:
            print(f"[QwenASR-HF] 正在加载模型: {model_path} (backend={self.backend})")

        # 构建后端专属参数
        kwargs = dict(
            max_new_tokens=max_new_tokens,
            max_inference_batch_size=max_inference_batch_size,
        )
        kwargs.update(backend_kwargs)

        if self.backend == "vllm":
            kwargs.setdefault("gpu_memory_utilization", gpu_memory_utilization)
            self.asr = _Qwen3ASRModel.LLM(model_path, **kwargs)
        else:
            # transformers 后端
            kwargs.setdefault("device_map", device_map)
            if dtype:
                kwargs.setdefault("torch_dtype", dtype)
            self.asr = _Qwen3ASRModel.from_pretrained(model_path, **kwargs)

        if self.verbose:
            print(f"[QwenASR-HF] 模型加载完成")

    def create_stream(self, hotwords: Optional[str] = None) -> RecognitionStream:
        """创建识别流（hotwords 在当前版本暂不生效）"""
        return RecognitionStream()

    def decode_stream(
        self,
        stream: RecognitionStream,
        context: Optional[str] = None,
        language: Optional[str] = None,
        temperature: float = 0.4,
    ):
        """
        解码识别流

        Args:
            stream: 包含音频数据的流对象
            context: 上下文参考文本（之前的识别结果）
            language: 目标语言，如 'zh', 'en', 'yue' 等
            temperature: 解码温度（qwen-asr 包内部已处理，此处保留接口兼容）
        """
        if stream.audio_data is None or stream.audio_data.size == 0:
            return

        sr = stream.sample_rate
        audio_data = stream.audio_data

        # 调用 qwen-asr 进行非流式整段转录
        # qwen-asr 内部会自动将音频重采样到 16kHz（使用 librosa）
        results = self.asr.transcribe(
            audio=(audio_data, sr),
            context=context or "",
            language=language,
            return_time_stamps=False,
        )

        if results:
            # results 是 List[ASRTranscription]，取第一条结果
            stream.result.text = results[0].text or ""
        else:
            stream.result.text = ""

    def cleanup(self):
        """释放资源（qwen-asr 暂无显式 shutdown，此处保留接口）"""
        pass


# ──────────────────────────────────────────────────────────────────────────────
# 5. 工厂函数（与 fun_asr_gguf / qwen_asr_gguf 风格保持一致）
# ──────────────────────────────────────────────────────────────────────────────
def create_asr_engine(
    model_path: str = "Qwen/Qwen3-ASR-1.7B",
    backend: str = "transformers",
    device_map: str = "auto",
    gpu_memory_utilization: float = 0.8,
    max_new_tokens: int = 512,
    max_inference_batch_size: int = 32,
    dtype: Optional[str] = None,
    verbose: bool = False,
    **kwargs,
) -> QwenASRHFEngine:
    """
    创建 Qwen3-ASR HuggingFace 引擎

    Args:
        model_path: HuggingFace 模型 ID 或本地绝对路径。
                    例如 "Qwen/Qwen3-ASR-1.7B" 或本地缓存路径。
        backend: "transformers" 或 "vllm"。
        device_map: transformers 后端的设备映射，默认 "auto"。
        gpu_memory_utilization: vLLM 后端的 GPU 显存占用比例。
        max_new_tokens: 单次推理最大生成 token 数。
        max_inference_batch_size: 推理批大小。
        dtype: 模型数据类型，如 "auto", "float16", "bfloat16" 等。
        verbose: 是否打印加载日志。
        **kwargs: 额外传递给 qwen-asr 后端的参数。

    Returns:
        QwenASRHFEngine 实例
    """
    return QwenASRHFEngine(
        model_path=model_path,
        backend=backend,
        device_map=device_map,
        gpu_memory_utilization=gpu_memory_utilization,
        max_new_tokens=max_new_tokens,
        max_inference_batch_size=max_inference_batch_size,
        dtype=dtype,
        verbose=verbose,
        **kwargs,
    )
