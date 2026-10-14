#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_replay.py — 实时打印 /cmd_vel 下发值 与 /odom 反馈值，排查"发了不动"。

用法: python3 watch_replay.py [秒数]
"""
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node


def yaw_of(q):
    import math
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class W(Node):
    def __init__(self):
        super().__init__('watch_replay')
        self.cmd = None
        self.od = None
        self.create_subscription(Twist, '/cmd_vel', self.c1, 10)
        self.create_subscription(Odometry, '/odom', self.c2, 20)

    def c1(self, m):
        self.cmd = m

    def c2(self, m):
        self.od = m


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    rclpy.init()
    n = W()
    t_end = time.time() + secs
    print('  t(s)   | cmd_vx cmd_vy cmd_wz | od_vx od_vy od_wz |   x      y    yaw  ')
    print('-' * 76)
    t0 = time.time()
    last = None
    while time.time() < t_end:
        rclpy.spin_once(n, timeout_sec=0.1)
        if n.cmd is None or n.od is None:
            continue
        c, o = n.cmd, n.od.twist.twist
        p = n.od.pose.pose.position
        row = (round(c.linear.x, 3), round(c.linear.y, 3), round(c.angular.z, 3),
               round(o.linear.x, 3), round(o.linear.y, 3), round(o.angular.z, 3),
               round(p.x, 3), round(p.y, 3))
        # 只在数值变化时打印，避免刷屏
        if row == last and time.time() - t0 < secs - 0.3:
            continue
        last = row
        print(f'{time.time() - t0:6.1f}  | {c.linear.x:+7.3f} {c.linear.y:+7.3f} '
              f'{c.angular.z:+7.3f} | {o.linear.x:+6.3f} {o.linear.y:+6.3f} '
              f'{o.angular.z:+6.3f} | {p.x:+6.3f} {p.y:+6.3f} '
              f'{yaw_of(n.od.pose.pose.orientation):+6.1f}')
    n.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()