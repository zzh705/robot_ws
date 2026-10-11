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
                 out_min=-1.0, out_max=1.0, i_limit=10.0, fb_alpha=0.4):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_min = out_min
        self.out_max = out_max
        self.i_limit = i_limit
        # 反馈一阶低通系数: 0<α<=1, 越小越平滑(α=1 等于不滤波)
        self.fb_alpha = fb_alpha
        self.fb_filt = None

        self.integral = 0.0
        self.prev_error = 0.0
        self.prev_time = None

    def update(self, setpoint, feedback, now):
        """setpoint=期望, feedback=反馈, now=秒时间戳"""
        # 反馈低通(EMA): /odom 的轮速在 20Hz 量级有 ±0.1~0.2 m/s 的抖动
        # (编码器差分 + 下位机上报节奏), 直接进 P 项会被放大成命令抖动,
        # 末端表现就是车剧烈抖动。先做一阶低通。
        if self.fb_alpha >= 0.999:
            fb = feedback
        elif self.fb_filt is None:
            self.fb_filt = feedback
            fb = feedback
        else:
            self.fb_filt = (self.fb_alpha * feedback
                            + (1.0 - self.fb_alpha) * self.fb_filt)
            fb = self.fb_filt
        error = setpoint - fb

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
        self.fb_filt = None


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
        self.declare_parameter('control_period', 0.05)  # 控制周期, 必须与 DWA 一致

        # ---------- PID 增益参数 ----------
        # ★ 增益修正(2026-10-11 实测): 原来是 2.0/2.0/1.5。环路增益=2 配上
        #   10Hz 采样 + /odom 反馈抖动 + 下位机自身的速度环, 构成 ~5Hz 极限环
        #   (实测 /cmd_vel 在 0/0.1/0.2 三级间 bang-bang)。降到 0.4 后修正量
        #   温和(±trim_limit 仍未变), 稳态精度由前馈保证。
        self.declare_parameter('kp_x', 0.4)
        self.declare_parameter('ki_x', 0.0)
        self.declare_parameter('kd_x', 0.0)
        self.declare_parameter('kp_y', 0.4)
        self.declare_parameter('ki_y', 0.0)
        self.declare_parameter('kd_y', 0.0)
        self.declare_parameter('kp_z', 0.4)
        self.declare_parameter('ki_z', 0.0)
        self.declare_parameter('kd_z', 0.0)

        self.mvx = self.get_parameter('max_linear_x').value
        self.mvy = self.get_parameter('max_linear_y').value
        self.mwz = self.get_parameter('max_angular_z').value
        self.period = self.get_parameter('control_period').value

        # 加速度限制按"每秒"定义(避免改频率后斜坡跟着变)
        # 斜坡也放慢(原 2.0/4.0): 每周期允许变化 = per_s × period。原来 2.0×0.05
        # = 0.1/周期, 恰好把抖动量化成 0/0.1/0.2 三级, 进一步放大抖动观感。
        self.declare_parameter('slew_v_per_s', 0.6)   # 线加速 m/s²
        self.declare_parameter('slew_w_per_s', 1.5)   # 角加速 rad/s²
        self.declare_parameter('decel_boost', 3.0)    # 减速允许是加速的 N 倍(停得干脆)
        self.declare_parameter('trim_limit', 0.15)     # PID 修正量上限, 反馈异常时仍安全
        self.slew_v_per_s = self.get_parameter('slew_v_per_s').value
        self.slew_w_per_s = self.get_parameter('slew_w_per_s').value
        self.decel_boost = self.get_parameter('decel_boost').value
        self.trim_limit = self.get_parameter('trim_limit').value
        self.slew_v = self.slew_v_per_s * self.period    # 每周期允许变化量
        self.slew_w = self.slew_w_per_s * self.period
        self.slew_v_dec = self.slew_v * self.decel_boost
        self.slew_w_dec = self.slew_w * self.decel_boost

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

        # /cmd_vel 是共享话题: 遥控脚本(file_cmd_vel / teleop_twist_keyboard)也发它。
        # 两个发布者同时存在会互相抢底盘, 这里发现后告警一次。
        self._conflict_warned = False
        self.create_timer(2.0, self.warn_if_conflict)

        self.target = Twist()
        self.feedback = Twist()
        self.has_target = False
        self.has_feedback = False

        # 兼容旧参数: 如果上游 launch 还传 slew_v / slew_w, 尊重但不强制.
        # 新版按 per-s 标准化, 这些字段变成"每秒"等价(供向后兼容).
        self.declare_parameter('slew_v', -1.0)
        self.declare_parameter('slew_w', -1.0)
        legacy_v = self.get_parameter('slew_v').value
        legacy_w = self.get_parameter('slew_w').value
        if legacy_v > 0 and (self.get_parameter('slew_v_per_s').value == 0.6
                              and legacy_v not in (0.08, 0.04)):
            # 有人显式给了非默认 per-cycle 旋钮, 等价换算成 per-s
            self.slew_v_per_s = legacy_v / self.period
            self.slew_v = self.slew_v_per_s * self.period
        if legacy_w > 0 and self.get_parameter('slew_w_per_s').value == 1.5:
            self.slew_w_per_s = legacy_w / self.period
            self.slew_w = self.slew_w_per_s * self.period

        self.prev_cmd_vx = 0.0
        self.prev_cmd_vy = 0.0
        self.prev_cmd_wz = 0.0

        self.timer = self.create_timer(self.period, self.control_loop)

        self.last_log = 0.0
        self.get_logger().info(
            f'PID controller ready: '
            f'mvx={self.mvx} mvy={self.mvy} mwz={self.mwz}')

    def warn_if_conflict(self):
        if self._conflict_warned:
            return
        n = self.count_publishers('/cmd_vel')
        if n > 1:
            self._conflict_warned = True
            self.get_logger().warn(
                f'/cmd_vel 上当前有 {n} 个发布者(含本节点)。'
                f'若同时开着遥控(file_cmd_vel/teleop_twist_keyboard), '
                f'两边会互相抢底盘; 遥控前请先停掉导航栈。')

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

        # 关键改动: 前馈 + 有界 trim
        # out = setpoint + bounded_pid_error
        #   * 稳态精确(前馈抵消负载), 没有低速时的"追不上"滞后
        #   * trim 限 ±trim_limit: 反馈异常(odom=0)时不会暴走
        # 旧版是 out = kp*e, setpoint=0.5m/s 时车先慢后快,
        # 配合 STM32 自身闭环 + 10Hz PID -> 明显一顿一顿的卡顿.
        tgt_x = self.target.linear.x
        tgt_y = self.target.linear.y
        tgt_w = self.target.angular.z
        # ★ 修正(2026-10-11 实测): 原式 clamp(pid_out - 目标, ±limit) 把设定点
        #   减了两次, 实测两个后果:
        #     a) 稳态偏慢: 定速 0.15 m/s 车只跑 ~0.054 m/s(理论根 = 目标/3)
        #     b) 极限环抖动: 误差过零时修正量在 ±limit 间来回跳, 叠加下位机
        #        自身速度环 -> /cmd_vel 20~30Hz 跳 ±0.1~0.2 m/s, 车剧烈抖动
        #   正确语义 = 前馈(直接给设定值) + 有界 P 修正(取自 PID 输出本身)。
        trim_x = max(-self.trim_limit,
                      min(self.trim_limit, out_x))
        trim_y = max(-self.trim_limit,
                      min(self.trim_limit, out_y))
        trim_z = max(-self.trim_limit,
                      min(self.trim_limit, out_z))
        out_x = tgt_x + trim_x
        out_y = tgt_y + trim_y
        out_z = tgt_w + trim_z

        # 非对称斜坡: 加速按 slew_v, 减速按 slew_v*decel_boost(停得干脆)
        sv = (self.slew_v_dec if abs(out_x) < abs(self.prev_cmd_vx)
              else self.slew_v)
        sy = (self.slew_v_dec if abs(out_y) < abs(self.prev_cmd_vy)
              else self.slew_v)
        sw = (self.slew_w_dec if abs(out_z) < abs(self.prev_cmd_wz)
              else self.slew_w)
        out_x = max(self.prev_cmd_vx - sv,
                    min(self.prev_cmd_vx + sv, out_x))
        out_y = max(self.prev_cmd_vy - sy,
                    min(self.prev_cmd_vy + sy, out_y))
        out_z = max(self.prev_cmd_wz - sw,
                    min(self.prev_cmd_wz + sw, out_z))

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