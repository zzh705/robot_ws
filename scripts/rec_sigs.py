#!/usr/bin/env python3
"""rec_sigs.py — 诊断"车能走但剧烈抖动"：录三路信号做对比。

思路
    用**恒定指令**绕开 DWA(不发 goal, DWA 就不会发 /cmd_vel_plan)，
    直接往 /cmd_vel_plan 发固定 vx，观察:
      /cmd_vel_plan  我发的期望(已知, 恒定)
      /cmd_vel       PID 校正后的实际下发(是否在抖?)
      /odom          编码器反馈的轮速(量化噪声有多大? 抖动频率?)
    三路一起看，就能分清抖动来自:
      a) /odom 反馈噪声大(编码器量化) → 低层闭环被噪声激励
      b) /cmd_vel 自己在振荡(反馈没噪声) → 环路增益/延时问题
      c) /cmd_vel_plan 上游在抖 → DWA/规划问题(本次不会, 因为我恒定)

用法
    python3 rec_sigs.py --vx 0.15 --secs 4        # 前进录制
    python3 rec_sigs.py --vx 0.0  --secs 0        # 只看不动的噪声底
"""
import argparse
import math
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node


class Rec(Node):
    def __init__(self):
        super().__init__('rec_sigs')
        self.rows = []          # (t, plan_vx, cmd_vx, od_vx, od_wz)
        self.plan = (0.0, 0.0)
        self.cmd = (0.0, 0.0)
        self.od = (0.0, 0.0)
        self.pub = self.create_publisher(Twist, '/cmd_vel_plan', 10)
        self.create_subscription(Twist, '/cmd_vel', self.on_cmd, 10)
        self.create_subscription(Odometry, '/odom', self.on_odom, 20)

    def on_cmd(self, m):
        self.cmd = (m.linear.x, m.angular.z)

    def on_odom(self, m):
        t = m.twist.twist
        self.od = (t.linear.x, t.angular.z)


def stats(v, name, unit=''):
    if not v:
        print(f'  {name}: 无数据')
        return
    n = len(v)
    mean = sum(v) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in v) / n)
    zc = sum(1 for i in range(1, n) if (v[i] - mean) * (v[i - 1] - mean) < 0)
    print(f'  {name}: n={n} 均值={mean:+.4f}{unit} 标准差={sd:.4f} '
          f'峰峰值={max(v)-min(v):.4f} 过零={zc} 次'
          f'  -> 约 {zc/2:.1f} Hz 摆动')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--vx', type=float, default=0.15)
    ap.add_argument('--secs', type=float, default=4.0)
    ap.add_argument('--rate', type=float, default=20.0)
    args = ap.parse_args()

    rclpy.init()
    node = Rec()
    # 先静置 1s 采噪声底
    t0 = time.time()
    while time.time() - t0 < 1.0:
        rclpy.spin_once(node, timeout_sec=0.05)
    idle = [node.od[0] for _ in range(20) for _ in [rclpy.spin_once(node, timeout_sec=0.02)]]
    print('=== 静止时 /odom 轮速(噪声底) ===')
    stats(idle, 'odom.linear.x', ' m/s')

    print(f'\n=== 恒定指令 vx={args.vx} m/s, {args.secs}s ===')
    node.pub.publish(Twist())      # 清一次
    t_end = time.time() + args.secs
    ts = time.time()
    while time.time() < t_end:
        m = Twist()
        m.linear.x = args.vx
        node.pub.publish(m)
        node.rows.append((time.time() - ts, args.vx, node.cmd[0], node.od[0]))
        rclpy.spin_once(node, timeout_sec=1.0 / args.rate)

    # 停车
    for _ in range(10):
        node.pub.publish(Twist())
        rclpy.spin_once(node, timeout_sec=0.05)

    od = [r[3] for r in node.rows]
    cm = [r[2] for r in node.rows]
    print('\n=== 反馈 /odom.linear.x ===')
    stats(od, 'odom.linear.x', ' m/s')
    print('=== 下发 /cmd_vel.linear.x ===')
    stats(cm, 'cmd.linear.x', ' m/s')

    print('\n=== 前 40 个采样(时间, 期望, 下发, 反馈) ===')
    for t, p, c, o in node.rows[:40]:
        print(f'  {t:5.2f}s  {p:+.3f}  {c:+.3f}  {o:+.3f}')
    node.destroy_node()
    return 0


if __name__ == '__main__':
    sys.exit(main())
