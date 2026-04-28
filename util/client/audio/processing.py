# coding: utf-8
"""
音频后处理工具

提供统一的增益、归一化与软限幅处理，避免在多处重复实现。
"""

import numpy as np


def soft_limit(audio: np.ndarray, threshold: float = 0.9) -> np.ndarray:
    """
    软限幅（Soft Limiter）。

    在 |audio| <= threshold 时保持线性；超过 threshold 后，
    使用平滑的 tanh 曲线将信号逐渐压缩并趋近于 ±1.0，
    从而避免硬削波（hard clip）带来的刺耳数字失真。

    在 threshold 处函数值与导数均连续，过渡自然。
    """
    abs_audio = np.abs(audio)
    mask = abs_audio > threshold
    if not np.any(mask):
        return audio

    result = audio.copy()
    # 将超过 threshold 的部分缩放到 tanh 的定义域
    over = (abs_audio[mask] - threshold) / (1.0 - threshold)
    # 压缩后的幅度：从 threshold 开始平滑趋近于 1.0
    compressed = threshold + (1.0 - threshold) * np.tanh(over)
    result[mask] = np.sign(audio[mask]) * compressed
    return result


def apply_audio_gain(
    audio_data: np.ndarray,
    *,
    normalize: bool = False,
    normalize_target: float = 0.95,
    gain: float = 1.0,
) -> np.ndarray:
    """
    统一音频增益/归一化处理。

    优先级：
    1. normalize=True 时，按峰值归一化到 normalize_target，随后软限幅。
    2. gain != 1.0 时，应用固定增益，随后软限幅。
    3. 其余情况原样返回。
    """
    if normalize:
        peak = np.max(np.abs(audio_data))
        if peak > 0:
            computed_gain = normalize_target / peak
            return soft_limit(audio_data * computed_gain)
        return audio_data
    elif gain != 1.0:
        return soft_limit(audio_data * gain)
    return audio_data
