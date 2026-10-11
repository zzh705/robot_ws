#!/usr/bin/env python3
"""topic_rate.py <topic> <msg_type> [seconds] — 轻量频率计

比 `ros2 topic hz` 省得多（后者在建图时会吃满一个核 8~10 秒）。
除了频率还会打印相邻消息的最大/平均间隔，用来判断有没有卡顿。

例：
    python3 topic_rate.py /scan sensor_msgs/msg/LaserScan 5
    python3 topic_rate.py /odom nav_msgs/msg/Odometry 5
"""
import sys

import rclpy
from rosidl_runtime_py.utilities import get_message


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    topic, type_str = sys.argv[1], sys.argv[2]
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
    msg_type = get_message(type_str)

    rclpy.init()
    node = rclpy.create_node('topic_rate_probe')
    state = {'n': 0, 'last': None, 'gaps': []}

    def cb(_msg):
        now = node.get_clock().now().nanoseconds / 1e9
        if state['last'] is not None:
            state['gaps'].append(now - state['last'])
        state['last'] = now
        state['n'] += 1

    node.create_subscription(msg_type, topic, cb, 10)
    end = node.get_clock().now().nanoseconds / 1e9 + dur
    while rclpy.ok() and node.get_clock().now().nanoseconds / 1e9 < end:
        rclpy.spin_once(node, timeout_sec=0.1)

    n, gaps = state['n'], state['gaps']
    extra = ''
    if gaps:
        extra = (f" | 相邻间隔 mean={sum(gaps) / len(gaps) * 1000:.0f}ms "
                 f"max={max(gaps) * 1000:.0f}ms")
    elif n == 1:
        extra = ' | 只收到 1 条'
    print(f"{topic}: {n} 条 / {dur:.1f}s = {n / dur:.2f} Hz{extra}")

    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())