#!/usr/bin/env python3
"""STM32 桥接主节点：串口 ↔ ROS2"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from .serial_driver import SerialDriver
from .protocol import (
    FrameParser,
    TYPE_ENCODER,
    unpack_encoder,
    pack_cmd_vel,
)
from .encoder import EncoderVelocity
from .odometry import OdometryPublisher


class BridgeNode(Node):
    def __init__(self):
        super().__init__('stm32_bridge')

        # ===== 串口端口可配置（参数化）=====
        self.declare_parameter('port', '/dev/ttyACM0')
        port = self.get_parameter('port').get_parameter_value().string_value

        self.serial = SerialDriver(device=port, baudrate=115200)
        self.parser = FrameParser()
        self.encoder_vel = EncoderVelocity()
        self.odom_pub = OdometryPublisher()
        self.serial.open()

        # ===== 订阅 cmd_vel（键盘/手柄遥控指令）=====
        self.cmd_vel_sub = self.create_subscription(
            Twist,
            '/cmd_vel',
            self.on_cmd_vel,
            10
        )

        # ===== 启动接收线程 =====
        self.serial.on_frame = self.on_frame
        self.get_logger().info(
            f'STM32 bridge started on {port}'
        )

    def on_frame(self, frame_type, payload):
        """每收到一个完整帧，自动调用这个函数"""

        if frame_type == TYPE_ENCODER:
            # 解码：payload → EncoderData
            enc = unpack_encoder(payload)

            # 诊断: 打印原始计数, 判断 update 前解析是否正常
            self.get_logger().info(
                f'RAW enc: ts={enc.timestamp_ms} '
                f'fl={enc.fl} rl={enc.rl} fr={enc.fr} rr={enc.rr}'
            )

            # 换算：脉冲数 → 四轮速度 m/s
            v_fl, v_fr, v_rl, v_rr = self.encoder_vel.update(
                enc.timestamp_ms,
                enc.fl,
                enc.rl,
                enc.fr,
                enc.rr,
            )

            # 发布 /odom + TF
            self.odom_pub.update(v_fl, v_fr, v_rl, v_rr)

            # 调试用：在终端打印一下
            self.get_logger().info(
                f'odom: fl={v_fl:.3f} fr={v_fr:.3f} '
                f'rl={v_rl:.3f} rr={v_rr:.3f}'
            )

    def on_cmd_vel(self, msg: Twist):
        """收到 /cmd_vel 后，打包发给 STM32"""

        frame = pack_cmd_vel(
            float(msg.linear.x),
            float(msg.linear.y),
            float(msg.angular.z),
        )

        # >>> 诊断: 确认收到指令 + 帧内容
        self.get_logger().warn(
            f'CMD_VEL TX: vx={msg.linear.x:.4f} '
            f'vy={msg.linear.y:.4f} wz={msg.angular.z:.4f} '
            f'frame={frame.hex(" ")}'
        )

        self.serial.send(frame)


def main(args=None):
    rclpy.init(args=args)
    node = BridgeNode()
    rclpy.spin(node)
    node.serial.close()
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()