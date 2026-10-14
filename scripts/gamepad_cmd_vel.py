#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gamepad_cmd_vel.py — 手柄 -> /cmd_vel（唯一遥控通道）

为什么不再直连 STM32 串口：
    /dev/robot_stm32 (/dev/ttyACM0) 必须由 stm32_bridge 独占。bridge 一边把
    /cmd_vel 下发给 STM32，一边读回编码器帧积分 /odom。若第二个进程也打开同一个
    tty，两边会互相抢读字节流：编码器帧丢一半 -> /odom 跳变 -> slam_toolbox 按
    错误位姿插帧，地图表现就是"机器人的扫描扇区一块一块重叠"；同时 STM32 会同时
    收到两路互相冲突的速度指令（bridge 的 0 与本脚本的摇杆值），车会一顿一顿。

操作手感与 teleop_gamepad.py 保持一致：
    左摇杆 Y(轴1) 前进/后退   左摇杆 X(轴0) 左右横移   右摇杆 X(轴3) 原地旋转
    按键0 急停（切换）        按键1 按住加速 x2

用法：
    source /opt/ros/humble/setup.bash
    python3 gamepad_cmd_vel.py
"""
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

try:
    import pygame
except ImportError:
    sys.exit("[ERR] 缺少 pygame, 请先: pip install pygame")

# ---------------------------------------------------------------- 摇杆映射
# 默认值对应 BETOP XF2 BFM DONGLE（2026-10-13 实测）:
#   ax0=左X  ax1=左Y  ax2=右X  ax3=右Y  ax4/ax5=LT/RT(静息 -1)
# 若换回北通 D2Z(XInput 轴序: ax2=LTrigger, ax3=右X), 启动时加:
#   --ros-args -p axis_rotate:=3
AXIS_FORWARD = 1    # 左摇杆 Y
AXIS_STRAFE = 0     # 左摇杆 X
AXIS_ROTATE = 2     # 右摇杆 X（BETOP XF2）
DEADZONE = 0.08
SPEED_FORWARD = 1.0   # m/s
SPEED_STRAFE = 1.0    # m/s
SPEED_ROTATE = 1.0    # rad/s
BTN_ESTOP = 0
BTN_BOOST = 1
PUB_HZ = 50.0
AB = 0.178            # (轴距/2 + 轮距/2)，与 odometry.py 的 K 一致


def apply_deadzone(v, dz=DEADZONE):
    return 0.0 if abs(v) < dz else v


def clamp_kinematic(vx, vy, omega):
    """麦轮反解限幅：任一轮速超 1m/s 就整体等比缩放，避免 STM32 端硬截断造成偏航。"""
    w1 = vx - vy - omega * AB
    w2 = vx + vy - omega * AB
    w3 = vx + vy + omega * AB
    w4 = vx - vy + omega * AB
    m = max(1.0, abs(w1), abs(w2), abs(w3), abs(w4))
    if m > 1.0:
        return vx / m, vy / m, omega / m
    return vx, vy, omega


class GamepadCmdVel(Node):
    def __init__(self):
        super().__init__('gamepad_cmd_vel')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.estop = False
        self.joy = None
        self.joy_warned = False

        # 轴/键映射做成 ROS 参数，换手柄不用改代码
        self.declare_parameter('axis_forward', AXIS_FORWARD)
        self.declare_parameter('axis_strafe', AXIS_STRAFE)
        self.declare_parameter('axis_rotate', AXIS_ROTATE)
        self.declare_parameter('btn_estop', BTN_ESTOP)
        self.declare_parameter('btn_boost', BTN_BOOST)
        self.declare_parameter('deadzone', DEADZONE)
        self.declare_parameter('speed_forward', SPEED_FORWARD)
        self.declare_parameter('speed_strafe', SPEED_STRAFE)
        self.declare_parameter('speed_rotate', SPEED_ROTATE)
        g = lambda n: self.get_parameter(n).value
        self.ax_f, self.ax_s, self.ax_r = g('axis_forward'), g('axis_strafe'), g('axis_rotate')
        self.btn_e, self.btn_b = g('btn_estop'), g('btn_boost')
        self.dz = g('deadzone')
        self.v_f, self.v_s, self.v_r = g('speed_forward'), g('speed_strafe'), g('speed_rotate')

        pygame.init()
        pygame.joystick.init()
        self._find_joy(block_for=10.0)

        self.timer = self.create_timer(1.0 / PUB_HZ, self.tick)
        self.get_logger().info(
            f'gamepad_cmd_vel 就绪: 前进=ax{self.ax_f} 横移=ax{self.ax_s} '
            f'旋转=ax{self.ax_r} 急停=按键{self.btn_e} 加速=按键{self.btn_b}\n'
            f'只发布 /cmd_vel（不占用 STM32 串口）'
        )

    def _find_joy(self, block_for=0.0):
        """找手柄；block_for>0 时最多轮询这么久（接收器枚举有延迟）。"""
        deadline = time.time() + block_for
        while True:
            pygame.event.pump()
            pygame.joystick.init()
            if pygame.joystick.get_count() > 0:
                joy = pygame.joystick.Joystick(0)
                joy.init()
                self.joy = joy
                self.joy_warned = False
                self.get_logger().info(f'手柄: {joy.get_name()}')
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.5)

    def tick(self):
        pygame.event.pump()
        for ev in pygame.event.get():
            if ev.type == pygame.JOYBUTTONDOWN and ev.button == self.btn_e:
                self.estop = not self.estop
                self.get_logger().warn('急停' if self.estop else '解除急停')

        vx = vy = omega = 0.0

        if self.joy is None:
            self._find_joy()

        if self.joy is not None and not self.estop:
            try:
                fx = apply_deadzone(self.joy.get_axis(self.ax_f), self.dz)
                fy = apply_deadzone(self.joy.get_axis(self.ax_s), self.dz)
                fr = apply_deadzone(self.joy.get_axis(self.ax_r), self.dz)
                boost = 2.0 if self.joy.get_button(self.btn_b) else 1.0
            except pygame.error:
                # 手柄真实拔出：停车，等待重新插入后自动恢复
                if not self.joy_warned:
                    self.get_logger().warn('手柄断开，已停车，等待重新插入…')
                    self.joy_warned = True
                self.joy = None
                pygame.joystick.quit()
                pygame.joystick.init()
            else:
                vx = -fx * self.v_f * boost   # pygame 上=-1 -> 前进为正
                vy = fy * self.v_s * boost
                omega = fr * self.v_r * boost
                vx = max(-self.v_f, min(self.v_f, vx))
                vy = max(-self.v_s, min(self.v_s, vy))
                omega = max(-self.v_r, min(self.v_r, omega))

        vx, vy, omega = clamp_kinematic(vx, vy, omega)

        msg = Twist()
        msg.linear.x = vx
        msg.linear.y = vy
        msg.angular.z = omega
        self.pub.publish(msg)


def main():
    rclpy.init()
    node = GamepadCmdVel()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.pub.publish(Twist())   # 退出前补一帧 0，避免残余速度
        except Exception:
            pass
        node.destroy_node()
        rclpy.shutdown()
        pygame.quit()


if __name__ == '__main__':
    main()