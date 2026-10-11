#!/usr/bin/env python3
"""轻量 /scan 存活探针：N 秒内收到至少一条 LaserScan 则退出码 0，否则 1。

为什么不用 `ros2 topic hz /scan --window 20`：
    那条 CLI 每次要占满一个核 8~10 秒，而看护每 15 秒就探一次，
    在建图 + 遥控时正好变成周期性卡顿源。本探针只订阅一条消息就退出。

用法：python3 scan_alive.py [超时秒数, 默认 4]
"""
import sys

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan

TIMEOUT = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0


class Probe(Node):
    def __init__(self):
        super().__init__('scan_alive_probe')
        self.seen = False
        self.create_subscription(LaserScan, '/scan', self._cb, 10)

    def _cb(self, _msg):
        self.seen = True


def main():
    rclpy.init()
    node = Probe()
    end = node.get_clock().now().nanoseconds / 1e9 + TIMEOUT
    while rclpy.ok() and not node.seen:
        rclpy.spin_once(node, timeout_sec=0.2)
        if node.get_clock().now().nanoseconds / 1e9 > end:
            break
    ok = node.seen
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()