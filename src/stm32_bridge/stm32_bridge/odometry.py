#!/usr/bin/env python3
"""四轮麦克纳姆轮运动学：四轮速度 → /odom + TF"""

import math
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


def quaternion_from_euler_yaw(yaw):
    """绕 Z 轴(yaw)旋转 → 四元数 (x, y, z, w).

    只用到 yaw, 本地实现即可; 不再依赖 tf_transformations ——
    它是 pip 包, 未在 package.xml 声明, 换机容易缺失。
    """
    half = yaw * 0.5
    return (0.0, 0.0, math.sin(half), math.cos(half))

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

    def __init__(self, use_imu_yaw=False, imu_yaw_weight=0.98,
                 imu_gyro_bias_lr=0.02, imu_still_vx=0.01,
                 imu_still_wz=0.02, imu_timeout=0.5, imu_yaw_sign=1.0,
                 log_interval=2.0):
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

        # ===== IMU yaw 融合状态 =====
        # 纯轮速差算的 omega 噪声大、打滑/轮径误差会整体偏(实测建图时
        # map→odom 一度漂到 yaw −116°); gyro z 短期准得多, 但**必须先标定
        # 零偏**(本车静止实测 +0.144 rad/s ≈ +8.2°/s, 直接积分 1s 就飘 8°)。
        self.use_imu_yaw = bool(use_imu_yaw)
        self.alpha = float(imu_yaw_weight)
        self.bias_lr = float(imu_gyro_bias_lr)
        self.still_vx = float(imu_still_vx)
        self.still_wz = float(imu_still_wz)
        self.imu_timeout = float(imu_timeout)
        self.imu_sign = float(imu_yaw_sign)
        self.log_interval = float(log_interval)

        self.gz = None          # 最新 gyro z (rad/s)
        self.gz_time = None     # 收到该样本的时刻 (s)
        self.bias = 0.0         # 零偏估计 (rad/s)
        self.bias_ready = False
        self._bias_buf = []     # 冷启动: 静止头 40 帧取均值
        self.theta_wheel = 0.0  # 纯轮速积分(诊断对照用)
        self.n_gyro = 0
        self.n_fallback = 0
        self._warned_fallback = False
        self._last_log = 0.0

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

        # ===== yaw 角速度: 轮速 与 IMU gyro z 互补滤波 =====
        #   yaw_dot = α·(gz − bias) + (1−α)·omega_wheel
        # α 大 = 短期信 IMU; 轮速只当长期兜底(它不漂零偏, 但有尺度/打滑误差)
        now_s = now.nanoseconds / 1e9
        wz = omega
        if self.use_imu_yaw:
            gz = self._fresh_gyro(now_s)
            if gz is None:
                self.n_fallback += 1
                if not self._warned_fallback:
                    self.get_logger().warn(
                        f'IMU 无新帧(>{self.imu_timeout}s) → yaw 回退纯轮速积分')
                    self._warned_fallback = True
            else:
                self.n_gyro += 1
                self._warned_fallback = False
                # 静止判定: 四轮速度与轮速角速度都≈0 (车不动, 轮子也不动)
                if (abs(vx) < self.still_vx and abs(vy) < self.still_vx
                        and abs(omega) < self.still_wz):
                    self._update_bias(gz)
                wz = self.alpha * (gz - self.bias) + (1.0 - self.alpha) * omega
        else:
            self.n_fallback += 1

        # ===== 积分：速度 × 时间 → 位置增量 =====
        # 把车体坐标系的速度转成世界坐标系
        self.x += (vx * math.cos(self.theta) - vy * math.sin(self.theta)) * dt
        self.y += (vx * math.sin(self.theta) + vy * math.cos(self.theta)) * dt
        self.theta_wheel += omega * dt      # 纯轮速对照(诊断)
        self.theta += wz * dt

        # 低频对照日志: 融合 vs 纯轮速 + 零偏状态
        # (手转 360° 验收就看这条: 融合/纯轮速/真值 三者对比)
        if now_s - self._last_log >= self.log_interval:
            self._last_log = now_s
            gz_txt = f'{self.gz:+.3f}' if self.gz is not None else 'n/a'
            self.get_logger().info(
                f'yaw 对照: 融合={math.degrees(self.theta):+.1f}° '
                f'纯轮速={math.degrees(self.theta_wheel):+.1f}° '
                f'| gyro_z={gz_txt} bias={self.bias:+.3f} rad/s '
                f'| IMU帧={self.n_gyro} 回退={self.n_fallback}')

        # ===== 构造 /odom 消息 =====
        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = 'odom'            # 全局坐标系名字
        odom.child_frame_id = 'base_footprint'    # 车体坐标系名字
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        q = quaternion_from_euler_yaw(self.theta)  # 欧拉角→四元数
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

    # ==================================================================
    # IMU 融合
    # ==================================================================
    def update_imu(self, gz, stamp=None):
        """桥每收到一帧 IMU(10Hz) 时调用: 记下最新 gyro z (rad/s)."""
        self.gz = float(gz) * self.imu_sign
        self.gz_time = (float(stamp) if stamp is not None
                        else self.get_clock().now().nanoseconds / 1e9)

    def _fresh_gyro(self, now_s):
        """返回新鲜可用的 gyro z; 过期/从未收到 → None(触发回退)."""
        if self.gz is None or self.gz_time is None:
            return None
        if now_s - self.gz_time > self.imu_timeout:
            return None
        return self.gz

    def _update_bias(self, gz):
        """静止时标定/跟踪 gyro z 零偏.

        冷启动: 前 40 帧取均值(收敛快, 避免开局 8°/s 漂移);
        之后: 慢 EMA。只在 |gz-bias| 小的时候更新, 防止"慢慢原地转"被吃成零偏。
        """
        if not self.bias_ready:
            self._bias_buf.append(gz)
            if len(self._bias_buf) >= 40:
                self.bias = sum(self._bias_buf) / len(self._bias_buf)
                self.bias_ready = True
                self.get_logger().info(
                    f'gyro z 零偏已标定: {self.bias:+.4f} rad/s '
                    f'({math.degrees(self.bias):+.2f}°/s), '
                    f'样本 {len(self._bias_buf)}')
            return
        if abs(gz - self.bias) < 0.15:
            self.bias = (1.0 - self.bias_lr) * self.bias + self.bias_lr * gz

def main(args=None):
    rclpy.init(args=args)
    node = OdometryPublisher()
    rclpy.spin(node)  # 让节点一直运行
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()