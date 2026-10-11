#!/usr/bin/env python3
"""map_dump.py — 把 /map 拉成文字分析（不用 rviz 也能看建图结果）

输出：
  1. 栅格元信息（分辨率 / 尺寸 / 原点 / 实际范围）
  2. 各类栅格计数（occupied / free / unknown）
  3. 占用格在 x、y 方向的分布直方图（墙会形成尖峰；"重影墙"会形成多个尖峰）
  4. ASCII 预览（# 占用、. 空闲、空格未知，向上为机器人初始朝向）

用法：python3 map_dump.py [ASCII 列数, 默认 96]
"""
import sys

import rclpy
from rclpy.node import Node
from nav_msgs.msg import OccupancyGrid

COLS = int(sys.argv[1]) if len(sys.argv) > 1 else 96


def main():
    rclpy.init()
    node = rclpy.create_node('map_dump')
    box = {}

    def cb(msg):
        box['m'] = msg

    node.create_subscription(OccupancyGrid, '/map', cb, 1)
    end = node.get_clock().now().nanoseconds / 1e9 + 20.0
    while rclpy.ok() and 'm' not in box:
        rclpy.spin_once(node, timeout_sec=0.2)
        if node.get_clock().now().nanoseconds / 1e9 > end:
            print('20s 内没收到 /map（slam_toolbox 在跑吗？）')
            node.destroy_node()
            rclpy.shutdown()
            return 1

    m = box['m']
    info, grid = m.info, m.data
    w, h, res = info.width, info.height, info.resolution
    ox, oy = info.origin.position.x, info.origin.position.y

    print(f'分辨率 = {res:.3f} m/格   栅格 = {w} x {h}')
    print(f'原点 = ({ox:.2f}, {oy:.2f})   范围 = {w * res:.2f} m x {h * res:.2f} m')

    occ = free = unk = 0
    xs, ys = [], []
    for i, v in enumerate(grid):
        if v >= 50:
            occ += 1
            xs.append(i % w)
            ys.append(i // w)
        elif v >= 0:
            free += 1
        else:
            unk += 1
    print(f'占用 = {occ}   空闲 = {free}   未知 = {unk}')

    if occ:
        print(f'占用范围: x {ox + min(xs) * res:.2f} ~ {ox + max(xs) * res:.2f} m   '
              f'y {oy + min(ys) * res:.2f} ~ {oy + max(ys) * res:.2f} m')

    def hist(vals, lo, hi, bins=24, label=''):
        print(f'-- {label} 方向占用分布（{hi - lo:.1f} m 分 {bins} 段）--')
        step = (hi - lo) / bins if hi > lo else 1.0
        cnt = [0] * bins
        for v in vals:
            k = int((v - lo) / step)
            cnt[min(max(k, 0), bins - 1)] += 1
        top = max(cnt) or 1
        for i, c in enumerate(cnt):
            bar = '#' * int(round(c * 40 / top))
            print(f'{lo + i * step:7.2f} |{bar} {c}')

    if occ:
        hist([ox + x * res for x in xs], ox + min(xs) * res, ox + max(xs) * res, label='x')
        hist([oy + y * res for y in ys], oy + min(ys) * res, oy + max(ys) * res, label='y')

    step = max(1, w // COLS)
    print(f'-- ASCII 预览（每字符 {step} 格 ≈ {step * res:.2f} m，上=+y）--')
    for y in range(h - 1, -1, -step):
        line = []
        for x in range(0, w, step):
            block = [grid[yy * w + xx]
                     for yy in range(y, max(-1, y - step), -1)
                     for xx in range(x, min(w, x + step))]
            if any(v >= 50 for v in block):
                line.append('#')
            elif any(v >= 0 for v in block):
                line.append('.')
            else:
                line.append(' ')
        print(''.join(line))

    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())