#!/usr/bin/env python3
"""map_patrol.py — 基于 /odom 闭环的建图航线:走一个小方框(每边 side 米)。
前进用距离闭环 + 航向保持;转向用角度闭环。
用法: python3 map_patrol.py [side_m] [speed_mps] [turn_rps]
默认: 1.0  0.12  0.40
"""
import math
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

SIDE = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
SPEED = float(sys.argv[2]) if len(sys.argv) > 2 else 0.12
TURN = float(sys.argv[3]) if len(sys.argv) > 3 else 0.40

# 方框: 前进 -> 左转90 重复 4 次
STEPS = []
for _ in range(4):
    STEPS.append(('fwd', SIDE))
    STEPS.append(('rot', math.radians(90.0)))

FWD_TOL = 0.01          # m
ROT_TOL = math.radians(2.0)   # rad
KH = 0.8                # 直行航向保持 P 增益
KH_LIM = 0.15           # 航向修正角速度上限 rad/s
KP_ROT = 2.0            # 转向 P 增益


def yaw_of(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def norm(a):
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


class Patrol(Node):
    def __init__(self):
        super().__init__('map_patrol')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.sub = self.create_subscription(Odometry, '/odom', self.cb, 10)
        self.have = False
        self.x = self.y = self.yaw = 0.0
        self.idx = 0
        self.seg_start = None
        self.seg_t0 = time.time()
        self.done = False
        self.create_timer(0.05, self.tick)
        self.get_logger().info(
            f'map_patrol start: side={SIDE} speed={SPEED} turn={TURN}')

    def cb(self, msg):
        p = msg.pose.pose.position
        self.x, self.y = p.x, p.y
        self.yaw = yaw_of(msg.pose.pose.orientation)
        if not self.have:
            self.have = True
            self.get_logger().info(
                f'odom ok start=({self.x:.3f},{self.y:.3f}) yaw={math.degrees(self.yaw):.1f}')

    def stop(self):
        self.done = True
        for _ in range(15):
            self.pub.publish(Twist())
            time.sleep(0.02)

    def tick(self):
        if self.done or not self.have:
            return
        if self.idx >= len(STEPS):
            self.get_logger().info('ROUTE COMPLETE')
            self.stop()
            return

        kind, val = STEPS[self.idx]
        if self.seg_start is None:
            self.seg_start = (self.x, self.y, self.yaw)
            self.seg_t0 = time.time()
            if kind == 'fwd':
                self.get_logger().info(
                    f'[{self.idx}] forward {val:.2f} m from ({self.x:.2f},{self.y:.2f})')
            else:
                self.get_logger().info(
                    f'[{self.idx}] rotate {math.degrees(val):.0f} deg, yaw={math.degrees(self.yaw):.1f}')

        sx, sy, syaw = self.seg_start
        dt = time.time() - self.seg_t0
        t = Twist()

        if kind == 'fwd':
            dist = math.hypot(self.x - sx, self.y - sy)
            if dist >= val - FWD_TOL:
                self.get_logger().info(f'[{self.idx}] fwd done dist={dist:.3f} m')
                self.next_seg()
                return
            if dt > val / SPEED * 3.0 + 6.0:
                self.get_logger().warn(f'[{self.idx}] fwd TIMEOUT dist={dist:.3f}')
                self.next_seg()
                return
            t.linear.x = SPEED
            err = norm(syaw - self.yaw)
            t.angular.z = max(-KH_LIM, min(KH_LIM, KH * err))
        else:
            dtheta = norm(self.yaw - syaw)
            if abs(dtheta) >= abs(val) - ROT_TOL:
                self.get_logger().info(
                    f'[{self.idx}] rot done dtheta={math.degrees(dtheta):.1f} deg')
                self.next_seg()
                return
            if dt > abs(val) / TURN * 3.0 + 6.0:
                self.get_logger().warn(f'[{self.idx}] rot TIMEOUT dtheta={math.degrees(dtheta):.1f}')
                self.next_seg()
                return
            err = val - dtheta
            w = max(-TURN, min(TURN, KP_ROT * err))
            if abs(w) < 0.12:
                w = 0.12 if w >= 0 else -0.12
            t.angular.z = w

        self.pub.publish(t)

    def next_seg(self):
        self.pub.publish(Twist())
        self.idx += 1
        self.seg_start = None


def main():
    rclpy.init()
    n = Patrol()
    while rclpy.ok() and not n.done:
        rclpy.spin_once(n, timeout_sec=0.05)
    n.stop()
    n.get_logger().info(
        f'FINAL odom=({n.x:.3f},{n.y:.3f}) yaw={math.degrees(n.yaw):.1f}')
    n.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
