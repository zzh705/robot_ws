import os
import sys
import wave
import numpy as np


# 加入项目根目录
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.insert(0, PROJECT_ROOT)


from audio_recorder import AudioRecorder
from asr import recognize
from book_chat import book_chat


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

    def record(self, seconds=5):
        """
        录制指定秒数的语音
        """

        print()
        print("================================")
        print("开始录音")
        print("================================")
        print(f"请说话，录音时间：{seconds} 秒")

        self.recorder.start()

        audio_blocks = []

        try:

            block_count = int(
                self.sample_rate / self.recorder.block_size * seconds
            )

            for _ in range(block_count):

                data = self.recorder.read(timeout=2)

                if data is not None:
                    audio_blocks.append(data)

        finally:

            self.recorder.stop()

        if not audio_blocks:
            print("没有录到音频")
            return None

        audio = np.concatenate(
            audio_blocks,
            axis=0
        )

        # 单声道
        if audio.ndim > 1:
            audio = audio[:, 0]

        # 48kHz → 16kHz
        # 目前先使用简单抽样，后面再优化
        audio = audio[::3]

        audio = audio.astype(np.int16)

        self._save_wav(
            self.wav_file,
            audio,
            16000
        )

        print(f"录音完成：{self.wav_file}")
        print(f"音频长度：{len(audio) / 16000:.2f} 秒")

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

    def voice_chat(self, seconds=5):

        # 1. 录音
        wav_file = self.record(seconds)

        if not wav_file:
            return "", ""

        # 2. 语音识别
        text = self.recognize(wav_file)

        if not text:
            return "", ""

        # 3. AI 问答
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