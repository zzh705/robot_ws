#!/usr/bin/env python3
"""encoder_calib.py — 编码器标定 / 轮子方向(极性)验证

为什么需要它
    /odom 准不准 = 轮径 × TICKS_PER_REV(每转脉冲数) × 四轮符号 三件事都对。
    轮径 0.097m 与四轮符号有实测记录，但 TICKS_PER_REV 现在有两个"真值"：
        encoder.py : 122758  (悬空反推标定)
        pulse.h    : 122880  (1024线 × 4倍频 × 减速比30)
    本脚本用「多个速度互相自洽」的方式重新标定：若 cmd_vel 的单位解释正确，
    不同速度反推出的 TICKS_PER_REV 应当一致；不一致说明中间有单位/换算错误。

两种模式
    count   不驱动电机，只统计四轮脉冲增量。配合 --distance 做
            "用手把车推一段已知距离" 的绝对标定（无打滑，最准）。
    drive   以给定速度驱动底盘若干秒再停。
            ⚠ 轮子会转！请先架空，或确认车前 1m 内无人无障碍。

用法
    python3 scripts/encoder_calib.py --mode count --seconds 6
    python3 scripts/encoder_calib.py --mode count --seconds 8 --distance 1.0
    python3 scripts/encoder_calib.py --mode drive --speeds 0.10,0.20,0.30
"""
import argparse
import math
import sys
import time

import serial

sys.path.insert(0, '/home/sunrise/robot_ws/src/stm32_bridge/stm32_bridge')
from protocol import (          # noqa: E402
    FrameParser, pack_cmd_vel, unpack_encoder, TYPE_ENCODER,
)

WHEEL_DIAMETER = 0.097                    # 实测 97mm
CIRCUMFERENCE = math.pi * WHEEL_DIAMETER  # 0.30473 m

# encoder.py 里记录的既有符号（2026-09-19 实测）
EXPECTED_SIGN = {'fl': '+', 'rl': '-', 'fr': '-', 'rr': '+'}


class Collector:
    """收 ENCODER 帧，记录首末计数与时间。"""

    def __init__(self):
        self.parser = FrameParser()
        self.t0 = None
        self.t1 = None
        self.first = None
        self.last = None
        self.frames = 0

    def feed(self, blob):
        for ftype, payload in self.parser.feed(blob):
            if ftype != TYPE_ENCODER:
                continue
            enc = unpack_encoder(payload)
            now = time.time()
            if self.first is None:
                self.first = (enc.fl, enc.rl, enc.fr, enc.rr)
                self.t0 = now
            self.last = (enc.fl, enc.rl, enc.fr, enc.rr)
            self.t1 = now
            self.frames += 1

    def deltas(self):
        if self.first is None or self.last is None:
            return None
        return tuple(b - a for a, b in zip(self.first, self.last))

    def dt(self):
        if self.t0 is None or self.t1 is None:
            return 0.0
        return self.t1 - self.t0


def send_cmd(ser, vx, wz=0.0):
    ser.write(pack_cmd_vel(vx, 0.0, wz))


def stop_robot(ser, times=8):
    """兜底停车：连发若干次 0 速度（固件 500ms 无指令自停，这里再加一道保险）。"""
    for _ in range(times):
        try:
            send_cmd(ser, 0.0, 0.0)
            time.sleep(0.05)
        except Exception:
            break


def run_segment(ser, seconds, speed=None, wz=0.0):
    """跑一段：speed=None 表示不驱动（count 模式）。返回 Collector。"""
    c = Collector()
    t_end = time.time() + seconds
    next_cmd = 0.0
    while time.time() < t_end:
        if speed is not None and time.time() >= next_cmd:
            send_cmd(ser, speed, wz)
            next_cmd = time.time() + 0.05
        try:
            data = ser.read(128)
        except Exception as e:
            print(f'  串口读失败: {e}')
            break
        if data:
            c.feed(data)
    return c


def report_deltas(c, seconds):
    d = c.deltas()
    if d is None:
        print('  !! 这段时间没收到 ENCODER 帧（串口没数据 / 下位机没发）')
        return None, None
    dt = c.dt() or seconds
    names = ('fl', 'rl', 'fr', 'rr')
    print(f'  帧数={c.frames}  测量时长={dt:.2f}s')
    print('  轮子   脉冲增量     脉冲/秒     符号')
    for n, v in zip(names, d):
        print(f'  {n:>3}  {v:>10}  {v / dt:>10.1f}   {"+" if v > 0 else "-"}')
    return d, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='/dev/robot_stm32')
    ap.add_argument('--mode', choices=['count', 'drive'], default='count')
    ap.add_argument('--seconds', type=float, default=4.0)
    ap.add_argument('--speeds', default='0.10,0.20,0.30',
                    help='drive 模式要试的速度列表 m/s')
    ap.add_argument('--distance', type=float, default=0.0,
                    help='count 模式：你推车的距离(m)，给了就算 TICKS_PER_REV')
    ap.add_argument('--wz', type=float, default=0.0, help='drive 时附加的角速度')
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, 115200, timeout=0.2)
    except Exception as e:
        print(f'打不开 {args.port}: {e}')
        return 1

    print(f'== 打开 {args.port} ==')
    print(f'轮径 {WHEEL_DIAMETER} m, 周长 {CIRCUMFERENCE:.5f} m')

    try:
        if args.mode == 'count':
            print(f'\n== count 模式：不驱动电机，请「用手把车沿直线推」，'
                  f'{args.seconds:.0f}s 内推完 ==')
            if args.distance:
                print(f'   目标距离 {args.distance} m（推完正好停下）')
            else:
                print('   （这次只统计脉冲；下次带 --distance 给出距离即可算出 TICKS_PER_REV）')
            c = run_segment(ser, args.seconds)
            d, dt = report_deltas(c, args.seconds)
            if d and args.distance:
                revs = args.distance / CIRCUMFERENCE
                names = ('fl', 'rl', 'fr', 'rr')
                ests = [abs(v) / revs for v in d]
                print(f'\n== 标定结果（推了 {args.distance} m = {revs:.3f} 圈）==')
                for n, v, e in zip(names, d, ests):
                    print(f'  {n:>3}: {abs(v)} 脉冲 / {revs:.3f} 圈 = '
                          f'{e:,.0f} 脉冲/圈')
                mean = sum(ests) / 4.0
                spread = (max(ests) - min(ests)) / mean * 100
                print(f'  四轮平均 TICKS_PER_REV = {mean:,.0f} '
                      f'(最大最小差 {spread:.2f}%)')
                print(f'  参考: encoder.py 现用 122758 / pulse.h 设计值 122880')
        else:
            speeds = [float(s) for s in args.speeds.split(',') if s.strip()]
            print(f'\n== drive 模式：轮子会转！速度 {speeds} m/s ==')
            for sp in speeds:
                print(f'\n--- 速度 {sp:.2f} m/s，{args.seconds:.0f}s（先停 0.5s 稳定）---')
                time.sleep(0.5)
                c = run_segment(ser, args.seconds, speed=sp, wz=args.wz)
                stop_robot(ser, 4)
                d, dt = report_deltas(c, args.seconds)
                if not d:
                    continue
                v_expected = sp
                revs_per_s = v_expected / CIRCUMFERENCE
                ests = [abs(v) / dt / revs_per_s for v in d]
                print(f'  反推 TICKS_PER_REV: fl={ests[0]:,.0f} rl={ests[1]:,.0f} '
                      f'fr={ests[2]:,.0f} rr={ests[3]:,.0f}')
                mean = sum(ests) / 4.0
                spread = (max(ests) - min(ests)) / mean * 100
                print(f'  四轮平均 = {mean:,.0f}  轮间差 {spread:.1f}%')
                names = ('fl', 'rl', 'fr', 'rr')
                signs = {n: ('+' if v > 0 else '-') for n, v in zip(names, d)}
                print(f'  符号实测 {signs}')
                print(f'  符号期望 {EXPECTED_SIGN}  '
                      f'→ {"一致 ✓" if signs == EXPECTED_SIGN else "不一致 ⚠ 需修正 encoder.py 的 WHEEL_SIGN"}')
    finally:
        stop_robot(ser)
        ser.close()
        print('\n已发停止指令并关闭串口。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
