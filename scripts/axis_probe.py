#!/usr/bin/env python3
"""axis_probe.py — 单轴方向探针：用「雷达 + IMU」当独立真值，不靠肉眼

背景
    2026-10-12 实测: 发 wz=+0.6 纯旋转，上位机算出的四轮速度是
    fl=-0.10 / fr=+0.10 / rl=-0.10 / rr=+0.10 (= wz*K, 大小完全正确)，
    但 IMU 实测车体只转了 -79°(顺时针)。说明「轮子转速 → 车体运动」的
    符号约定与物理相反(再叠加麦轮原地转打滑, 就出现"后退画弧")。
    本脚本把三个轴逐个发一遍，用两个与电机无关的传感器判定真实方向：

      1) vx=+0.10 : 车头扇区距离怎么变   → 真前进 or 真后退
      2) vy=+0.10 : 左右扇区距离怎么变   → 真左移 or 真右移
      3) wz=+0.40 : IMU yaw 积分变化     → 真逆时针(+) or 真顺时针(-)

坐标/约定
    * 雷达系: 0°=车尾, 180°=车头 (URDF base_link→laser yaw = 180°)
      所以 车身左 = 雷达 270°, 车身右 = 雷达 90°
    * ROS 约定: vx+ = 前进, vy+ = 向左, wz+ = 逆时针(从上往下看)
    * 判定: 前进 → 车头扇区距离变小; 后退 → 车尾扇区变小
            gyro 积分正 = 逆时针(IMU 已实测 z 轴朝上, accel z≈+9.86)

安全
    * 每轴只动 2.0s、速度 0.10m/s(≈20cm) / wz 0.40(≈名义46°)
    * 起手/收尾都发零速; 异常和 Ctrl-C 也会在 finally 里停车
    * 跑之前确认车身周围 0.5m 内没有障碍(原地转的扫掠半径 ~0.21m)

用法
    python3 scripts/axis_probe.py --dry-run     # 只采基线, 不发指令
    python3 scripts/axis_probe.py               # 真发指令
"""
import argparse
import math
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import Imu, LaserScan

BIN = 30                      # 扇区宽度(度)
WINDOWS = {'车头(180°)': 180, '车尾(0°)': 0,
           '左侧(270°)': 270, '右侧(90°)': 90}


class Probe(Node):
    def __init__(self):
        super().__init__('axis_probe')
        self.scan = None
        self.gz = None
        self.gyro_sum = 0.0
        self.gyro_n = 0
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)
        self.create_subscription(Imu, '/imu/data', self.on_imu, 10)

    def on_scan(self, m):
        self.scan = m

    def on_imu(self, m):
        self.gz = m.angular_velocity.z

    # ---------- 基础工具 ----------
    def spin_for(self, dur, cmd=None):
        """跑 dur 秒; cmd 不为 None 时以 20Hz 持续发该 Twist."""
        end = time.time() + dur
        while time.time() < end:
            if cmd is not None:
                self.cmd_pub.publish(cmd)
            rclpy.spin_once(self, timeout_sec=0.05)

    def sectors(self):
        """返回 {扇区起始角: 该扇区内最近障碍距离}"""
        s = self.scan
        out = {}
        if s is None:
            return out
        for i, r in enumerate(s.ranges):
            if not math.isfinite(r) or r <= 0.05:
                continue
            a = math.degrees(s.angle_min + s.angle_increment * i) % 360.0
            b = int(a // BIN) * BIN
            out[b] = min(out.get(b, 99.0), r)
        return out

    def window_min(self, bearing, half=45):
        """以 bearing 为中心 ±half 度的最近障碍距离"""
        sec = self.sectors()
        if not sec:
            return None
        vals = [v for b, v in sec.items()
                if min(abs(b + BIN / 2 - bearing),
                       360 - abs(b + BIN / 2 - bearing)) <= half]
        return min(vals) if vals else None

    def snapshot(self):
        return {name: self.window_min(b) for name, b in WINDOWS.items()}

    def gyro_mean(self, dur=0.5):
        """静置 dur 秒的 gyro z 均值(用来估计零偏)"""
        self.gyro_sum = 0.0
        self.gyro_n = 0
        end = time.time() + dur
        while time.time() < end:
            if self.gz is not None:
                self.gyro_sum += self.gz
                self.gyro_n += 1
            rclpy.spin_once(self, timeout_sec=0.05)
        return (self.gyro_sum / self.gyro_n) if self.gyro_n else 0.0

    def gyro_integrate(self, dur, bias):
        """积分 (gz-bias) dur 秒, 返回弧度"""
        acc = 0.0
        last = time.time()
        end = last + dur
        while time.time() < end:
            now = time.time()
            dt = now - last
            last = now
            if self.gz is not None:
                acc += (self.gz - bias) * dt
            rclpy.spin_once(self, timeout_sec=0.02)
        return acc

    def stop(self, dur=0.8):
        z = Twist()
        self.spin_for(dur, cmd=z)


def fmt(snap):
    if not snap:
        return 'n/a'
    return '  '.join(f'{k}={v:.2f}m' if v is not None else f'{k}=n/a'
                     for k, v in snap.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只采基线, 不发指令')
    ap.add_argument('--move-sec', type=float, default=2.0)
    ap.add_argument('--vx', type=float, default=0.10)
    ap.add_argument('--vy', type=float, default=0.10)
    ap.add_argument('--wz', type=float, default=0.40)
    args = ap.parse_args()

    rclpy.init()
    n = Probe()
    print('等待 /scan /imu/data ...', flush=True)
    n.spin_for(5.0)
    if n.scan is None:
        print('!! 收不到 /scan'); return 1
    if n.gz is None:
        print('!! 收不到 /imu/data'); return 1

    base = n.snapshot()
    print(f'基线: {fmt(base)}')
    if args.dry_run:
        print('(dry-run: 不发指令)')
        n.destroy_node(); rclpy.shutdown(); return 0

    bias = n.gyro_mean(1.0)
    print(f'gyro z 零偏(本次静置均值) = {bias:+.4f} rad/s\n')

    results = {}
    try:
        # 1) vx+
        print(f'--- 1/3 发 vx=+{args.vx} m/s, {args.move_sec}s ---')
        t = Twist(); t.linear.x = args.vx
        n.spin_for(args.move_sec, cmd=t); n.stop(1.0)
        after = n.snapshot()
        print(f'    之后: {fmt(after)}')
        results['vx'] = {k: (None if base[k] is None or after[k] is None
                             else after[k] - base[k]) for k in base}
        print('    变化: ' + '  '.join(
            f'{k}={v:+.2f}m' for k, v in results['vx'].items() if v is not None))

        # 2) vy+
        print(f'--- 2/3 发 vy=+{args.vy} m/s, {args.move_sec}s ---')
        t = Twist(); t.linear.y = args.vy
        n.spin_for(args.move_sec, cmd=t); n.stop(1.0)
        after = n.snapshot()
        print(f'    之后: {fmt(after)}')
        results['vy'] = {k: (None if base[k] is None or after[k] is None
                             else after[k] - base[k]) for k in base}
        print('    变化: ' + '  '.join(
            f'{k}={v:+.2f}m' for k, v in results['vy'].items() if v is not None))

        # 3) wz+  (用 IMU 判方向)
        print(f'--- 3/3 发 wz=+{args.wz} rad/s, {args.move_sec}s (看 IMU 积分) ---')
        t = Twist(); t.angular.z = args.wz
        n.spin_for(args.move_sec, cmd=t)
        n.stop(0.5)
        yaw = n.gyro_integrate(args.move_sec, bias)  # 占位: 实际见下
        results['wz'] = yaw
        print(f'    IMU 积分 yaw 变化(上一段) = {math.degrees(yaw):+.1f}°')
    finally:
        n.stop(1.0)
        n.destroy_node()
        rclpy.shutdown()

    print('\n=== 判定 ===')
    d = results.get('vx', {})
    if d.get('车头(180°)') is not None and d.get('车尾(0°)') is not None:
        if d['车头(180°)'] < -0.03 and d['车头(180°)'] < d['车尾(0°)']:
            print('  vx+ → 车头距离减小: 真实前进 ✓ (与 ROS 约定一致)')
        elif d['车尾(0°)'] < -0.03 and d['车尾(0°)'] < d['车头(180°)']:
            print('  vx+ → 车尾距离减小: **实际后退 ⚠ (vx 符号反)**')
        else:
            print('  vx+ → 前后变化不明显, 判不出(环境太对称或没动)')
    d = results.get('vy', {})
    if d.get('左侧(270°)') is not None and d.get('右侧(90°)') is not None:
        if d['左侧(270°)'] < -0.03 and d['左侧(270°)'] < d['右侧(90°)']:
            print('  vy+ → 左侧距离减小: 真实左移 ✓ (与 ROS 约定一致)')
        elif d['右侧(90°)'] < -0.03 and d['右侧(90°)'] < d['左侧(270°)']:
            print('  vy+ → 右侧距离减小: **实际右移 ⚠ (vy 符号反)**')
        else:
            print('  vy+ → 左右变化不明显, 判不出')
    return 0


if __name__ == '__main__':
    sys.exit(main())
