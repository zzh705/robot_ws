#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_path.py — 回放录制的路线（麦轮全向车专用控制器）。

为什么不用 Pure Pursuit
    纯跟踪是给差速车设计的，只能"边走边转"。遇到路线里的 90° 急弯会切弯外抛，
    目标点跑到身后就原地打转出不来。本车是麦轮(vx/vy/ω 三轴独立)，而且录制时
    手柄就是分开推这三个轴的 —— 逐点解算车体系误差最忠实。

控制律（每个路点一步）
    1. 世界系误差 -> 旋转到车体系:  (bx, by)
    2. 位置比例律:  vx = kp*bx,  vy = kp*by
    3. 航向保持:    ω  = kw*(目标yaw - 当前yaw)
    4. 进目标圆 -> 切下一个路点;  已越过的路点直接跳过(防死循环)
    5. 临近减速:   速度上限 = arrive_radius / dt, 保证不冲出目标点

安全特性
    * /replay_stop (std_msgs/Bool) 远程急停
    * 雷达净空: 沿运动方向净空 < --min-clear 停车等待
    * 卡死检测: --stuck-secs 内位移 < --stuck-dist 判定卡死
    * 总超时 --max-secs

用法
    python3 replay_path.py path.json                      # 默认 0.15 m/s
    python3 replay_path.py path.json --speed 0.10          # 慢速
    python3 replay_path.py path.json --dry-run            # 只打印不动车
"""
import argparse
import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool

LASER_TO_BODY_DEG = 180.0   # URDF 里 base_link->laser 的 yaw（已实测确认）


def yaw_of(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def norm_angle(a):
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


class Replayer(Node):
    def __init__(self, a):
        super().__init__('replay_path')
        self.a = a
        with open(a.path_file, 'r') as f:
            self.wp = json.load(f)['waypoints']
        if len(self.wp) < 2:
            raise SystemExit('路点少于 2 个，没法回放')

        self.total_len = sum(
            math.hypot(self.wp[i + 1]['x'] - self.wp[i]['x'],
                       self.wp[i + 1]['y'] - self.wp[i]['y'])
            for i in range(len(self.wp) - 1))

        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)
        self.create_subscription(Bool, '/replay_stop', self.on_stop, 10)

        self.x = self.y = self.yaw = 0.0
        self.have_odom = False
        self.scan = None
        self.idx = 0
        self.state = 'init'
        self.stop_flag = False
        self.t0 = None
        self.last_move_t = None
        self.last_xy = None
        self.acc_since_move = 0.0
        self.travelled = 0.0
        self.max_err = 0.0
        self.last_log = 0.0
        self.blocked_since = None

        self.dt = 0.05          # 与控制周期一致
        # 速度上限: 保证一步最多走 arrive_radius，避免冲出目标点
        self.v_cap = min(a.speed, a.arrive_radius / max(self.dt * 2.0, 1e-3))

        self.timer = self.create_timer(self.dt, self.tick)
        self.get_logger().info(
            f'回放就绪: {len(self.wp)} 路点 / 规划里程 {self.total_len:.2f} m / '
            f'速度上限 {self.v_cap:.3f} m/s (≈{self.total_len / max(self.v_cap, .01):.0f} s)\n'
            f'  路径起点 ({self.wp[0]["x"]:.3f}, {self.wp[0]["y"]:.3f})，'
            f'等第一帧 /odom 核对车在哪')
        if a.dry_run:
            self.get_logger().info('--dry-run: 不动车')

    # ---------------- 回调 ----------------
    def on_odom(self, m):
        p = m.pose.pose.position
        if self.have_odom and self.last_xy is not None:
            d = math.hypot(p.x - self.last_xy[0], p.y - self.last_xy[1])
            self.acc_since_move += d
            self.travelled += d
        self.last_xy = (p.x, p.y)
        self.x, self.y = p.x, p.y
        self.yaw = yaw_of(m.pose.pose.orientation)
        self.have_odom = True

    def on_scan(self, m):
        self.scan = m

    def on_stop(self, m: Bool):
        if m.data:
            self.get_logger().error('收到 /replay_stop —— 紧急停车')
            self.state = 'stopped'
            self.stop_flag = True

    def clearance_in_dir(self, body_deg, cone_deg=30.0, cap=3.0):
        s = self.scan
        if s is None:
            return cap
        best = cap
        tgt = body_deg % 360.0
        for i, r in enumerate(s.ranges):
            if not math.isfinite(r) or r <= 0.05:
                continue
            body = (math.degrees(s.angle_min + s.angle_increment * i)
                    + LASER_TO_BODY_DEG) % 360.0
            d = abs(body - tgt)
            d = min(d, 360.0 - d)
            if d <= cone_deg and r < best:
                best = r
        return best

    # ---------------- 主循环 ----------------
    def tick(self):
        if not self.have_odom:
            return

        if self.state == 'init':
            s = self.wp[0]
            off = math.hypot(self.x - s['x'], self.y - s['y'])
            self.get_logger().info(
                f'  车在 ({self.x:.3f}, {self.y:.3f}) yaw={math.degrees(self.yaw):+.1f}°，'
                f'距路径起点 {off:.3f} m')
            if off > self.a.max_recover:
                self.get_logger().error(
                    f'❌ 车离路径起点 {off:.2f} m，超过允许回位距离 '
                    f'{self.a.max_recover} m，拒绝启动。\n'
                    f'   请先用 gamepad 把车开回起点附近再重试。')
                self.state = 'toofar'
                self.stop_flag = True
                return
            if off > 0.6:
                self.get_logger().warn(
                    f'⚠️ 距起点 {off:.2f} m，全向车会直接平移回位，注意周围')
            if self.a.dry_run:
                self.dry_report()
                self.state = 'done'
                return
            self.state = 'run'
            self.t0 = time.time()
            self.last_move_t = self.t0
            self.get_logger().info('▶️ 开始回放')
            return

        if self.state != 'run':
            return

        now = time.time()
        elapsed = now - self.t0

        if elapsed > self.a.max_secs:
            self.get_logger().warn(f'⏱ 总超时 {self.a.max_secs}s')
            self.state = 'timeout'
            self.stop_flag = True

        if self.acc_since_move >= self.a.stuck_dist:
            self.acc_since_move = 0.0
            self.last_move_t = now
        elif now - self.last_move_t > self.a.stuck_secs:
            self.get_logger().error(
                f'🛑 卡死：{self.a.stuck_secs}s 内位移 < {self.a.stuck_dist}m')
            self.state = 'stuck'
            self.stop_flag = True

        cmd = Twist()
        if not self.stop_flag:
            cmd = self.compute_cmd()
            if self.a.min_clear > 0 and math.hypot(cmd.linear.x, cmd.linear.y) > 1e-3:
                dir_body = math.degrees(math.atan2(cmd.linear.y, cmd.linear.x))
                clr = self.clearance_in_dir(dir_body)
                if clr < self.a.min_clear:
                    if self.blocked_since is None:
                        self.get_logger().warn(
                            f'⛔ 运动方向净空 {clr:.2f}m < {self.a.min_clear}m，停车等待')
                        self.blocked_since = now
                    cmd = Twist()
                elif self.blocked_since is not None:
                    self.get_logger().info('▶️ 已通，恢复')
                    self.blocked_since = None

        if self.stop_flag:
            self.finish()
            return

        self.pub.publish(cmd)
        self.progress(elapsed, now)

    # ---------------- 逐点跟踪 ----------------
    def compute_cmd(self):
        n = len(self.wp)

        # 1) 跳过已经到达/越过的路点（最多扫 40 个，防远距离回位时卡死）
        scanned = 0
        while self.idx < n - 1 and scanned < 40:
            t = self.wp[self.idx]
            d = math.hypot(t['x'] - self.x, t['y'] - self.y)
            if d <= self.a.arrive_radius:
                self.idx += 1
                scanned += 1
            else:
                break

        tgt = self.wp[self.idx]
        last = self.idx >= n - 1
        d_world = math.hypot(tgt['x'] - self.x, tgt['y'] - self.y)

        # 终点判定
        if last and d_world < self.a.goal_tol:
            self.get_logger().info('🏁 到达终点')
            self.state = 'done'
            self.stop_flag = True
            return Twist()

        # 2) 世界误差 -> 车体系
        c, s = math.cos(-self.yaw), math.sin(-self.yaw)
        dx = tgt['x'] - self.x
        dy = tgt['y'] - self.y
        bx = c * dx - s * dy
        by = s * dx + c * dy
        self.max_err = max(self.max_err, d_world)

        # 3) 比例律 + 限幅
        vx = self.a.kp * bx
        vy = self.a.kp * by
        sp = math.hypot(vx, vy)
        cap = self.v_cap
        if last and d_world < self.a.slow_radius:
            cap = min(cap, self.v_cap * (d_world / self.a.slow_radius))
        if sp > cap and sp > 1e-9:
            vx *= cap / sp
            vy *= cap / sp

        # 4) 航向保持（最后一个路点不强制对齐，终点位置优先）
        wz = 0.0
        if not (last and d_world < self.a.goal_tol):
            wz = self.a.kw * norm_angle(tgt['yaw'] - self.yaw)
            wz = max(-self.a.max_wz, min(self.a.max_wz, wz))
            if d_world > self.a.arrive_radius:
                wz = max(-self.a.max_wz, min(self.a.max_wz, wz))

        t = Twist()
        t.linear.x = vx
        t.linear.y = vy
        t.angular.z = wz
        return t

    def dry_report(self):
        n = len(self.wp)
        worst_turn = (0.0, 0)
        for i in range(n - 1):
            a, b = self.wp[i], self.wp[i + 1]
            d = math.hypot(b['x'] - a['x'], b['y'] - a['y'])
            if d < 1e-6:
                continue
            ang = abs(norm_angle(b['yaw'] - a['yaw']))
            step_ang = ang
            if d > 0.05 and step_ang > worst_turn[0]:
                worst_turn = (step_ang, i)
        self.get_logger().info('--- 路线体检 ---')
        self.get_logger().info(f'  路点数 {n}, 规划里程 {self.total_len:.2f} m')
        self.get_logger().info(f'  平均路点间距 {self.total_len / max(n - 1, 1):.3f} m')
        self.get_logger().info(
            f'  相邻路点最大航向突变 {math.degrees(worst_turn[0]):.0f}° '
            f'(#{worst_turn[1]})')
        ys = [w['yaw'] for w in self.wp]
        self.get_logger().info(
            f'  航向跨度 {math.degrees(max(ys) - min(ys)):.0f}°')

    def progress(self, elapsed, now):
        if now - self.last_log < 2.0:
            return
        self.last_log = now
        n = len(self.wp)
        g = self.wp[-1]
        d_goal = math.hypot(g['x'] - self.x, g['y'] - self.y)
        pct = 100.0 * self.idx / max(n - 1, 1)
        self.get_logger().info(
            f'  {elapsed:5.1f}s  进度 {pct:5.1f}%  idx {self.idx}/{n - 1}  '
            f'行驶 {self.travelled:5.2f}m  距终点 {d_goal:5.2f}m  '
            f'位置 ({self.x:+.2f},{self.y:+.2f})  '
            f'当前点误差 {math.hypot(self.wp[self.idx]["x"] - self.x, self.wp[self.idx]["y"] - self.y):.3f}m')

    def stop_zero(self, n=10):
        for _ in range(n):
            self.pub.publish(Twist())
            time.sleep(0.02)

    def finish(self):
        self.stop_zero()
        if self.timer:
            self.timer.cancel()
            self.timer = None
        g = self.wp[-1]
        self.get_logger().info(
            f'回放结束[{self.state}]: 行驶 {self.travelled:.2f}m / '
            f'规划 {self.total_len:.2f}m，'
            f'到达 idx {self.idx}/{len(self.wp) - 1}\n'
            f'  实际终点 ({self.x:.3f}, {self.y:.3f}) 规划终点 ({g["x"]:.3f}, {g["y"]:.3f}) '
            f'偏差 {math.hypot(g["x"] - self.x, g["y"] - self.y):.3f}m')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path_file')
    ap.add_argument('--speed', type=float, default=0.15, help='速度上限 m/s')
    ap.add_argument('--kp', type=float, default=1.2, help='位置比例增益')
    ap.add_argument('--kw', type=float, default=1.6, help='航向比例增益')
    ap.add_argument('--max-wz', type=float, default=0.6, help='最大角速度 rad/s')
    ap.add_argument('--arrive-radius', type=float, default=0.06,
                    help='进入该半径即切下一路点 m')
    ap.add_argument('--slow-radius', type=float, default=0.30,
                    help='终点前该半径内开始减速 m')
    ap.add_argument('--goal-tol', type=float, default=0.12, help='终点容差 m')
    ap.add_argument('--max-recover', type=float, default=2.5,
                    help='车离起点超过该距离就拒绝启动 m')
    ap.add_argument('--stuck-dist', type=float, default=0.05)
    ap.add_argument('--stuck-secs', type=float, default=6.0)
    ap.add_argument('--max-secs', type=float, default=420.0)
    ap.add_argument('--min-clear', type=float, default=0.30,
                    help='运动方向最小净空 m (0 = 关闭)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    rclpy.init()
    node = Replayer(a)
    try:
        while rclpy.ok() and node.state not in ('done', 'stopped', 'stuck',
                                                 'timeout', 'toofar'):
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        node.get_logger().warn('用户中断 (Ctrl-C)，停车')
        node.stop_flag = True
    finally:
        node.stop_zero(20)
        node.get_logger().info(
            f'最终: 状态={node.state} 行驶={node.travelled:.2f}m '
            f'位置=({node.x:.3f}, {node.y:.3f})')
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()