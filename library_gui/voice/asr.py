import subprocess

import os



class ASR:

    """

    Whisper.cpp 语音识别模块

    """


    def __init__(self):

        self.whisper_bin = os.path.join(

            os.path.dirname(__file__),

            "whisper.cpp",

            "build",

            "bin",

            "whisper-cli"

        )


        self.model_path = os.path.join(

            os.path.dirname(__file__),

            "whisper.cpp",

            "models",

            "ggml-base.bin"

        )


    def recognize(self, wav_file):

        """

        识别 WAV 文件中的中文语音

        """


        if not os.path.exists(wav_file):

            print(f"音频文件不存在：{wav_file}")

            return ""


        if not os.path.exists(self.whisper_bin):

            print(f"Whisper 程序不存在：{self.whisper_bin}")

            return ""


        if not os.path.exists(self.model_path):

            print(f"Whisper 模型不存在：{self.model_path}")

            return ""


        command = [

            self.whisper_bin,

            "-m", self.model_path,

            "-f", wav_file,

            "-l", "zh",

            "-t", "4",

            "-nt",

            "-ng"

        ]


        try:


            result = subprocess.run(

                command,

                stdout=subprocess.PIPE,

                stderr=subprocess.STDOUT,

                text=True

            )


            output = result.stdout


            print("Whisper 输出：")

            print(output)


            # whisper-cli 在 -nt 模式下，

            # 最后一段纯文字就是识别结果。

            lines = output.strip().splitlines()


            for line in reversed(lines):


                line = line.strip()


                if not line:

                    continue


                if line.startswith("whisper_"):

                    continue


                if line.startswith("main:"):

                    continue


                if line.startswith("system_info:"):

                    continue


                if line.startswith("read_audio_data:"):

                    continue


                if line.startswith("whisper_init"):

                    continue


                if line.startswith("whisper_model"):

                    continue


                if line.startswith("whisper_backend"):

                    continue


                if line.startswith("whisper_init_state"):

                    continue


                if line.startswith("whisper_print"):

                    continue


                return line


            return ""


        except Exception as e:


            print(f"Whisper 识别失败：{e}")

            return ""



def recognize(wav_file):

    """

    简单调用接口

    """


    asr = ASR()


    return asr.recognize(wav_file)



if __name__ == "__main__":


    wav_file = os.path.join(

        os.path.dirname(__file__),

        "test.wav"

    )


    text = recognize(wav_file)


    print()

    print("====================")

    print("识别结果：")

    print(text)

    print("====================")
