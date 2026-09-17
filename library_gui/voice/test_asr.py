import wave

import numpy as np


from audio_recorder import AudioRecorder



OUTPUT_FILE = "test.wav"


SAMPLE_RATE = 48000

CHANNELS = 1

RECORD_SECONDS = 5



recorder = AudioRecorder(

    device=6,

    sample_rate=SAMPLE_RATE,

    channels=CHANNELS

)

audio_data = []


try:

    print("================================")

    print("开始录音")

    print("请说：你好，请帮我找一本 Python 的书")

    print("录音时间：5 秒")

    print("================================")


    recorder.start()


    total_blocks = int(SAMPLE_RATE * RECORD_SECONDS / 1024)


    for _ in range(total_blocks):

        data = recorder.read(timeout=1)


        if data is not None:

            audio_data.append(data)


finally:

    recorder.stop()



if not audio_data:

    print("没有采集到音频")

    exit(1)



audio = np.concatenate(audio_data, axis=0)


# 单声道

audio = audio[:, 0]


# 48kHz -> 16kHz

audio_16k = audio[::3]


# 保存 WAV

with wave.open(OUTPUT_FILE, "wb") as wf:

    wf.setnchannels(1)

    wf.setsampwidth(2)       # int16 = 2 bytes

    wf.setframerate(16000)

    wf.writeframes(audio_16k.astype(np.int16).tobytes())



print()

print("录音完成")

print(f"音频长度：{len(audio_16k) / 16000:.2f} 秒")

print(f"文件：{OUTPUT_FILE}")
