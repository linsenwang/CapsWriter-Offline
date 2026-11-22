# coding: utf-8
"""
音频后处理工具

提供统一的增益、归一化与软限幅处理，避免在多处重复实现。
"""

import math

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


class LoudnessAGC:
    """
    自适应响度补偿（Automatic Gain Control）。

    逐块统计短时 RMS，自动把平均电平推向目标值，替代写死的固定增益。与
    峰值归一化相比：
    - 用 RMS 而不是峰值衡量电平，单个爆音（敲键盘、咳嗽）不会把整段拉低；
    - 增益在 dB 域平滑：变小快、变大慢，避免音量忽大忽小（pumping）；
    - 低于 gate 的静音块不更新增益，避免把底噪抬成「沙沙」声；
    - 逐块处理，无额外延迟，每块只有一次 sqrt + 一次乘法，开销可忽略。

    平滑状态保存在实例内部，同一路音频必须复用同一个实例；每次开始录音
    或开始转录新文件时调用 reset()。
    """

    def __init__(
        self,
        *,
        target_db: float = -20.0,
        max_gain_db: float = 30.0,
        min_gain_db: float = -12.0,
        gate_db: float = -55.0,
        attack: float = 0.15,
        release: float = 2.5,
        sample_rate: int = 48000,
    ):
        """
        Args:
            target_db: 目标平均电平（dBFS RMS）
            max_gain_db: 最大放大量（dB），防止把底噪抬得过高
            min_gain_db: 最大衰减量（dB，负值），防止爆音
            gate_db: 静音门限（dBFS RMS），低于该电平的块不参与增益更新
            attack: 增益下降的时间常数（秒），越小压爆音越快
            release: 增益上升的时间常数（秒），越大音量越稳但适应越慢
            sample_rate: 输入采样率，用于把时间常数换算成逐块系数
        """
        self.target_db = target_db
        self.max_gain_db = max_gain_db
        self.min_gain_db = min_gain_db
        self.gate_db = gate_db
        self.attack = max(attack, 1e-3)
        self.release = max(release, 1e-3)
        self.sample_rate = sample_rate
        self.reset()

    def reset(self) -> None:
        """清空平滑状态，回到默认增益（0dB，即原样）"""
        self.gain_db = 0.0
        self._initialized = False

    def process(self, audio_data: np.ndarray) -> np.ndarray:
        """更新增益并应用（含软限幅），返回与输入同形状的音频"""
        if audio_data.size == 0:
            return audio_data

        # 每通道的样本数，用于按真实时长换算平滑系数
        frames = audio_data.shape[0] if audio_data.ndim > 1 else audio_data.size
        rms = float(np.sqrt(np.mean(np.square(audio_data, dtype=np.float64))))

        if rms > 1e-7:
            level_db = 20.0 * math.log10(rms)
            # 静音块只沿用当前增益，不更新状态
            if level_db >= self.gate_db:
                desired_db = min(
                    max(self.target_db - level_db, self.min_gain_db),
                    self.max_gain_db,
                )
                if not self._initialized:
                    # 首个有效块直接对齐，避免开头一小段电平不足
                    self.gain_db = desired_db
                    self._initialized = True
                else:
                    tau = self.attack if desired_db < self.gain_db else self.release
                    alpha = 1.0 - math.exp(-frames / (self.sample_rate * tau))
                    self.gain_db += (desired_db - self.gain_db) * alpha

        return soft_limit(audio_data * (10.0 ** (self.gain_db / 20.0)))

    @property
    def gain(self) -> float:
        """当前线性增益系数（便于日志排查）"""
        return 10.0 ** (self.gain_db / 20.0)


def create_agc(sample_rate: int) -> LoudnessAGC:
    """按 config_client 中的音频配置创建 AGC 实例"""
    from config_client import ClientConfig as Config

    return LoudnessAGC(
        target_db=getattr(Config, 'audio_agc_target_db', -20.0),
        max_gain_db=getattr(Config, 'audio_agc_max_gain_db', 30.0),
        min_gain_db=getattr(Config, 'audio_agc_min_gain_db', -12.0),
        gate_db=getattr(Config, 'audio_agc_gate_db', -55.0),
        attack=getattr(Config, 'audio_agc_attack', 0.15),
        release=getattr(Config, 'audio_agc_release', 2.5),
        sample_rate=sample_rate,
    )
