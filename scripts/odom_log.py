#!/usr/bin/env python3
"""odom_log.py — 把 /odom 连续记成 CSV，用于里程计标定核对（事后算尺度/方向误差）。

列：# t,x,y,yaw,vx,vy,wz
用法：python3 odom_log.py [输出文件]   默认 logs/odom_<unix时间戳>.csv
"""
import math
import sys
import time

import rclpy
from nav_msgs.msg import Odometry


def yaw_of(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def main():
    path = (sys.argv[1] if len(sys.argv) > 1
            else f'/home/sunrise/robot_ws/logs/odom_{int(time.time())}.csv')
    rclpy.init()
    node = rclpy.create_node('odom_log')
    fh = open(path, 'w', buffering=1)
    fh.write('# t,x,y,yaw,vx,vy,wz\n')

    def cb(m):
        p = m.pose.pose.position
        t = node.get_clock().now().nanoseconds / 1e9
        fh.write(f'{t:.3f},{p.x:.4f},{p.y:.4f},{yaw_of(m.pose.pose.orientation):.4f},'
                 f'{m.twist.twist.linear.x:.4f},{m.twist.twist.linear.y:.4f},'
                 f'{m.twist.twist.angular.z:.4f}\n')

    node.create_subscription(Odometry, '/odom', cb, 20)
    print(f'[odom_log] 写入 {path}', flush=True)
    rclpy.spin(node)


if __name__ == '__main__':
    main()