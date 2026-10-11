#!/usr/bin/env python3
"""odom_report.py <odom_*.csv> [只看最后N段] — 把 /odom 记录拆成"直线段/旋转段"

用途：核对里程计标定。把实测值（卷尺量到的 1.00 m、原地 360°）和这里的数字一比，
就能算出尺度与旋转系数的修正量。

用法：python3 odom_report.py /home/sunrise/robot_ws/logs/odom_1789909237.csv
"""
import math
import sys

MOVE_V = 0.03      # m/s 以上算在移动
ROT_W = 0.15       # rad/s 以上算在旋转
MIN_SAMPLES = 5


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def classify(vx, vy, wz):
    v = math.hypot(vx, vy)
    if abs(wz) > ROT_W and v < 0.05:
        return 'rotate'
    if v > MOVE_V:
        return 'move'
    return 'idle'


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    path = sys.argv[1]
    tail_n = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    rows = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        f = line.split(',')
        if len(f) >= 7:
            rows.append([float(v) for v in f[:7]])
    if not rows:
        print('没有数据')
        return 1

    segs = []
    cur = None
    for r in rows:
        k = classify(r[4], r[5], r[6])
        if cur is None or cur['kind'] != k:
            if cur is not None:
                segs.append(cur)
            cur = {'kind': k, 'rows': [r]}
        else:
            cur['rows'].append(r)
    if cur is not None:
        segs.append(cur)

    segs = [s for s in segs if len(s['rows']) >= MIN_SAMPLES]
    if tail_n:
        segs = segs[-tail_n:]

    t0 = rows[0][0]
    print(f'共 {len(rows)} 行 / {rows[-1][0] - t0:.1f}s；有效段 {len(segs)} 个 '
          f'(move>= {MOVE_V} m/s, rotate |wz|>= {ROT_W} rad/s)')
    for i, s in enumerate(segs):
        rs = s['rows']
        dt = rs[-1][0] - rs[0][0]
        du = rs[-1][1] - rs[0][1]
        dv = rs[-1][2] - rs[0][2]
        dyaw = 0.0
        path = 0.0
        yaw_int = 0.0
        for a, b in zip(rs, rs[1:]):
            d = b[0] - a[0]
            dyaw += wrap(b[3] - a[3])
            path += math.hypot(a[4], a[5]) * d
            yaw_int += a[6] * d
        print(f"#{i} {s['kind']:6s} @{rs[0][0] - t0:7.1f}s 时长{dt:5.1f}s "
              f"净位移{math.hypot(du, dv):6.2f}m (Δx={du:6.2f} Δy={dv:6.2f}) "
              f"积分行程{path:6.2f}m Δyaw={math.degrees(dyaw):8.1f}° "
              f"(∫wz dt={math.degrees(yaw_int):7.1f}°)")
    return 0


if __name__ == '__main__':
    sys.exit(main())