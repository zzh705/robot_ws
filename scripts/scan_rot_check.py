#!/usr/bin/env python3
"""scan_rot_check.py — 用激光自己测"车体实际转了多少/什么方向"

原理
    车静止时用激光测周围环境, 得到一个"方位角-距离"剖面 r(θ)。
    车体转过 φ 之后再看同一环境, 剖面会整体平移 −φ(环境相对车体反向转)。
    把两帧剖面做互相关, 最佳偏移量 = −φ
    → 直接给出真实旋转角与方向, 不依赖任何目测或轮速。

    约定与 ROS 一致: 从上往下看, 逆时针为正(+), 顺时针为负(−)。

用法
    python3 scripts/scan_rot_check.py --seconds 120 --interval 2
    启动后它会先记一帧基准, 之后每 interval 秒打一行:
        t=+12.0s  偏移=+90.0° 匹配=0.86  最近障碍=0.62m
    → 你在这期间慢慢转动车体即可, 转完停住, 最后几行就是结果。

判读 (注意符号: 偏移 = −车体旋转角)
    偏移 −90° → 车体逆时针(+90°, ROS 正方向)
    偏移 +90° → 车体顺时针(−90°)
    原因: 环境特征在激光系里的方位会朝车体旋转的**反方向**平移,
          所以"偏移"与"车体转角"差一个负号。
    匹配 < 0.5   → 结果不可信(视野太单调/被挡住), 换个附近有家具的朝向重测
    若过程中偏移单调增大/减小并跨过 ±180°, 按跨过前的一致方向累加
    (例如 0→+175→−179→−171 实际是 +189°, 不是 −171°)。
"""
import argparse
import math
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan

BINS = 360            # 1° 一格
TOL = 0.15            # 认为"同一面墙"的距离容差 m


class RotCheck(Node):
    def __init__(self):
        super().__init__('scan_rot_check')
        self.scan = None
        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)

    def on_scan(self, msg):
        self.scan = msg

    def profile(self):
        """返回 (360 bins 最小距离, 最近障碍距离); 无数据 → (None, None)."""
        s = self.scan
        if s is None:
            return None, None
        prof = np.full(BINS, np.nan)
        nearest = 99.0
        for i, r in enumerate(s.ranges):
            if not math.isfinite(r) or r <= 0.05:
                continue
            nearest = min(nearest, r)
            a = math.degrees(s.angle_min + s.angle_increment * i) % 360.0
            b = int(a) % BINS
            if math.isnan(prof[b]) or r < prof[b]:
                prof[b] = r
        return prof, nearest


def best_shift(p0, p1):
    """求 p1 相对 p0 的最佳方位偏移(度, -180..180)与匹配率."""
    best = (None, -1.0, [])
    scores = []
    for sh in range(-180, 181):
        idx = (np.arange(BINS) + sh) % BINS
        a, b = p0, p1[idx]
        ok = ~np.isnan(a) & ~np.isnan(b)
        if ok.sum() < 60:            # 有效重叠太少, 跳过
            continue
        match = float(np.mean(np.abs(a[ok] - b[ok]) < TOL))
        scores.append((sh, match))
        if match > best[1]:
            best = (sh, match, scores)
    # 次优峰(相隔 >20° 的另一个候选), 用来判断是否有多解
    second = None
    if best[0] is not None:
        for sh, m in sorted(scores, key=lambda kv: -kv[1]):
            if abs(sh - best[0]) > 20:
                second = (sh, round(m, 2))
                break
    return best[0], round(best[1], 2), second


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=120.0, help='采集总时长')
    ap.add_argument('--interval', type=float, default=2.0, help='打点间隔 s')
    args = ap.parse_args()

    rclpy.init()
    node = RotCheck()
    print('等待 /scan ...', flush=True)
    t_wait = time.time() + 8.0
    while time.time() < t_wait and node.scan is None:
        rclpy.spin_once(node, timeout_sec=0.1)
    if node.scan is None:
        print('!! 收不到 /scan, 雷达没在跑?')
        return 1

    p0, near0 = node.profile()
    t0 = node.get_clock().now().nanoseconds / 1e9
    print(f'基准已记录: 最近障碍={near0:.2f}m  (ros_t={t0:.1f})', flush=True)
    print('>> 现在开始慢慢转动车体, 转完停住 <<', flush=True)

    t_end = time.time() + args.seconds
    while time.time() < t_end:
        rclpy.spin_once(node, timeout_sec=0.2)
        time.sleep(args.interval)
        p1, near1 = node.profile()
        if p1 is None:
            continue
        sh, match, second = best_shift(p0, p1)
        t = node.get_clock().now().nanoseconds / 1e9
        extra = f' 次优候选={second}' if second else ''
        print(f't=+{t - t0:5.1f}s ros_t={t:.1f} 偏移={sh:+4d}° '
              f'匹配={match:.2f} 最近障碍={near1:.2f}m{extra}', flush=True)

    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
