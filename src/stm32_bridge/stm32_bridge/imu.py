#!/usr/bin/env python3
"""imu.py — 把下位机上报的 IMU 帧发布成 ROS2 sensor_msgs/Imu

数据来源
    stm32_bridge 串口帧 TYPE=0x04 (载荷 24 字节:
    ax,ay,az,gx,gy,gz 各 int32 LE, 物理量放大 1000 倍 —— 加速度 mg,
    角速度 m°/s), 由下位机 STM32F407 上的 MPU6050 以 10Hz 上报。

发布
    默认 /imu/data (sensor_msgs/Imu), frame_id 默认 base_footprint。

设计说明
    * 固件只给「加速度 + 角速度」的原始量测, 没有姿态四元数。所以这里
      orientation 填单位四元数, 并把 orientation_covariance[0] 置 -1,
      即 REP-103 约定的「该字段无效, 请下游自行融合」。硬塞一个假姿态会
      让下游误以为有真值, 比留空更糟。
    * MPU6050 在车体上的实际安装朝向未知, 所以提供轴系重排/取反参数
      (imu_axes / imu_signs)。标定方法: 车静止放平, 看 /imu/data 的
      linear_acceleration 是否≈(0,0,+9.8) (Z 轴朝上); 不对就调这两个参数。
    * 单位遵循 REP-103: 线加速度 m/s², 角速度 rad/s。
"""

import math

from sensor_msgs.msg import Imu

_AXIS_INDEX = {'x': 0, 'y': 1, 'z': 2}


class ImuPublisher:
    """把 protocol.ImuData (SI 单位) 转成 sensor_msgs/Imu 并发布。"""

    def __init__(self, node, topic='imu/data', frame_id='base_footprint',
                 axes='xyz', signs='+++', accel_variance=0.02,
                 gyro_variance=0.002, min_interval=0.0):
        self.node = node
        self.frame_id = frame_id
        self.accel_variance = float(accel_variance)
        self.gyro_variance = float(gyro_variance)
        self.min_interval = float(min_interval)
        self.count = 0
        self._last_ts = -1e9

        # 轴系映射: axes='xyz' → 输出的 X/Y/Z 分别取输入的 x/y/z
        self._idx = []
        self._sgn = []
        for ch in (axes or 'xyz').lower()[:3]:
            if ch not in _AXIS_INDEX:
                raise ValueError(f'imu_axes 非法: {axes!r}, 只认 xyz 的组合')
            self._idx.append(_AXIS_INDEX[ch])
        while len(self._idx) < 3:                     # 参数不全时补齐
            self._idx.append(len(self._idx))
        for ch in (signs or '+++')[:3]:
            self._sgn.append(1.0 if ch == '+' else -1.0)
        while len(self._sgn) < 3:
            self._sgn.append(1.0)

        self.pub = node.create_publisher(Imu, topic, 10)
        self.last_gz = 0.0   # 最近一帧(重排/取反后)的 gyro z, 供 odometry 融合

    # ------------------------------------------------------------------
    def _remap(self, ax, ay, az, gx, gy, gz):
        a = [ax, ay, az]
        g = [gx, gy, gz]
        out_a = [self._sgn[i] * a[self._idx[i]] for i in range(3)]
        out_g = [self._sgn[i] * g[self._idx[i]] for i in range(3)]
        return out_a, out_g

    def publish(self, imu):
        """imu: protocol.ImuData (m/s², rad/s)。被限频丢弃时返回 False。"""
        stamp = self.node.get_clock().now()
        if self.min_interval > 0.0:
            t = stamp.nanoseconds / 1e9
            if t - self._last_ts < self.min_interval:
                return False
            self._last_ts = t

        (ax, ay, az), (gx, gy, gz) = self._remap(
            imu.ax, imu.ay, imu.az, imu.gx, imu.gy, imu.gz)
        self.last_gz = gz    # 与发出去的 /imu/data 同源, 避免两处各算一遍

        msg = Imu()
        msg.header.stamp = stamp.to_msg()
        msg.header.frame_id = self.frame_id

        # 无姿态真值 → REP-103: orientation_covariance[0] = -1
        msg.orientation.x = 0.0
        msg.orientation.y = 0.0
        msg.orientation.z = 0.0
        msg.orientation.w = 1.0
        msg.orientation_covariance[0] = -1.0

        msg.angular_velocity.x = gx
        msg.angular_velocity.y = gy
        msg.angular_velocity.z = gz
        msg.angular_velocity_covariance[0] = self.gyro_variance
        msg.angular_velocity_covariance[4] = self.gyro_variance
        msg.angular_velocity_covariance[8] = self.gyro_variance

        msg.linear_acceleration.x = ax
        msg.linear_acceleration.y = ay
        msg.linear_acceleration.z = az
        msg.linear_acceleration_covariance[0] = self.accel_variance
        msg.linear_acceleration_covariance[4] = self.accel_variance
        msg.linear_acceleration_covariance[8] = self.accel_variance

        self.pub.publish(msg)
        self.count += 1
        return True

    def summary(self, imu):
        """一行摘要, 供节点低频打日志。"""
        return (f'a=({imu.ax:+.2f},{imu.ay:+.2f},{imu.az:+.2f}) m/s² '
                f'w=({imu.gx:+.3f},{imu.gy:+.3f},{imu.gz:+.3f}) rad/s '
                f'|a|={math.sqrt(imu.ax ** 2 + imu.ay ** 2 + imu.az ** 2):.2f}')
