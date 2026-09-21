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

import os
import glob
import threading
import time

import serial

from .protocol import FrameParser


class LinkDownError(RuntimeError):
    """串口链路已断(拔线 / USB 重新枚举 / 写失败)。

    继承 RuntimeError 以兼容既有捕获; 调用方应捕获它后继续运行,
    **不要**让它冒到 rclpy 回调之外——那会顺着 executor 杀掉整个节点进程。
    实测: 写失败 `[Errno 5] Input/output error` 未捕获时, 节点直接退出码 1。
    """


def auto_detect_port(verbose: bool = False):
    """自动找 STM32 串口(USB 重新枚举后 ttyACM0 可能变成 ttyACM1)。

    优先级:
      1) /dev/robot_stm32             udev 稳定别名(推荐)
      2) /dev/serial/by-id/*1a86_*    按芯片匹配(1a86 = CH343/CH340), 与 ttyACM 编号无关
      3) 第一个 /dev/ttyACM*
    故意不含 /dev/ttyUSB*(那是雷达 CP2102)。
    """

    if os.path.exists("/dev/robot_stm32"):
        return "/dev/robot_stm32"

    for path in sorted(glob.glob("/dev/serial/by-id/*1a86_*")):
        if os.path.exists(path):
            if verbose:
                print(f"[SerialDriver] 自动探测: by-id 命中 {path}")
            return path

    acms = sorted(glob.glob("/dev/ttyACM*"))
    if acms:
        if verbose:
            print(f"[SerialDriver] 自动探测: 用第一个 ACM 口 {acms[0]}")
        return acms[0]

    return None


class SerialDriver:
    """
    STM32 串口驱动。

    当前默认：

        device = /dev/robot_stm32
        baudrate = 115200
        8N1
    """

    def __init__(
        self,
        device: str = "/dev/robot_stm32",
        baudrate: int = 115200,
        timeout: float = 0.1,
        device_resolver=None,
        reconnect_interval: float = 1.0,
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

        # ---- 链路自愈 ----
        # USB 重新枚举后设备名会变(ttyACM0 -> ttyACM1), 所以不能只认死原路径
        self.device_resolver = device_resolver or (lambda: auto_detect_port())
        self.reconnect_interval = reconnect_interval
        self.reconnect_count = 0
        self.last_error = None
        self._stop = threading.Event()
        self._supervisor = None

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

        # 路径不在时先重新解析一次(USB 重新枚举后 ttyACM0 会变成 ttyACM1)
        if not os.path.exists(self.device):
            resolved = self.device_resolver()
            if resolved:
                self.device = resolved

        # 启动前预检: 设备不存在时给出可操作的报错, 而不是让 serial.Serial 抛底层异常
        if not os.path.exists(self.device):
            raise FileNotFoundError(
                f"串口设备不存在: {self.device} | "
                "① STM32 是否已插好并上电 (ls -l /dev/ttyACM*) | "
                "② udev 规则 /etc/udev/rules.d/99-robot.rules 依赖 ttyACM* + 1a86:55d4, "
                "可用 lsusb / ls /dev/serial/by-id 核对 | "
                "③ 临时指定其它口: ros2 launch stm32_bridge stm32_bridge.launch.py "
                "port:=/dev/ttyACM0"
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
        self.last_error = None

        # 只在线程确实不在时新建, 避免重连时堆线程
        if self.receive_thread is None or not self.receive_thread.is_alive():

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

        # 用 _stop 而不是 running 作为条件: 链路断开时 running 会变 False,
        # 但线程必须活到重连成功之后, 否则重连了也没人收数据
        while not self._stop.is_set():

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
                    f"[SerialDriver] Serial error (将自动重连): {exc}"
                )

                self._link_down(exc)

                time.sleep(0.5)

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

        with self.lock:

            if self.serial is None or not self.serial.is_open:

                raise LinkDownError(
                    "串口未打开(链路已断, 正在自动重连)"
                )

            try:

                self.serial.write(data)
                self.serial.flush()

            except Exception as exc:

                # 关键: 抛给调用方的是可捕获的 LinkDownError,
                # 而不是让 serial.SerialException 穿透 rclpy 回调杀掉节点
                self._link_down(exc)

                raise LinkDownError(
                    f"串口写失败: {exc}"
                ) from exc

    # ========================================================
    # 链路故障与自动重连
    # ========================================================

    def _link_down(self, exc):
        """统一处理链路故障: 记录原因、关掉句柄, 交给看护线程重连。

        注意: 不在这里取 self.lock —— send() 已经持有它, 再取会死锁。
        """

        self.last_error = f"{type(exc).__name__}: {exc}"
        self.running = False

        try:
            if self.serial is not None and self.serial.is_open:
                self.serial.close()
        except Exception:
            pass

        self.serial = None

    def start_auto_reconnect(self):
        """启动看护线程: 链路断了就按 reconnect_interval 反复尝试重连。"""

        if self._supervisor is not None and self._supervisor.is_alive():
            return

        self._stop.clear()

        self._supervisor = threading.Thread(
            target=self._supervise_loop,
            daemon=True,
        )

        self._supervisor.start()

    def _supervise_loop(self):

        while not self._stop.is_set():

            self._stop.wait(self.reconnect_interval)

            if self._stop.is_set():
                break

            if self.is_connected():
                continue

            try:

                resolved = self.device_resolver()

                if resolved:
                    self.device = resolved

                self.open()

                self.reconnect_count += 1

                print(
                    f"[SerialDriver] Reconnected: {self.device} "
                    f"(第 {self.reconnect_count} 次重连, 上次错误: {self.last_error})"
                )

            except Exception as exc:

                self.last_error = f"{type(exc).__name__}: {exc}"

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
        self._stop.set()

        if self._supervisor is not None:

            self._supervisor.join(timeout=1.0)

            self._supervisor = None

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
        device="/dev/robot_stm32",
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
