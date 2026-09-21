#!/usr/bin/env python3
"""STM32 桥接主节点：串口 ↔ ROS2"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from .serial_driver import SerialDriver, auto_detect_port
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

        # ===== 串口端口可配置（参数化, 留空 = 自动探测）=====
        self.declare_parameter('port', '')
        port = self.get_parameter('port').get_parameter_value().string_value.strip()
        if not port:
            port = auto_detect_port()
            if not port:
                port = '/dev/robot_stm32'

        self.serial = SerialDriver(device=port, baudrate=115200)
        self.parser = FrameParser()
        self.encoder_vel = EncoderVelocity()
        self.odom_pub = OdometryPublisher()
        self._log_ts = {}
        try:
            self.serial.open()
        except Exception as exc:
            self.get_logger().fatal(f'串口打开失败: {exc}')
            raise

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

    def throttled(self, key, interval=1.0):
        """同一 key 的日志最多 interval 秒一条.

        编码器帧率远高于日志吞吐, 不节流会把 CPU 和 SSH 通道刷爆。
        """
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self._log_ts.get(key, 0.0) < interval:
            return False
        self._log_ts[key] = now
        return True

    def on_frame(self, frame_type, payload):
        """每收到一个完整帧，自动调用这个函数"""

        if frame_type == TYPE_ENCODER:
            # 解码：payload → EncoderData
            enc = unpack_encoder(payload)

            # 诊断: 打印原始计数, 判断 update 前解析是否正常
            if self.throttled('raw'):
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
            if self.throttled('odom'):
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
        if self.throttled('cmd'):
            self.get_logger().warn(
                f'CMD_VEL TX: vx={msg.linear.x:.4f} '
                f'vy={msg.linear.y:.4f} wz={msg.angular.z:.4f} '
                f'frame={frame.hex(" ")}'
            )

        try:
            self.serial.send(frame)
        except Exception as exc:
            # 异常绝不能穿透回调: rclpy 的回调异常会顺着 executor 冒到 spin(),
            # 把整个节点进程杀掉(实测: 串口写 [Errno 5] → 退出码 1, /odom 与
            # /cmd_vel 订阅同时消失)。这里只限频报错, 交给驱动自动重连。
            if self.throttled('tx_err', 2.0):
                self.get_logger().error(
                    f'串口发送失败(已跳过该指令, 等待自动重连): {exc}'
                )


def main(args=None):
    rclpy.init(args=args)
    try:
        node = BridgeNode()
    except Exception as exc:
        print(f'[stm32_bridge] 启动失败: {exc}', flush=True)
        rclpy.shutdown()
        raise SystemExit(1)
    # 串口被拔 / USB 重新枚举(ttyACM0 -> ttyACM1)后自动重连, 不必人工重启节点
    node.serial.start_auto_reconnect()
    rclpy.spin(node)
    node.serial.close()
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()