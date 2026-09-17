#!/usr/bin/env python3
"""
fake_stm.py — 用 pty 伪终端模拟 STM32，向串口以 30Hz 发送 ENCODER 帧。

用法：
    python3 /home/sunrise/robot_ws/scripts/fake_stm.py

原理：
    创建一对 pty（master/slave），模拟器把协议帧写到 master 一侧，
    slave 一侧会当成串口读到。测试时把 stm32_bridge_node 的 port 指向
    打印出来的 slave 设备路径。

    与真实 STM32 完全等价，只是数据是假的：
      模拟"前进"：四个轮 count 持续增加，速度在 0.25 m/s 附近。
"""

import os
import pty
import time
import sys

sys.path.insert(0, '/home/sunrise/robot_ws/src/stm32_bridge/stm32_bridge')
from protocol import pack_encoder

MASTER, SLAVE = pty.openpty()
SLAVE_NAME = os.ttyname(SLAVE)

print("=" * 50, flush=True)
print(f"[FAKE-STM] slave 串口设备: {SLAVE_NAME}", flush=True)
print("[FAKE-STM] 把 stm32_bridge 的 port 参数指到这里", flush=True)
print("[FAKE-STM] 正在以 30Hz 模拟'前进'的编码器数据...", flush=True)
print("=" * 50, flush=True)

# 把地址写入固定文件，供测试脚本自动读取，避免手动抄错
with open('/tmp/fake_port.txt', 'w') as fp:
    fp.write(SLAVE_NAME)
print(f"[FAKE-STM] 已写入 /tmp/fake_port.txt = {SLAVE_NAME}", flush=True)

t = 0  # 时间戳（毫秒）
count = 0  # 累计编码器计数

try:
    while True:
        # 模拟前进：编码器计数每 0.1s 增加 30
        # 对应速度 ≈ 30/0.1/1440*0.3047 ≈ 0.25 m/s
        count += 3
        frame = pack_encoder(t, count, count, count, count)
        os.write(MASTER, frame)
        t += 33
        time.sleep(0.033)
except KeyboardInterrupt:
    print("[FAKE-STM] 停止模拟")
finally:
    os.close(MASTER)
    os.close(SLAVE)