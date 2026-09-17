#!/usr/bin/env python3
"""四轮麦克纳姆轮运动学：四轮速度 → /odom + TF"""

import math
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
from tf_transformations import quaternion_from_euler

# ============ 底盘尺寸（已确认）============
# 轮距一半 = 98mm = 0.098m（左右轮中心距的一半）
HALF_TRACK = 0.098
# 轴距一半 = 80mm = 0.080m（前后轮中心距的一半）
HALF_WHEELBASE = 0.080
# 这两个数相加，在后面算角速度要用
K = HALF_WHEELBASE + HALF_TRACK  # = 0.178m
class OdometryPublisher(Node):
    """
    这是一个 ROS2 节点。
    功能：每收到一次四轮速度，就发布一次 /odom 话题，并广播 odom→base_footprint TF。
    """

    def __init__(self):
        # 创建节点，名字叫 'odometry'
        super().__init__('odometry')

        # 发布器：往 /odom 话题发 Odometry 消息
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)

        # TF 广播器：用来广播 odom → base_footprint 变换
        self.tf_br = TransformBroadcaster(self)

        # 机器人在世界坐标系里的位置（初始为 0）
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0  # 航向角，弧度
        self.prev_time = None

    def update(self, v_fl, v_fr, v_rl, v_rr):
        """
        输入：四个轮子的当前速度 m/s
        作用：积分出位置，发布 /odom 和 TF
        """
        now = self.get_clock().now()

        # 第一次调用：没有时间基准，只记录
        if self.prev_time is None:
            self.prev_time = now
            return

        # 计算 dt（秒）
        dt = (now - self.prev_time).nanoseconds / 1e9
        self.prev_time = now
        if dt <= 0.001:
            return

        # ===== 麦轮正运动学：四轮速度 → 车体速度 =====
        # （公式推导见下方图解）
        vx = (v_fl + v_fr + v_rl + v_rr) / 4.0
        vy = (-v_fl + v_fr + v_rl - v_rr) / 4.0
        omega = (-v_fl + v_fr - v_rl + v_rr) / (4.0 * K)

        # ===== 积分：速度 × 时间 → 位置增量 =====
        # 把车体坐标系的速度转成世界坐标系
        self.x += (vx * math.cos(self.theta) - vy * math.sin(self.theta)) * dt
        self.y += (vx * math.sin(self.theta) + vy * math.cos(self.theta)) * dt
        self.theta += omega * dt

        # ===== 构造 /odom 消息 =====
        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = 'odom'            # 全局坐标系名字
        odom.child_frame_id = 'base_footprint'    # 车体坐标系名字
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        q = quaternion_from_euler(0.0, 0.0, self.theta)  # 欧拉角→四元数
        odom.pose.pose.orientation.x = q[0]
        odom.pose.pose.orientation.y = q[1]
        odom.pose.pose.orientation.z = q[2]
        odom.pose.pose.orientation.w = q[3]
        odom.twist.twist.linear.x = vx
        odom.twist.twist.linear.y = vy
        odom.twist.twist.angular.z = omega
        self.odom_pub.publish(odom)

        # ===== 广播 TF：odom → base_footprint =====
        tf = TransformStamped()
        tf.header.stamp = now.to_msg()
        tf.header.frame_id = 'odom'
        tf.child_frame_id = 'base_footprint'
        tf.transform.translation.x = self.x
        tf.transform.translation.y = self.y
        tf.transform.rotation.x = q[0]
        tf.transform.rotation.y = q[1]
        tf.transform.rotation.z = q[2]
        tf.transform.rotation.w = q[3]
        self.tf_br.sendTransform(tf)
def main(args=None):
    rclpy.init(args=args)
    node = OdometryPublisher()
    rclpy.spin(node)  # 让节点一直运行
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()