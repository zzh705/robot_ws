#!/usr/bin/env python3
"""PID 速度跟踪节点 —— 自主导航三层中最底层。

订阅:
    /cmd_vel_plan  (geometry_msgs/Twist)  DWA 给的期望速度
    /odom          (nav_msgs/Odometry)    编码器读回的真实速度(反馈)

发布:
    /cmd_vel       (geometry_msgs/Twist)  校正后的速度指令 → stm32_bridge → STM32

三个自由度(前/横/转)各一个独立 PID。
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

# ============================================================
# 单个 PID 控制器(位置式)
# ============================================================

class PID:
    """位置式 PID: out = kp*e + ki*∫e*dt + kd*de/dt"""

    def __init__(self, kp, ki, kd,
                 out_min=-1.0, out_max=1.0, i_limit=10.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_min = out_min
        self.out_max = out_max
        self.i_limit = i_limit

        self.integral = 0.0
        self.prev_error = 0.0
        self.prev_time = None

    def update(self, setpoint, feedback, now):
        """setpoint=期望, feedback=反馈, now=秒时间戳"""
        error = setpoint - feedback

        if self.prev_time is None:
            dt = 0.0
        else:
            dt = now - self.prev_time
        if dt <= 0.0:
            dt = 1e-4  # 防止除零

        # I 项:误差随时间累积,并限幅(防"积分饱和")
        self.integral += error * dt
        self.integral = max(-self.i_limit, min(self.i_limit, self.integral))

        # D 项:误差变化率(先置 0,避免噪声放大)
        derivative = 0.0 if dt < 1e-4 else (error - self.prev_error) / dt

        out = (self.kp * error
               + self.ki * self.integral
               + self.kd * derivative)

        out = max(self.out_min, min(self.out_max, out))

        self.prev_error = error
        self.prev_time = now
        return out

    def reset(self):
        self.integral = 0.0
        self.prev_error = 0.0
        self.prev_time = None


# ============================================================
# PID 控制节点
# ============================================================

class PIDControllerNode(Node):
    def __init__(self):
        super().__init__('pid_controller')

        # ---------- 速度上限参数 ----------
        self.declare_parameter('max_linear_x', 0.4)   # 前后 m/s
        self.declare_parameter('max_linear_y', 0.25)  # 横移 m/s
        self.declare_parameter('max_angular_z', 0.5)  # 旋转 rad/s

        # ---------- PID 增益参数 ----------
        self.declare_parameter('kp_x', 2.0)
        self.declare_parameter('ki_x', 0.0)
        self.declare_parameter('kd_x', 0.0)
        self.declare_parameter('kp_y', 2.0)
        self.declare_parameter('ki_y', 0.0)
        self.declare_parameter('kd_y', 0.0)
        self.declare_parameter('kp_z', 1.5)
        self.declare_parameter('ki_z', 0.0)
        self.declare_parameter('kd_z', 0.0)

        self.mvx = self.get_parameter('max_linear_x').value
        self.mvy = self.get_parameter('max_linear_y').value
        self.mwz = self.get_parameter('max_angular_z').value

        # ---------- 三个通道 PID ----------
        self.pid_x = PID(
            self.get_parameter('kp_x').value,
            self.get_parameter('ki_x').value,
            self.get_parameter('kd_x').value,
            out_min=-self.mvx, out_max=self.mvx)
        self.pid_y = PID(
            self.get_parameter('kp_y').value,
            self.get_parameter('ki_y').value,
            self.get_parameter('kd_y').value,
            out_min=-self.mvy, out_max=self.mvy)
        self.pid_z = PID(
            self.get_parameter('kp_z').value,
            self.get_parameter('ki_z').value,
            self.get_parameter('kd_z').value,
            out_min=-self.mwz, out_max=self.mwz)

        # ---------- 订阅/发布 ----------
        self.plan_sub = self.create_subscription(
            Twist, '/cmd_vel_plan', self.on_plan, 10)
        self.odom_sub = self.create_subscription(
            Odometry, '/odom', self.on_odom, 10)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        self.target = Twist()
        self.feedback = Twist()
        self.has_target = False
        self.has_feedback = False

        # ---------- 软启动斜坡: 限制每周期(0.1s)输出变化量 ----------
        # 电机启动瞬间电流冲击会拉垮供电, 用斜坡把 PWM 从 0 缓慢爬升。
        # 默认每周期最大变化 0.03 → 0.15 需约 0.5s, 启动电流平缓。
        self.declare_parameter('slew_v', 0.03)  # 线速度斜坡 m/cycle
        self.declare_parameter('slew_w', 0.06)  # 角速度斜坡 rad/cycle
        self.slew_v = self.get_parameter('slew_v').value
        self.slew_w = self.get_parameter('slew_w').value
        self.prev_cmd_vx = 0.0
        self.prev_cmd_vy = 0.0
        self.prev_cmd_wz = 0.0

        self.timer = self.create_timer(0.1, self.control_loop)

        self.last_log = 0.0
        self.get_logger().info(
            f'PID controller ready: '
            f'mvx={self.mvx} mvy={self.mvy} mwz={self.mwz}')

    def on_plan(self, msg: Twist):
        self.target = msg
        self.has_target = True

    def on_odom(self, msg: Odometry):
        """反馈: 从 /odom 提取真实速度"""
        tw = msg.twist.twist
        self.feedback.linear.x = tw.linear.x
        self.feedback.linear.y = tw.linear.y
        self.feedback.angular.z = tw.angular.z
        self.has_feedback = True

    def control_loop(self):
        """定时器: 10Hz 算一次 PID 并发布"""
        if not (self.has_target and self.has_feedback):
            return

        now = self.get_clock().now().nanoseconds / 1e9

        out_x = self.pid_x.update(self.target.linear.x,
                                  self.feedback.linear.x, now)
        out_y = self.pid_y.update(self.target.linear.y,
                                  self.feedback.linear.y, now)
        out_z = self.pid_z.update(self.target.angular.z,
                                  self.feedback.angular.z, now)

        # 软启动: 限幅输出较上次的变化量
        out_x = max(self.prev_cmd_vx - self.slew_v,
                    min(self.prev_cmd_vx + self.slew_v, out_x))
        out_y = max(self.prev_cmd_vy - self.slew_v,
                    min(self.prev_cmd_vy + self.slew_v, out_y))
        out_z = max(self.prev_cmd_wz - self.slew_w,
                    min(self.prev_cmd_wz + self.slew_w, out_z))
        self.prev_cmd_vx = out_x
        self.prev_cmd_vy = out_y
        self.prev_cmd_wz = out_z

        cmd = Twist()
        cmd.linear.x = out_x
        cmd.linear.y = out_y
        cmd.angular.z = out_z
        self.cmd_pub.publish(cmd)

        # 节流打印(dt 限幅 + 只打印 2Hz)
        if now - self.last_log >= 0.5:
            self.last_log = now
            self.get_logger().info(
                f'期望({self.target.linear.x:.2f},'
                f'{self.target.linear.y:.2f},'
                f'{self.target.angular.z:.2f}) '
                f'实际({self.feedback.linear.x:.2f},'
                f'{self.feedback.linear.y:.2f},'
                f'{self.feedback.angular.z:.2f}) '
                f'输出({out_x:.2f},{out_y:.2f},{out_z:.2f})')


def main(args=None):
    rclpy.init(args=args)
    node = PIDControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()