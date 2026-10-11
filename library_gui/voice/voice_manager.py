import os
import sys
import wave
import numpy as np


# 加入项目根目录
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.insert(0, PROJECT_ROOT)

_VOICE_DIR = os.path.dirname(os.path.abspath(__file__))
if _VOICE_DIR not in sys.path:
    sys.path.insert(0, _VOICE_DIR)


from audio_recorder import AudioRecorder
from asr import recognize
from book_chat import book_chat
from vad import VoiceActivityGate


def _resample_to_16k(audio, sample_rate):
    """把采样率转到 16kHz。

    Whisper 只吃 16k 单声道。旧版用 `audio[::3]` 粗暴抽样, 会有混叠、
    丢高频, 识别率受影响。这里优先用 scipy 多相滤波(带抗混叠),
    环境里没有 scipy 时再退回抽样, 保证不因缺依赖而失败。
    """
    if int(sample_rate) == 16000:
        return audio.astype(np.int16)
    try:
        from math import gcd
        from scipy.signal import resample_poly

        g = gcd(int(sample_rate), 16000)
        up = 16000 // g
        down = int(sample_rate) // g
        out = resample_poly(audio.astype(np.float32), up, down)
        return np.clip(out, -32768, 32767).astype(np.int16)
    except Exception:
        step = max(1, int(round(sample_rate / 16000.0)))
        return audio[::step].astype(np.int16)


class VoiceManager:
    """
    语音问答管理器

    完成：
    麦克风录音
        ↓
    WAV 文件
        ↓
    Whisper 语音识别
        ↓
    Ollama AI 问答
    """

    def __init__(self):

        self.sample_rate = 48000
        self.channels = 1

        self.recorder = AudioRecorder(
            sample_rate=self.sample_rate,
            channels=self.channels
        )

        self.base_dir = os.path.dirname(
            os.path.abspath(__file__)
        )

        self.wav_file = os.path.join(
            self.base_dir,
            "voice_input.wav"
        )

    def record(
        self,
        seconds=5,
        on_level=None,
        on_stage=None,
        auto_stop=False,
        max_seconds=None,
        min_seconds=1.0,
        silence_timeout=0.9,
        stop_check=None,
    ):
        """录制语音并写成 16k 单声道 WAV。

        参数:
            seconds      : 固定录音秒数(auto_stop=False 时生效)
            auto_stop    : True 时用能量 VAD 检测「说完了」自动停
            max_seconds  : auto_stop 模式下的最长录音秒数, 默认取 seconds
            min_seconds  : 最短录音秒数, 防止秒停
            silence_timeout : 连续静音多久算说完(秒)
            stop_check   : 无参可调用对象, 返回 True 立即停止(界面按钮)
            on_level     : 回调(0.0~1.0 音量), 驱动界面电平环
            on_stage     : 回调('recording'/'recognizing'/'thinking')
        """

        if on_stage is not None:
            on_stage('recording')

        print()
        print("================================")
        print("开始录音")
        print("================================")
        print(f"请说话，录音时间：{seconds} 秒")

        gate = None
        if auto_stop:
            gate = VoiceActivityGate(
                sample_rate=self.sample_rate,
                max_seconds=float(
                    seconds if max_seconds is None else max_seconds),
                min_seconds=min_seconds,
                silence_timeout=silence_timeout,
            )
            print(f"VAD 自动断句已开启(最长 {gate.max_seconds:.0f} 秒)")

        block_count = (
            None if auto_stop else
            int(self.sample_rate / self.recorder.block_size * seconds)
        )

        self.recorder.start()

        audio_blocks = []
        empty_reads = 0

        try:

            while True:

                if stop_check is not None and stop_check():
                    if gate is not None:
                        gate.mark_manual_stop()
                    break

                if block_count is not None and len(audio_blocks) >= block_count:
                    break

                data = self.recorder.read(timeout=2)

                if data is None:
                    # 采集端暂时没数据: 连着几次拿不到就收工, 别死等
                    empty_reads += 1
                    if empty_reads >= 3:
                        break
                    continue

                empty_reads = 0

                block = data[:, 0] if data.ndim > 1 else data

                if on_level is not None:
                    try:
                        on_level(
                            min(1.0, VoiceActivityGate.rms(block) / 3500.0))
                    except Exception:
                        pass

                if gate is not None and gate.feed(block):
                    break

                audio_blocks.append(block)

        finally:

            self.recorder.stop()

        if not audio_blocks:
            print("没有录到音频")
            return None

        audio = np.concatenate(audio_blocks, axis=0)

        # 单声道
        if audio.ndim > 1:
            audio = audio[:, 0]

        # 采样率 → 16kHz(Whisper 只吃 16k 单声道)
        audio = _resample_to_16k(audio, self.sample_rate)

        self._save_wav(
            self.wav_file,
            audio,
            16000
        )

        print(f"录音完成：{self.wav_file}")
        print(f"音频长度：{len(audio) / 16000:.2f} 秒")

        if gate is not None:

            print(
                f"VAD 结果：检测到语音={gate.speech_detected} "
                f"语音时长={gate.speech_seconds:.2f}s "
                f"停止原因={gate.reason}"
            )

        return self.wav_file

    def _save_wav(self, filename, audio, sample_rate):

        with wave.open(filename, "wb") as wf:

            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)

            wf.writeframes(
                audio.tobytes()
            )

    def recognize(self, wav_file):

        print()
        print("================================")
        print("开始语音识别")
        print("================================")

        text = recognize(wav_file)

        print()
        print("识别结果：")
        print(text)

        return text

    def ask_ai(self, text):

        print()
        print("================================")
        print("开始处理用户问题")
        print("================================")

        answer = book_chat(text)

        print()
        print("AI回答：")
        print(answer)

        return answer

    def voice_chat(
        self,
        seconds=5,
        on_level=None,
        on_stage=None,
        auto_stop=False,
        max_seconds=None,
        stop_check=None,
    ):

        # 1. 录音
        wav_file = self.record(
            seconds,
            on_level=on_level,
            on_stage=on_stage,
            auto_stop=auto_stop,
            max_seconds=max_seconds,
            stop_check=stop_check,
        )

        if not wav_file:
            return "", ""

        # 2. 语音识别
        if on_stage is not None:
            on_stage('recognizing')

        text = self.recognize(wav_file)

        if not text:
            return "", ""

        # 3. AI 问答
        if on_stage is not None:
            on_stage('thinking')

        answer = self.ask_ai(text)

        return text, answer


if __name__ == "__main__":

    manager = VoiceManager()

    text, answer = manager.voice_chat(
        seconds=5
    )

    print()
    print("================================")
    print("最终结果")
    print("================================")

    print("用户：")
    print(text)

    print()

    print("AI：")
    print(answer)