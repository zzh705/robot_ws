#!/usr/bin/env python3
"""lidar_yaw_check.py — 判定雷达的实际安装朝向（哪个方向是"车头"）

为什么要它
    URDF 里 base_link→laser 的 yaw 一直挂着"临时值 180°"，没人确认过。
    如果它是错的，SLAM 建出的地图会整体旋转，DWA 会把障碍物看反。

判据（绝对，不需要目视、不需要驱动电机）
    "车头方向"由电机 +PWM 定义（固件里实测过），与雷达怎么装无关。
    在【车头正前方 ~25cm、与雷达同高】放一个物体后，扫描里该方向会
    **多出一个近距离回波**；那个扇区就是车头在激光坐标系里的角度 θ_front。

        URDF 的 base_link→laser yaw = -θ_front
        θ_front ≈ 180° → yaw = 180°(π) → 现状正确
        θ_front ≈   0° → yaw = 0       → 现状反了 180°（且地图必须重建）

三种用法
    # 1) 免掐表（推荐）：持续监视，你放上/拿开物体时立刻出结论
    python3 scripts/lidar_yaw_check.py --watch [--window 180]

    # 2) 快照式：分开存两次，再比对
    python3 scripts/lidar_yaw_check.py --save clean    # 车头前方空旷
    python3 scripts/lidar_yaw_check.py --save object   # 放好物体且不动
    python3 scripts/lidar_yaw_check.py --compare

快照落在 /home/sunrise/.lidar_yaw/（重启不丢、不污染仓库）。
"""
import argparse
import math
import os
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan

SNAP_DIR = '/home/sunrise/.lidar_yaw'
CAPTURE_S = 4.0


class P(Node):
    def __init__(self):
        super().__init__('lidar_yaw_check')
        self.frames = []
        self.amin = None
        self.ainc = None
        self.create_subscription(LaserScan, '/scan', self.cb, 10)

    def cb(self, msg):
        self.frames.append(np.array(msg.ranges, dtype=float))
        self.amin = msg.angle_min
        self.ainc = msg.angle_increment


def capture(node, dur=CAPTURE_S):
    """采 dur 秒, 返回每束的中位距离(丢掉的用 NaN)。"""
    node.frames = []
    t_end = time.time() + dur
    while time.time() < t_end:
        rclpy.spin_once(node, timeout_sec=0.2)
    if not node.frames:
        return None
    n = min(len(f) for f in node.frames)
    arr = np.array([f[:n] for f in node.frames], dtype=float)
    arr[~np.isfinite(arr)] = np.nan
    with np.errstate(all='ignore'):
        return np.nanmedian(arr, axis=0)


def sect_min(med, amin, ainc, nsect=36):
    """每 10° 扇区的最近距离。"""
    n = len(med)
    ang = np.degrees(amin + ainc * np.arange(n)) % 360.0
    out = {}
    for s in range(nsect):
        m = (ang >= s * 10) & (ang < s * 10 + 10)
        if m.sum() >= 2 and np.isfinite(med[m]).any():
            out[s] = float(np.nanmin(med[m]))
    return out


def verdict(cand, title='=== 判定 ==='):
    """cand: [(变化量, 扇区, 旧值, 新值)] —— 变化的扇区 = 车头方向。"""
    wx = wy = 0.0
    for d, s, b, l in cand:
        th = math.radians(s * 10 + 5)
        wx += abs(d) * math.cos(th)
        wy += abs(d) * math.sin(th)
    th_front = math.degrees(math.atan2(wy, wx)) % 360.0
    yaw_u = (-th_front) % 360.0
    near = min((0, 90, 180, 270),
               key=lambda c: min(abs(yaw_u - c), 360 - abs(yaw_u - c)))
    print(f'\n{title}')
    for d, s, b, l in sorted(cand, key=lambda x: -abs(x[0])):
        what = '出现近物' if d < 0 else '近物消失'
        print(f'  扇区 {s*10:>3}-{s*10+10:>3}°  {b:.2f} → {l:.2f} m  ({what})')
    print(f'  车头在激光系方向 θ_front ≈ {th_front:.1f}°')
    print(f'  → URDF 的 base_link→laser yaw 应为 {yaw_u:.1f}° (≈ {near}°)')
    print('  当前 URDF 写的是 180°(π)')
    if near == 180:
        print('  ✅ 现状正确: 雷达 0° 朝车尾, URDF 不用改。')
    elif near == 0:
        print('  ❌ 现状反了 180°: 雷达 0° 其实朝车头。')
        print('     → URDF 里 3.14159265 改成 0')
        print('     → 现有 library.pgm 是带错 yaw 建的地图, 必须重建')
        print('       (重建前别跑导航: DWA 会把障碍物看反)')
    else:
        print(f'  ⚠ 像装在车的 {near}° 方向 —— 人工复核(可能侧装)')
    return th_front


def watch(window):
    """持续监视: 你在车头前方放上/拿开物体, 一有显著变化立刻出结论。"""
    rclpy.init()
    node = P()
    print('采集基线 5s ... 这一刻先别动车头前方的东西', flush=True)
    base = capture(node, 5.0)
    if base is None:
        print('!! 没收到 /scan（雷达没在发布？）')
        node.destroy_node()
        return 1
    amin, ainc = node.amin, node.ainc
    sb = sect_min(base, amin, ainc)
    print(f'基线就绪。接下来 {window:.0f}s 内, 请【把物体放到 / 或从'
          f'车头正前方约 25cm 处拿开】(与雷达同高), 放好保持不动。',
          flush=True)
    t_end = time.time() + window
    last = time.time()
    while time.time() < t_end:
        now = capture(node, 2.0)
        if now is None:
            continue
        sn = sect_min(now, amin, ainc)
        cand = []
        for s in sorted(set(sb) | set(sn)):
            b, l = sb.get(s), sn.get(s)
            if b is None or l is None:
                continue
            d = l - b
            if abs(d) > 0.15 and (b < 1.5 or l < 1.5):
                cand.append((d, s, b, l))
        if cand:
            verdict(cand, '=== 检测到变化 ===')
            node.destroy_node()
            return 0
        if time.time() - last > 30:
            last = time.time()
            print(f'  ... 继续等（剩余 {max(0, t_end - time.time()):.0f}s）',
                  flush=True)
    print('!! 超时: 这段时间没检测到显著变化')
    print('   检查: 物体是否与雷达同高(离车底 0.12m)? 距离 20~30cm?')
    print('   若该方向本来就有更近的墙, 变化会被掩盖')
    node.destroy_node()
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--save', metavar='NAME', help='snapshot 名字, 如 clean / object')
    ap.add_argument('--compare', action='store_true')
    ap.add_argument('--watch', action='store_true', help='持续监视, 变化即出结论')
    ap.add_argument('--window', type=float, default=180.0, help='--watch 最长秒数')
    args = ap.parse_args()
    if not (args.save or args.compare or args.watch):
        ap.error('需要 --save NAME / --compare / --watch 之一')
    if args.watch:
        return watch(args.window)

    os.makedirs(SNAP_DIR, exist_ok=True)
    rclpy.init()
    node = P()
    print(f'采集 {CAPTURE_S:.0f}s ...', flush=True)
    med = capture(node)
    amin, ainc = node.amin, node.ainc
    node.destroy_node()
    if med is None:
        print('!! 没收到 /scan（雷达没在发布？）')
        return 1

    if args.save:
        path = os.path.join(SNAP_DIR, f'{args.save}.npz')
        np.savez(path, ranges=med, amin=amin, ainc=ainc)
        sec = sect_min(med, amin, ainc)
        print(f'已存快照 [{args.save}] -> {path}  ({len(med)} 点)')
        for s in sorted(sec):
            print(f'  {s*10:>3}-{s*10+10:>3}  {sec[s]:6.2f}')
        return 0

    pc = os.path.join(SNAP_DIR, 'clean.npz')
    po = os.path.join(SNAP_DIR, 'object.npz')
    if not (os.path.exists(pc) and os.path.exists(po)):
        print(f'需要先存两个快照: {pc} 和 {po}')
        return 1
    dc, do = np.load(pc), np.load(po)
    clean, obj = dc['ranges'], do['ranges']
    n = min(len(clean), len(obj))
    sc = sect_min(clean[:n], amin, ainc)
    so = sect_min(obj[:n], amin, ainc)
    print('\n=== 扇区: 干净 / 放物体 / 变化(负=多出近物) ===')
    cand = []
    for s in sorted(set(sc) | set(so)):
        b, l = sc.get(s), so.get(s)
        if b is None or l is None:
            continue
        d = l - b
        mark = ''
        if abs(d) > 0.15 and (b < 1.5 or l < 1.5):
            mark = '  <== 变化'
            cand.append((d, s, b, l))
        print(f'  {s*10:>3}-{s*10+10:>3}   {b:6.2f}   {l:6.2f}   {d:+7.3f}{mark}')
    if not cand:
        print('\n!! 没检测到显著变化 —— 物体是否与雷达同高/距离 20~30cm?')
        return 1
    verdict(cand)
    return 0


if __name__ == '__main__':
    sys.exit(main())
