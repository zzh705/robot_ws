
import os

import subprocess

import tempfile

import wave

import time



WHISPER = "/home/sunrise/robot_ws/library_gui/voice/whisper.cpp/build/bin/whisper-cli"

MODEL = "/home/sunrise/robot_ws/library_gui/voice/whisper.cpp/models/ggml-base.bin"

DEVICE = "plughw:1,0"



print("实时语音转文字已启动")

print("请对着 USB 麦克风说话，按 Ctrl+C 退出")

print("每段录音 3 秒，识别完成后显示文字")



try:

    while True:

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:

            wav_path = f.name



        try:

            rec = subprocess.run(

                ["arecord", "-D", DEVICE, "-f", "S16_LE",

                 "-c", "1", "-r", "16000", "-d", "3", wav_path],

                stdout=subprocess.DEVNULL,

                stderr=subprocess.PIPE,

                text=True

            )

            if rec.returncode != 0:

                print("录音失败：", rec.stderr.strip())

                time.sleep(1)

                continue



            result = subprocess.run(

                [WHISPER, "-m", MODEL, "-f", wav_path,

                 "-l", "zh", "-t", "4", "-ng", "-nt"],

                stdout=subprocess.PIPE,

                stderr=subprocess.STDOUT,

                text=True

            )



            text = ""

            for line in result.stdout.splitlines():

                line = line.strip()

                if not line or line.startswith(("whisper_", "main:", "system_info:", "read_audio_data:")):

                    continue

                if line.startswith("[") and "]" in line:

                    text = line.split("]", 1)[1].strip()



            if text:

                print("识别结果：", text, flush=True)

            else:

                print("本段未识别到文字", flush=True)



        finally:

            if os.path.exists(wav_path):

                os.remove(wav_path)



except KeyboardInterrupt:

    print("\n已退出实时识别")

