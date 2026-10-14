#!/usr/bin/env python3
"""record_path.py — 手柄遥控时记录轨迹(里程计路点)，用于后续回放建图。

用法:
    python3 record_path.py [输出文件.json]

输出: JSON 格式的路点列表 [{x, y, yaw}, ...]
"""
import json
import math
import sys
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import Bool


def yaw_of(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class PathRecorder(Node):
    def __init__(self, output_file, min_dist=0.05, min_yaw=0.05):
        super().__init__('path_recorder')
        self.output_file = output_file
        self.min_dist = min_dist
        self.min_yaw = min_yaw
        self.waypoints = []
        self.last_wp = None
        self.recording = False

        self.sub_odom = self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.sub_rec = self.create_subscription(Bool, '/record_path', self.on_record, 10)

        self.get_logger().info(f'PathRecorder 就绪: 输出={output_file}, 最小间距={min_dist}m, 最小角度={math.degrees(min_yaw):.1f}°')
        self.get_logger().info('按下手柄按键0(急停键)切换录制开/关，或发布 /record_path (std_msgs/Bool)')

    def on_record(self, msg: Bool):
        self.recording = msg.data
        if self.recording:
            self.get_logger().info('🔴 开始录制轨迹...')
            self.waypoints = []
            self.last_wp = None
        else:
            self.get_logger().info(f'⏹️ 停止录制，共 {len(self.waypoints)} 个路点')
            self.save()

    def on_odom(self, msg: Odometry):
        if not self.recording:
            return
        p = msg.pose.pose.position
        x, y = p.x, p.y
        yaw = yaw_of(msg.pose.pose.orientation)

        if self.last_wp is None:
            self.waypoints.append({'x': x, 'y': y, 'yaw': yaw})
            self.last_wp = (x, y, yaw)
            self.get_logger().info(f'  起点: ({x:.3f}, {y:.3f}) yaw={math.degrees(yaw):.1f}°')
            return

        lx, ly, lyaw = self.last_wp
        dist = math.hypot(x - lx, y - ly)
        dyaw = abs(yaw - lyaw)
        while dyaw > math.pi:
            dyaw = abs(dyaw - 2 * math.pi)

        if dist >= self.min_dist or dyaw >= self.min_yaw:
            self.waypoints.append({'x': x, 'y': y, 'yaw': yaw})
            self.last_wp = (x, y, yaw)
            self.get_logger().info(f'  路点 {len(self.waypoints)}: ({x:.3f}, {y:.3f}) yaw={math.degrees(yaw):.1f}°')

    def save(self):
        data = {
            'waypoints': self.waypoints,
            'count': len(self.waypoints),
            'timestamp': time.time()
        }
        with open(self.output_file, 'w') as f:
            json.dump(data, f, indent=2)
        self.get_logger().info(f'✅ 轨迹已保存到 {self.output_file}')


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else '/home/sunrise/robot_ws/logs/recorded_path.json'

    rclpy.init()
    node = PathRecorder(output)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        if node.recording:
            node.save()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()