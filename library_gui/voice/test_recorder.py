from audio_recorder import AudioRecorder


recorder = AudioRecorder()

try:

    recorder.start()

    print("开始读取麦克风数据...")
    print("请对着 HY57 说话")
    print("按 Ctrl+C 停止")

    while True:

        data = recorder.read(timeout=1)

        if data is not None:

            print(
                f"读取到音频："
                f"shape={data.shape}, "
                f"dtype={data.dtype}, "
                f"bytes={data.nbytes}"
            )

except KeyboardInterrupt:

    print("\n用户停止录音")

finally:

    recorder.stop()