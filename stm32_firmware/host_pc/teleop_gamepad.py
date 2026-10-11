# -*- coding: utf-8 -*-
"""
遥控手动控制 STM32 麦克纳姆小车
================================
通过 USB / 蓝牙手柄(游戏手柄)读取摇杆, 按协议组包 CMD_VEL 发送到小车。

协议(与 applications/protocol.h 一致):
  帧: AA 55 | VER=01 | TYPE | LEN(2,LE) | DATA | CRC16-CCITT(2,LE)
  覆盖 VER..DATA, poly 0x1021, init 0xFFFF
  CMD_VEL (TYPE=0x01): payload = vx(f32) vy(f32) omega(f32), LEN=12
    vx/vy: m/s   [-1.0, 1.0]  正为前进/左移
    omega: rad/s [-1.0, 1.0]  正为逆时针
  IMU     (TYPE=0x04): payload = ax..gz 各 int32 LE, 物理量放大1000倍, LEN=24
    ax,ay,az 单位 mg(÷1000 = g); gx,gy,gz 单位 m°/s(÷1000 = °/s)

默认摇杆映射(可按你的手柄修改):
  左摇杆 Y(轴1) : 前进/后退
  左摇杆 X(轴0) : 左右横移
  右摇杆 X(轴2) : 原地旋转
  按键 0 : 急停
  按键 1 : 按住加速 x2

依赖: pip install pyserial pygame
运行: python teleop_gamepad.py                    (自动找串口)
      python teleop_gamepad.py --port COM5
      python teleop_gamepad.py --list             (列出串口/手柄)
"""

import argparse
import struct
import sys
import time

try:
    import pygame
except ImportError:
    sys.exit("[ERR] 缺少 pygame, 请先: pip install pygame")

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("[ERR] 缺少 pyserial, 请先: pip install pyserial")

# ---------------------------------------------------------------- 协议常量
SOF0, SOF1, VER = 0xAA, 0x55, 0x01
TYPE_CMD_VEL = 0x01
TYPE_ENCODER = 0x02
TYPE_IMU = 0x04
LEN_CMD_VEL = 12
LEN_ENCODER = 20
LEN_IMU = 24

AB = 0.178  # (轴距/2 + 轮距/2), 与 motion_ctrl.c mecanum_calc 一致, 单位 m


# ---------------------------------------------------------------- 摇杆映射
AXIS_FORWARD = 1    # 左摇杆 Y
AXIS_STRAFE = 0     # 左摇杆 X
AXIS_ROTATE = 3     # 右摇杆 X (北通D2Z XInput模式, Xbox360布局: 0=LX 1=LY 2=LT 3=RX 4=RY 5=RT)
DEADZONE = 0.08
SPEED_FORWARD = 1.0  # 最大前速 m/s
SPEED_STRAFE = 1.0   # 最大横移 m/s
SPEED_ROTATE = 1.0   # 最大旋转 rad/s
BTN_ESTOP = 0
BTN_BOOST = 1        # 按住加速

BAUD = 115200
LOOP_PERIOD = 0.05       # 50Hz 发送(STM32 超时停车 500ms)
# 注意: 不用"事件超时停车"。pygame 仅当摇杆数值变化才发事件,
# 持续推住摇杆 = 无事件, 超时停车会造成一顿一顿。改为真实拔出检测。
MONITOR_INTERVAL = 1.0   # 编码器回传打印间隔(秒)


# ---------------------------------------------------------------- CRC16/组包
def crc16_ccitt(data, seed=0xFFFF):
    crc = seed & 0xFFFF
    for b in data:
        crc ^= (b << 8) & 0xFFFF
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_cmd_vel(vx, vy, omega):
    payload = struct.pack("<fff", vx, vy, omega)
    type_len = bytes([TYPE_CMD_VEL]) + struct.pack("<H", LEN_CMD_VEL)
    crc = crc16_ccitt(bytes([VER]) + type_len + payload)
    return bytes([SOF0, SOF1, VER]) + type_len + payload + struct.pack("<H", crc)


# ---------------------------------------------------------------- 运动学安全限幅
def clamp_kinematic(vx, vy, omega):
    """按麦克纳姆反解, 若任一轮速超 1m/s 则整体等比缩放, 避免 STM32 端硬截断造成偏航。"""
    w1 = vx - vy - omega * AB
    w2 = vx + vy - omega * AB
    w3 = vx + vy + omega * AB
    w4 = vx - vy + omega * AB
    m = max(1.0, abs(w1), abs(w2), abs(w3), abs(w4))
    if m > 1.0:
        return vx / m, vy / m, omega / m
    return vx, vy, omega


def apply_deadzone(v, dz=DEADZONE):
    return 0.0 if abs(v) < dz else v


# ---------------------------------------------------------------- 回传帧解析(带缓冲重同步)
class FrameParser:
    def __init__(self):
        self.buf = bytearray()
        self.last_counts = [0, 0, 0, 0]

    def feed(self, data):
        """吃进串口数据, 返回解析出的 [(type, payload), ...]"""
        frames = []
        self.buf += data
        while True:
            idx = self.buf.find(bytes([SOF0, SOF1, VER]))
            if idx < 0:
                if len(self.buf) > 64:
                    del self.buf[:32]
                return frames
            if idx > 0:
                del self.buf[:idx]
            if len(self.buf) < 6:
                return frames
            ln = struct.unpack_from("<H", self.buf, 4)[0]
            total = 6 + ln + 2
            if len(self.buf) < total:
                return frames
            frame = bytes(self.buf[:total])
            del self.buf[:total]
            typ = frame[3]
            payload = frame[6:6 + ln]
            crc = struct.unpack_from("<H", frame, 6 + ln)[0]
            if crc16_ccitt(bytes([VER]) + frame[3:6] + payload) == crc:
                frames.append((typ, payload))
            # 校验失败则丢帧, 循环重同步


# ---------------------------------------------------------------- 串口选择
def pick_serial(args):
    if args.port:
        return serial.Serial(args.port, BAUD, timeout=0.1)
    ports = list(list_ports.comports())
    for p in ports:
        if any(k in p.description.upper() for k in ("CH9102", "CH340", "CP210", "USB-SERIAL", "USB SERIAL")):
            return serial.Serial(p.device, BAUD, timeout=0.1)
    if ports:
        return serial.Serial(ports[0].device, BAUD, timeout=0.1)
    raise SystemExit("[ERR] 未找到串口, 请用 --port COMx 指定")


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="用游戏手柄遥控麦克纳姆小车")
    ap.add_argument("--port", help="串口, 如 COM5")
    ap.add_argument("--list", action="store_true", help="列出串口和手柄")
    args = ap.parse_args()

    if args.list:
        print("== 串口 ==")
        for p in list(list_ports.comports()):
            print(" ", p.device, p.description)
        print("== 手柄 ==")
        pygame.init()
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            j.init()
            print(f"  [{i}] {j.get_name()}  axes={j.get_numaxes()} buttons={j.get_numbuttons()}")
        return

    ser = pick_serial(args)
    print(f"[SYS] 串口 {ser.port} @ {BAUD} 已打开")

    pygame.init()
    pygame.joystick.init()

    # 手柄/接收器枚举可能有延迟: 轮询最长 10s
    joy = None
    for _ in range(20):
        pygame.event.pump()
        pygame.joystick.init()
        if pygame.joystick.get_count() > 0:
            joy = pygame.joystick.Joystick(0)
            joy.init()
            break
        time.sleep(0.5)
    if joy is None:
        pygame.quit()
        ser.close()
        sys.exit("[ERR] 未检测到手柄, 请插入 USB/蓝牙手柄后重试")
    print(f"[SYS] 手柄: {joy.get_name()}")
    print("[SYS] 开始遥控: 左摇杆=前进/横移, 右摇杆X=旋转, 按键0=急停, 按键1=加速x2, Ctrl+C=退出")

    parser = FrameParser()
    last_monitor = 0.0
    last_imu_monitor = 0.0
    estop = False
    frame_count = 0
    joy_missing_warned = False

    try:
        while True:
            pygame.event.pump()
            for ev in pygame.event.get():
                if ev.type == pygame.JOYBUTTONDOWN and ev.button == BTN_ESTOP:
                    estop = not estop
                    print("[CTRL] 急停" if estop else "[CTRL] 解除急停")

            # 默认停止
            vx = vy = omega = 0.0

            if not estop:
                try:
                    fx = apply_deadzone(joy.get_axis(AXIS_FORWARD))
                    fy = apply_deadzone(joy.get_axis(AXIS_STRAFE))
                    fr = apply_deadzone(joy.get_axis(AXIS_ROTATE))
                    boost = 2.0 if joy.get_button(BTN_BOOST) else 1.0
                except pygame.error:
                    # 手柄真实拔出: 停车, 并等待重新插入后自动恢复
                    if not joy_missing_warned:
                        print("[WARN] 手柄断开, 已停车, 等待重新插入...")
                        joy_missing_warned = True
                    pygame.joystick.quit()
                    pygame.joystick.init()
                    if pygame.joystick.get_count() > 0:
                        joy = pygame.joystick.Joystick(0)
                        joy.init()
                        print("[SYS] 手柄已重新连接:", joy.get_name())
                        joy_missing_warned = False
                else:
                    vx = -fx * SPEED_FORWARD * boost   # pygame 上=-1 -> 前进为正
                    vy = fy * SPEED_STRAFE * boost
                    omega = fr * SPEED_ROTATE * boost
                    vx = max(-SPEED_FORWARD, min(SPEED_FORWARD, vx))
                    vy = max(-SPEED_STRAFE, min(SPEED_STRAFE, vy))
                    omega = max(-SPEED_ROTATE, min(SPEED_ROTATE, omega))

            vx, vy, omega = clamp_kinematic(vx, vy, omega)
            ser.write(build_cmd_vel(vx, vy, omega))
            frame_count += 1

            # 处理回传(编码器计数/IMU), 周期打印
            n = ser.in_waiting
            if n:
                for typ, payload in parser.feed(ser.read(n)):
                    if typ == TYPE_ENCODER and len(payload) >= LEN_ENCODER:
                        counts = struct.unpack_from("<4i", payload, 4)
                        if time.time() - last_monitor > MONITOR_INTERVAL:
                            print(f"[ENC] FL={counts[0]} RL={counts[1]} FR={counts[2]} RR={counts[3]}")
                            last_monitor = time.time()
                    elif typ == TYPE_IMU and len(payload) >= LEN_IMU:
                        ax, ay, az, gx, gy, gz = (v / 1000.0 for v in struct.unpack_from("<6i", payload, 0))
                        if time.time() - last_imu_monitor > MONITOR_INTERVAL:
                            print(f"[IMU] aX={ax:+.3f}g aY={ay:+.3f}g aZ={az:+.3f}g | "
                                  f"gX={gx:+.3f} gY={gy:+.3f} gZ={gz:+.3f} deg/s")
                            last_imu_monitor = time.time()

            time.sleep(LOOP_PERIOD)
    except KeyboardInterrupt:
        print("\n[SYS] 退出中...")
    finally:
        try:
            ser.write(build_cmd_vel(0.0, 0.0, 0.0))
        except Exception:
            pass
        ser.close()
        pygame.quit()
        print(f"[SYS] 已发送 {frame_count} 帧, 串口已关闭")


if __name__ == "__main__":
    main()