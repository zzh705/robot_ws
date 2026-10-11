"""voice/vad.py —— 轻量「能量法」语音活动检测(纯 numpy, 不需要额外模型)。

作用: 让语音交互从「固定录 5 秒」升级为「检测到你说完就自动停」。

判定思路
  1. 开头 noise_calib_seconds 秒只用来估本底噪声, 不做判定;
  2. 之后每块 PCM 算 RMS, 与三个参考值取最大作为阈值:
        固定下限 threshold_min
        本底噪声 * noise_factor
        迄今峰值 * peak_ratio      <- 自适应麦克风增益
  3. 检测到语音后, 连续静音超过 silence_timeout 秒 → 认为说完了;
  4. 兜底: no_speech_timeout 内一直没人说话 → 停(不空等);
          录满 max_seconds → 强制停; 不足 min_seconds 不触发静音判定。

纯 numpy + 一个状态机, 可直接在板端单测(见文件末尾 __main__)。
"""

import math

import numpy as np


class VoiceActivityGate:
    """逐块喂 PCM, 返回「是否该停止录音」。"""

    def __init__(
        self,
        sample_rate=48000,
        threshold_min=150.0,
        noise_factor=2.5,
        peak_ratio=0.15,
        noise_calib_seconds=0.6,
        silence_timeout=1.4,
        no_speech_timeout=5.0,
        min_seconds=1.0,
        max_seconds=10.0,
        min_speech_seconds=0.5,
    ):
        self.sample_rate = float(sample_rate)
        self.threshold_min = float(threshold_min)
        self.noise_factor = float(noise_factor)
        self.peak_ratio = float(peak_ratio)
        self.noise_calib_seconds = float(noise_calib_seconds)
        self.silence_timeout = float(silence_timeout)
        self.no_speech_timeout = float(no_speech_timeout)
        self.min_seconds = float(min_seconds)
        self.max_seconds = float(max_seconds)
        self.min_speech_seconds = float(min_speech_seconds)

        # ---- 运行状态(便于界面/日志展示) ----
        self.elapsed = 0.0          # 已判定时长(秒)
        self.speech_detected = False
        self.speech_seconds = 0.0
        self.noise_floor = 0.0
        self._peak = 0.0
        self._calib_levels = []
        self._silent_run = 0.0
        self._reason = None

    # ------------------------------------------------------------------
    @staticmethod
    def rms(block):
        """一块 int16 PCM 的均方根(音量)。空块返回 0。"""
        a = np.asarray(block, dtype=np.float64)
        if a.size == 0:
            return 0.0
        return float(math.sqrt(float((a * a).mean())))

    @property
    def threshold(self):
        """当前判定阈值: 固定下限 / 本底噪声 / 峰值 三者取大。"""
        return max(
            self.threshold_min,
            self.noise_floor * self.noise_factor,
            self._peak * self.peak_ratio,
        )

    @property
    def reason(self):
        """停止原因: 'silence' / 'max' / 'no_speech' / 'manual' / None。"""
        return self._reason

    def mark_manual_stop(self):
        """界面按钮手动结束时调用, 让停止原因可读。"""
        if self._reason is None:
            self._reason = 'manual'

    # ------------------------------------------------------------------
    def feed(self, block):
        """喂一块 PCM(int16, 1 维)。返回 True 表示可以停止录音了。"""
        n = len(block)
        if n == 0:
            return False

        dur = n / self.sample_rate
        level = self.rms(block)

        # ---- 本底噪声标定期: 只统计, 不判定 ----
        if self.elapsed < self.noise_calib_seconds:
            # 取标定期「最小」块当本底噪声: 说话人若一开始就出声, 用均值
            # 会把噪声底估高、阈值偏高, 于是真人语音被判成静音 → 提前截断。
            self._calib_levels.append(level)
            self.noise_floor = min(self._calib_levels)
            self._peak = max(self._peak, level)
            self.elapsed += dur
            return False

        if level > self.threshold:
            self.speech_detected = True
            self.speech_seconds += dur
            self._silent_run = 0.0
        else:
            self._silent_run += dur

        self._peak = max(self._peak, level)
        self.elapsed += dur

        # 1) 录满上限
        if self.elapsed >= self.max_seconds:
            self._reason = 'max'
            return True

        # 2) 说完了: 有过语音 + 静音够久 + 话够长
        if (
            self.speech_detected
            and self.speech_seconds >= self.min_speech_seconds
            and self._silent_run >= self.silence_timeout
            and self.elapsed >= self.min_seconds
        ):
            self._reason = 'silence'
            return True

        # 3) 一直没人说话
        if (
            not self.speech_detected
            and self.elapsed - self.noise_calib_seconds >= self.no_speech_timeout
        ):
            self._reason = 'no_speech'
            return True

        return False


if __name__ == '__main__':
    import sys
    import wave

    path = sys.argv[1] if len(sys.argv) > 1 else 'voice_input.wav'
    with wave.open(path) as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16)

    gate = VoiceActivityGate(
        sample_rate=sr,
        max_seconds=60.0,        # 自测不靠上限, 只看 VAD 判断
        no_speech_timeout=60.0,
    )
    for i in range(0, len(audio), 1024):
        if gate.feed(audio[i:i + 1024]):
            break

    print(
        f'file={path} sr={sr} 判定时长={gate.elapsed:.2f}s '
        f'检测到语音={gate.speech_detected} 语音时长={gate.speech_seconds:.2f}s '
        f'本底={gate.noise_floor:.1f} 阈值={gate.threshold:.1f} '
        f'停止原因={gate.reason}'
    )
