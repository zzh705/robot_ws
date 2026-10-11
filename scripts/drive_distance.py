#!/usr/bin/env python3
"""drive_distance.py —— 基于 /odom 闭环，直线前进指定距离后停车
用法: python3 drive_distance.py [距离m] [速度m/s]   默认 1.0 0.15
"""
import math
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

TARGET = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
SPEED = float(sys.argv[2]) if len(sys.argv) > 2 else 0.15
TIMEOUT = 30.0


class Drive(Node):
    def __init__(self):
        super().__init__('drive_distance')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.sub = self.create_subscription(Odometry, '/odom', self.cb, 10)
        self.start = None
        self.dist = 0.0
        self.done = False
        self.t0 = time.time()
        self.create_timer(0.05, self.tick)
        self.get_logger().info(
            f'drive target={TARGET:.2f} m speed={SPEED:.2f} m/s')

    def cb(self, msg):
        p = msg.pose.pose.position
        if self.start is None:
            self.start = (p.x, p.y)
            self.get_logger().info(f'start odom=({p.x:.3f},{p.y:.3f})')
        self.dist = math.hypot(p.x - self.start[0], p.y - self.start[1])

    def tick(self):
        if self.done:
            return
        if self.dist >= TARGET:
            self.get_logger().info(f'reached {self.dist:.3f} m, stop')
            self.stop()
            return
        if time.time() - self.t0 > TIMEOUT:
            self.get_logger().warn(
                f'TIMEOUT: only {self.dist:.3f} m moved (no motion?)')
            self.stop()
            return
        t = Twist()
        t.linear.x = SPEED
        self.pub.publish(t)

    def stop(self):
        self.done = True
        for _ in range(15):
            self.pub.publish(Twist())
            time.sleep(0.02)
        self.get_logger().info(f'STOPPED dist={self.dist:.3f} m')


def main():
    rclpy.init()
    n = Drive()
    while rclpy.ok() and not n.done:
        rclpy.spin_once(n, timeout_sec=0.05)
    n.stop()
    n.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()