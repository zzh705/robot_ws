
import queue

import subprocess

import threading

import numpy as np





class AudioRecorder:

    """

    基于 ALSA arecord 的麦克风音频采集器。



    对外接口保持不变：



        start()

        read()

        stop()



    这样 VoiceManager 不需要修改。

    """



    def __init__(

        self,

        device=6,

        sample_rate=48000,

        channels=1,

        block_size=1024,

        queue_size=50

    ):

        self.device = device

        self.sample_rate = sample_rate

        self.channels = channels

        self.block_size = block_size



        self.audio_queue = queue.Queue(

            maxsize=queue_size

        )



        self.process = None

        self.thread = None

        self.running = False



        # RDK X5 上已经验证成功的 ALSA 设备

        self.alsa_device = "plughw:1,0"



    def _read_audio(self):

        """

        从 arecord 的 stdout 持续读取原始 PCM 数据。

        """



        bytes_per_sample = 2  # S16_LE

        block_bytes = (

            self.block_size

            * self.channels

            * bytes_per_sample

        )



        while self.running and self.process is not None:



            try:

                data = self.process.stdout.read(block_bytes)



                if not data:

                    break



                audio = np.frombuffer(

                    data,

                    dtype=np.int16

                ).copy()



                if self.channels > 1:

                    audio = audio.reshape(

                        -1,

                        self.channels

                    )



                else:

                    audio = audio.reshape(

                        -1,

                        1

                    )



                try:

                    self.audio_queue.put_nowait(audio)



                except queue.Full:

                    print(

                        "警告：音频队列已满，"

                        "丢弃一块音频"

                    )



            except Exception as e:

                print("读取 ALSA 音频失败：", e)

                break



    def start(self):

        """

        启动 ALSA 麦克风采集。

        """



        if self.process is not None:

            print("录音设备已经启动")

            return



        print("正在启动 ALSA 录音设备...")

        print(f"ALSA 设备：{self.alsa_device}")

        print(f"采样率：{self.sample_rate} Hz")

        print(f"声道：{self.channels}")

        print(f"Block Size：{self.block_size}")



        command = [

            "arecord",

            "-D", self.alsa_device,

            "-f", "S16_LE",

            "-c", str(self.channels),

            "-r", str(self.sample_rate),

            "-t", "raw"

        ]



        try:

            self.process = subprocess.Popen(

                command,

                stdout=subprocess.PIPE,

                stderr=subprocess.PIPE,

                bufsize=0

            )



        except Exception as e:

            self.process = None

            raise RuntimeError(

                f"无法启动 arecord：{e}"

            )



        self.running = True



        self.thread = threading.Thread(

            target=self._read_audio,

            daemon=True

        )



        self.thread.start()



        print("录音设备已启动")



    def read(self, timeout=None):

        """

        从音频队列读取一块音频。

        """



        try:

            return self.audio_queue.get(

                timeout=timeout

            )



        except queue.Empty:

            return None



    def stop(self):

        """

        停止 ALSA 录音并释放资源。

        """



        self.running = False



        if self.process is not None:



            try:

                self.process.terminate()

                self.process.wait(timeout=2)



            except Exception:

                try:

                    self.process.kill()

                except Exception:

                    pass



            self.process = None



        if self.thread is not None:



            self.thread.join(timeout=2)

            self.thread = None



        # 清空剩余音频

        while not self.audio_queue.empty():



            try:

                self.audio_queue.get_nowait()



            except queue.Empty:

                break



        print("录音设备已关闭")

