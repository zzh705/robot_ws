#!/usr/bin/env python3

"""
STM32 <-> RDK X5 串口驱动

功能：

1. 打开 STM32 串口
2. 配置 115200 8N1
3. 发送二进制协议帧
4. 接收串口字节流
5. 将接收到的数据交给 FrameParser
6. 提供关闭串口功能

注意：

本文件目前不会自动发送 CMD_VEL。
因此不会主动让机器人运动。
"""

import threading
import time

import serial

from .protocol import FrameParser


class SerialDriver:
    """
    STM32 串口驱动。

    当前默认：

        device = /dev/ttyACM0
        baudrate = 115200
        8N1
    """

    def __init__(
        self,
        device: str = "/dev/ttyACM0",
        baudrate: int = 115200,
        timeout: float = 0.1,
    ):

        self.device = device
        self.baudrate = baudrate
        self.timeout = timeout

        self.serial = None

        self.running = False

        self.receive_thread = None

        self.parser = FrameParser()

        self.lock = threading.Lock()

        # 最近一次收到有效数据的时间
        self.last_rx_time = 0.0

    # ========================================================
    # 打开串口
    # ========================================================

    def open(self):

        if self.serial is not None and self.serial.is_open:
            return

        print(
            f"[SerialDriver] Opening {self.device} "
            f"at {self.baudrate} baud..."
        )

        self.serial = serial.Serial(
            port=self.device,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )

        # 清理打开串口之前残留的数据
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

        self.running = True

        self.receive_thread = threading.Thread(
            target=self._receive_loop,
            daemon=True,
        )

        self.receive_thread.start()

        print(
            f"[SerialDriver] Connected: {self.device}"
        )

    # ========================================================
    # 接收线程
    # ========================================================

    def _receive_loop(self):

        print("[SerialDriver] Receive thread started.")

        while self.running:

            try:

                if self.serial is None or not self.serial.is_open:
                    time.sleep(0.1)
                    continue

                data = self.serial.read(
                    self.serial.in_waiting or 1
                )

                if not data:
                    continue

                self.last_rx_time = time.monotonic()

                frames = self.parser.feed(data)

                for frame_type, payload in frames:

                    self.on_frame(
                        frame_type,
                        payload,
                    )

            except serial.SerialException as exc:

                print(
                    f"[SerialDriver] Serial error: {exc}"
                )

                self.running = False

            except Exception as exc:

                print(
                    f"[SerialDriver] Receive error: {exc}"
                )

        print("[SerialDriver] Receive thread stopped.")

    # ========================================================
    # 接收到完整协议帧后的回调
    # ========================================================

    def on_frame(
        self,
        frame_type: int,
        payload: bytes,
    ):

        print(
            "[SerialDriver] RX frame:",
            f"type=0x{frame_type:02X}",
            f"len={len(payload)}",
            f"data={payload.hex(' ')}",
        )

    # ========================================================
    # 发送数据
    # ========================================================

    def send(self, data: bytes):

        if self.serial is None or not self.serial.is_open:

            raise RuntimeError(
                "串口尚未打开"
            )

        with self.lock:

            self.serial.write(data)
            self.serial.flush()

    # ========================================================
    # 当前连接状态
    # ========================================================

    def is_connected(self) -> bool:

        return (
            self.serial is not None
            and self.serial.is_open
            and self.running
        )

    # ========================================================
    # 最近接收时间
    # ========================================================

    def time_since_last_rx(self) -> float:

        if self.last_rx_time == 0.0:
            return float("inf")

        return (
            time.monotonic()
            - self.last_rx_time
        )

    # ========================================================
    # 关闭串口
    # ========================================================

    def close(self):

        self.running = False

        if self.receive_thread is not None:

            self.receive_thread.join(
                timeout=1.0
            )

            self.receive_thread = None

        if self.serial is not None:

            try:
                if self.serial.is_open:
                    self.serial.close()

            except Exception:
                pass

            self.serial = None

        print("[SerialDriver] Serial port closed.")


# ============================================================
# 独立测试
# ============================================================

def main():

    print(
        "=== STM32 Serial Driver Test ==="
    )

    driver = SerialDriver(
        device="/dev/ttyACM0",
        baudrate=115200,
    )

    try:

        driver.open()

        print(
            "[TEST] Serial connected."
        )

        print(
            "[TEST] Listening for incoming data..."
        )

        print(
            "[TEST] No CMD_VEL will be sent."
        )

        # 只监听 10 秒
        for i in range(10):

            time.sleep(1)

            if driver.is_connected():

                print(
                    f"[TEST] {i + 1}s "
                    f"connected=True "
                    f"last_rx="
                    f"{driver.time_since_last_rx():.3f}s"
                )

            else:

                print(
                    f"[TEST] {i + 1}s "
                    f"connected=False"
                )

    except KeyboardInterrupt:

        print(
            "[TEST] Interrupted by user."
        )

    except Exception as exc:

        print(
            f"[TEST] Failed: {exc}"
        )

    finally:

        driver.close()

        print(
            "=== Test Finished ==="
        )


if __name__ == "__main__":
    main()
