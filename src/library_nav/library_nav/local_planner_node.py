#!/usr/bin/env python3
"""DWA 局部规划节点 —— 自主导航三层中的第二层。

订阅:
    /scan          (sensor_msgs/LaserScan)   周围障碍
    /odom          (nav_msgs/Odometry)       当前位姿 + 速度
    /global_path   (nav_msgs/Path)           A* 给的参考大路(可空,为空时直冲目标)
    /goal_pose     (geometry_msgs/PoseStamped) 目标任务点(odom 或 map 系)

发布:
    /cmd_vel_plan  (geometry_msgs/Twist)     裁决出的期望速度 → PID

DWA(Dynamic Window Approach)四步:
    动态窗口采样 → 前向模拟轨迹 → 碰撞剔除 → 打分排序
"""

import math
import time
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Odometry, Path
from sensor_msgs.msg import LaserScan


class DWAController(Node):
    def __init__(self):
        super().__init__('local_planner_dwa')

        # =====================
        # 可调参数
        # =====================
        self.declare_parameter('max_vx', 0.4)      # 最大前进速度 m/s
        self.declare_parameter('min_vx', 0.0)     # 最小速度(禁止倒车: 倒车会诱发"原地后退打转")
        self.declare_parameter('max_wz', 0.5)      # 最大转角速度 rad/s
        self.declare_parameter('acc_x', 0.25)      # 线加速度上限 m/s²
        self.declare_parameter('acc_w', 0.6)       # 角加速度上限 rad/s²

        self.declare_parameter('predict_time', 2.0)  # 预测时长 s
        self.declare_parameter('sim_dt', 0.1)        # 模拟步长 s
        self.declare_parameter('sample_v', 9)        # 线速度采样份数
        self.declare_parameter('sample_w', 11)       # 角速度采样份数

        self.declare_parameter('inflate_radius', 0.25)  # 障碍膨胀半径(半车宽+安全) m
        self.declare_parameter('goal_tolerance', 0.15)  # 到达判定 m
        self.declare_parameter('lookahead', 0.5)        # 路径前瞻距离 m

        # 打分权重(调参时改这里)
        self.declare_parameter('w_heading', 0.4)
        self.declare_parameter('w_dist', 0.3)
        self.declare_parameter('w_vel', 0.2)
        self.declare_parameter('w_path', 0.1)
        self.declare_parameter('w_prog', 0.3)  # 推进分: 奖励"向目标靠近"轨迹, 抑制原地打转

        self.declare_parameter('control_period', 0.1)  # 决策周期 s

        # =====================
        # 读取参数
        # =====================
        self.max_vx = self.get_parameter('max_vx').value
        self.min_vx = self.get_parameter('min_vx').value
        self.max_wz = self.get_parameter('max_wz').value
        self.acc_x = self.get_parameter('acc_x').value
        self.acc_w = self.get_parameter('acc_w').value
        self.predict_time = self.get_parameter('predict_time').value
        self.sim_dt = self.get_parameter('sim_dt').value
        self.sample_v = self.get_parameter('sample_v').value
        self.sample_w = self.get_parameter('sample_w').value
        self.inflate = self.get_parameter('inflate_radius').value
        self.goal_tol = self.get_parameter('goal_tolerance').value
        self.lookahead = self.get_parameter('lookahead').value
        self.w_heading = self.get_parameter('w_heading').value
        self.w_dist = self.get_parameter('w_dist').value
        self.w_vel = self.get_parameter('w_vel').value
        self.w_path = self.get_parameter('w_path').value
        self.w_prog = self.get_parameter('w_prog').value
        self.period = self.get_parameter('control_period').value

        # =====================
        # 状态缓存
        # =====================
        self.pose = (0.0, 0.0, 0.0)      # 当前位姿 (x, y, theta) odom 系
        self.vel = (0.0, 0.0, 0.0)       # 当前速度 (vx, vy, wz)  -- vy 预留麦轮横移
        self.scan_points = None          # 障碍点数组 Nx2, odom 系
        self.scan_count = 0
        self.goal_pose = None            # PoseStamped(已变换到 odom 系)
        self.global_path = None          # A* 路径(点数组, 任何系, 与 goal 同系)

        # =====================
        # 订阅 / 发布
        # =====================
        self.scan_sub = self.create_subscription(
            LaserScan, '/scan', self.on_scan, 5)
        self.odom_sub = self.create_subscription(
            Odometry, '/odom', self.on_odom, 10)
        self.goal_sub = self.create_subscription(
            PoseStamped, '/goal_pose', self.on_goal, 10)
        self.path_sub = self.create_subscription(
            Path, '/global_path', self.on_global_path, 10)
        self.cmd_pub = self.create_publisher(
            Twist, '/cmd_vel_plan', 10)

        # 决策定时器
        self.timer = self.create_timer(self.period, self.plan_once)

        # 手动节流打印(Humble 的 logger 不支持 throttle_duration_sec)
        self.last_msg_time = 0.0
        self.last_msg = ''

        # 原地转圈熔断状态
        self._spin_t0 = time.monotonic()
        self._spin_dist = 1e9
        # 航向回正迟滞状态 (False=未在对齐; True=正在原地回正)
        self._aligning = False

        self.get_logger().info('DWA local planner ready.')

    # ============================================================
    # 输入回调
    # ============================================================

    def on_scan(self, msg: LaserScan):
        """把激光点从 laser 系转到 odom 系, 存为障碍点数组。
        此处忽略激光与车体的 TF 偏移(lidar 在车顶), 直接用平面坐标,
        误差在膨胀半径内吸收。
        """
        n = len(msg.ranges)
        angles = msg.angle_min + np.arange(n) * msg.angle_increment
        ranges = np.asarray(msg.ranges, dtype=np.float64)

        # 过滤: 忽略 <0.2m 的点(雷达自身/车体反射的固定盲区点, 非真实障碍)
        # 雷达装在车顶, 支架/线缆等结构会在固定方向产生 0.1~0.2m 反射,
        # 这些点永远在膨胀半径内, 会让 DWA 认为被堵死而无法起步。
        valid = np.isfinite(ranges) & (ranges > 0.2) \
            & (ranges < msg.range_max - 0.1)
        r = ranges[valid]
        a = angles[valid]

        # 障碍点在机器人(sensor)坐标系下的平面坐标
        local = np.stack([
            r * np.cos(a),
            r * np.sin(a),
        ], axis=1)

        # 粗略转到 odom 系(用车体位姿旋转 + 平移)
        x, y, theta = self.pose
        ct, st = math.cos(theta), math.sin(theta)
        rot = np.array([[ct, -st], [st, ct]])
        self.scan_points = local @ rot.T + np.array([x, y])
        self.scan_count = len(self.scan_points)
        now = time.monotonic()
        if now - getattr(self, '_obj_t_log', 0) > 5.0:
            self._obj_t_log = now
            if len(self.scan_points) > 0:
                # 相对车体坐标 (x前, y左)
                dx = self.scan_points[:, 0] - self.pose[0]
                dy = self.scan_points[:, 1] - self.pose[1]
                dist = np.hypot(dx, dy)
                front = self.scan_points[(dx > 0.05) & (np.abs(dy) < 0.6)
                                         & (dist < 2.0)]
                near = self.scan_points[dist < 0.8]
                # 找出最近 5 个点及其角度(相对车体)
                if len(dist) > 0:
                    k = min(5, len(dist))
                    idxs = np.argsort(dist)[:k]
                    info = []
                    for i in idxs:
                        ang = math.degrees(math.atan2(
                            self.scan_points[i, 1] - self.pose[1],
                            self.scan_points[i, 0] - self.pose[0]))
                        info.append(
                            f'{dist[i]:.2f}m@{ang:.0f}deg')
                    angstr = ' '.join(info)
                else:
                    angstr = 'none'
                self.get_logger().info(
                    f'scan_pts={len(self.scan_points)} '
                    f'front<2m={len(front)} '
                    f'near<0.8m={len(near)} '
                    f'min_near={(dist.min() if len(dist) else -1):.2f} '
                    f'nearest5={angstr}')

    def on_odom(self, msg: Odometry):
        p = msg.pose.pose
        q = p.orientation
        # 四元数 → 航向角 yaw
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)

        self.pose = (p.position.x, p.position.y, yaw)
        tw = msg.twist.twist
        self.vel = (tw.linear.x, tw.linear.y, tw.angular.z)

    def on_goal(self, msg: PoseStamped):
        self.goal_pose = (msg.pose.position.x,
                          msg.pose.position.y)
        self.get_logger().info(
            f'New goal: ({self.goal_pose[0]:.2f}, {self.goal_pose[1]:.2f})')

    def on_global_path(self, msg: Path):
        if not msg.poses:
            return
        self.global_path = [
            (p.pose.position.x, p.pose.position.y)
            for p in msg.poses
        ]
        self.get_logger().info(
            f'Global path updated: {len(self.global_path)} points')

    # ============================================================
    # 主决策: DWA 四步
    # ============================================================

    def plan_once(self):
        if self.goal_pose is None:
            return  # 还没有目标, 不动作

        x, y, theta = self.pose
        vx, vy, wz = self.vel

        dist_to_goal = math.hypot(
            self.goal_pose[0] - x,
            self.goal_pose[1] - y,
        )
        if dist_to_goal < self.goal_tol:
            self.publish_cmd(0.0, 0.0)
            self.log_throttled('Goal reached — stop.')
            return

        # ---- 0.5) 大航向偏差: 先原地回正再前进 ----
        # 若当前车头与"指向目标方向"偏差过大还同时给 vx,
        # DWA 倾向选 "vx+wz" 大弧线 → 低速转大圈, 观感=原地打转。
        # 策略: 偏差 > 阈值时只旋转不前进, 回正到阈值内再走直线。
        goal_ang = math.atan2(
            self.goal_pose[1] - y, self.goal_pose[0] - x)
        heading_err = self.norm_angle(goal_ang - theta)
        # 迟滞: 航向偏差大时先原地回正, 回正到小角度后再走直线.
        # 30°进 → 原地转; 10°出 → 恢复前进. 中间死区防止来回切换抖动.
        align_in = math.radians(30.0)
        align_out = math.radians(10.0)
        if not getattr(self, '_aligning', False):
            in_align = abs(heading_err) > align_in
        else:
            in_align = abs(heading_err) > align_out
        self._aligning = in_align
        if in_align:
            target_w = min(
                self.max_wz,
                max(-self.max_wz, heading_err / 0.5))  # 比例转向, 5s 内回正
            self.log_throttled(
                f'Aligning: err={math.degrees(heading_err):+.0f}deg  '
                f'wz={target_w:+.2f} (vx=0)')
            # 有意回正视为"有进展", 刷新原地转圈熔断计时, 防止误停
            self._spin_t0 = time.monotonic()
            self._spin_dist = dist_to_goal
            self.publish_cmd(0.0, target_w)
            return

        # ---- 0) 选定局部目标: 有全局路径则跟踪"前瞻点", 否则直冲终点 ----
        goal_x, goal_y = self.goal_pose
        if self.global_path is not None:
            lookahead = self.pick_lookahead(x, y)
            if lookahead is not None:
                goal_x, goal_y = lookahead

        # ---- ① 动态窗口: 受当前速度与加速度限制 ----
        # 上界放宽到 max_vx(不依赖当前速度), 避免低速死锁:
        #   若上限=min(max_vx, vx+acc*dt), 车一旦很慢, 窗口一直很窄,
        #   永远选不到大速度, 车永远慢。 正常行为应是"想快就能快"。
        # 下界保留减速限制(min_vx 允许倒车), 防止急转弯/急刹。
        v_window = (
            max(self.min_vx, vx - self.acc_x * self.period),
            self.max_vx,
        )
        # 角速度窗口: 同样放开上限
        w_window = (
            max(-self.max_wz, wz - self.acc_w * self.period),
            self.max_wz,
        )

        # 采样网格
        v_samples = np.linspace(v_window[0], v_window[1], self.sample_v)
        w_samples = np.linspace(w_window[0], w_window[1], self.sample_w)

        best_score = -1e9
        best_v, best_w = 0.0, 0.0

        for v in v_samples:
            for w in w_samples:
                traj = self.simulate_trajectory(v, w, x, y, theta)
                score, safe = self.score_trajectory(
                    traj, v, w, x, y, theta,
                    dist_to_goal=dist_to_goal,
                    goal_x=goal_x, goal_y=goal_y)
                if not safe:
                    continue
                if score > best_score:
                    best_score = score
                    best_v, best_w = v, w

        # 一个能走的候选都没有 → 停车
        if best_score < 0:
            self.log_throttled('No feasible trajectory — stop.')
            self.publish_cmd(0.0, 0.0)
            return

        # ---- 原地转圈熔断: 连续 2.5s 只有原地打转, 没有向目标推进 ----
        # 场景: 目标在障碍后方/盲区里, 车唯一"安全"轨迹只有旋转,
        # 打分会让它一直转 (dist_score 对纯旋转已设为0, 但 heading 分仍让它转).
        # 若 2.5s 内 dist_to_goal 几乎没缩小 → 判定卡死, 停车而不是白转.
        chosen_is_rotation = (abs(best_v) < 0.02) and (abs(best_w) > 0.05)
        now = time.monotonic()
        if chosen_is_rotation:
            if now - self._spin_t0 > 2.5:
                if dist_to_goal > self._spin_dist - 0.15:
                    self.log_throttled(
                        'Stuck spinning (no progress) — stop.')
                    self.publish_cmd(0.0, 0.0)
                    return
                self._spin_t0 = now
                self._spin_dist = dist_to_goal
        else:
            self._spin_t0 = now
            self._spin_dist = dist_to_goal

        self.publish_cmd(best_v, best_w)
        # 诊断: 低频打印决策
        now = time.monotonic()
        if now - getattr(self, '_plan_log', 0) > 2.0:
            self._plan_log = now
            nfp = 0
            if self.scan_points is not None and len(self.scan_points):
                dx = self.scan_points[:, 0] - self.pose[0]
                dy = self.scan_points[:, 1] - self.pose[1]
                ds = np.hypot(dx, dy)
                ang = np.degrees(np.arctan2(dy, dx))
                nfp = int(((ds < 1.0) & (np.abs(ang) < 20)).sum())
            self.get_logger().info(
                f'PLAN vx={best_v:.3f} wz={best_w:.3f} '
                f'dist2goal={dist_to_goal:.2f} front1m_in20deg={nfp}')

    # ============================================================
    # 路径前瞻点: 路径上找离车最近点, 往前取 lookahead 处一点
    # ============================================================

    def pick_lookahead(self, x, y):
        if not self.global_path:
            return None
        pts = np.asarray(self.global_path, dtype=np.float64)
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        nearest = int(np.argmin(d))

        # 从最近点开始沿着路径累加距离, 到 >= lookahead 为止
        acc = 0.0
        for i in range(nearest, len(pts) - 1):
            acc += math.hypot(
                pts[i + 1, 0] - pts[i, 0],
                pts[i + 1, 1] - pts[i, 1])
            if acc >= self.lookahead:
                return float(pts[i + 1, 0]), float(pts[i + 1, 1])
        # 路径走完还没到 lookahead → 返回路径终点
        return float(pts[-1, 0]), float(pts[-1, 1])

    # ============================================================
    # ② 前向模拟: 运动学积分出预测轨迹
    # ============================================================

    def simulate_trajectory(self, v, w, x, y, theta):
        """从 (x,y,theta) 出发, 以 (v,w) 匀速走 predict_time 秒.
        返回轨迹点列表 [(x,y), ...]
        """
        traj = []
        cx, cy, ct = x, y, theta
        n = int(self.predict_time / self.sim_dt)
        for _ in range(n):
            ct += w * self.sim_dt          # 先转
            cx += v * math.cos(ct) * self.sim_dt   # 再走 (朝新朝向)
            cy += v * math.sin(ct) * self.sim_dt
            traj.append((cx, cy))
        return traj

    # ============================================================
    # ③④ 碰撞剔除 + 打分
    # ============================================================

    def score_trajectory(self, traj, v, w, x, y, theta,
                         dist_to_goal, goal_x=None, goal_y=None):
        """给一条轨迹打分; 不安全返回 (score, False)."""
        if goal_x is None:
            goal_x = self.goal_pose[0]
            goal_y = self.goal_pose[1]

        # ---- ③ 碰撞检测 ----
        min_dist = self.min_obstacle_dist(traj)
        if min_dist < self.inflate:
            return -1e9, False

        # ---- 末点位姿: 评估朝向 + 推进 ----
        end = traj[-1]
        ex, ey = end
        delta_x = goal_x - ex
        delta_y = goal_y - ey
        dist_end = math.hypot(delta_x, delta_y)
        # 推进分: 轨迹是否让车离目标更近 (纯原地旋转 → 分≈0)
        # 防止"目标旁有障碍 → 唯一安全轨迹是旋转 → 车原地转圈"的死局
        prog = (dist_to_goal - dist_end) / max(0.4, dist_to_goal)
        prog_score = min(1.0, max(0.0, prog))

        # 目标方向角
        goal_angle = math.atan2(delta_y, delta_x)
        # 轨迹末端航向: 近似用 (末点-倒数-第2点) 的方向
        if len(traj) >= 2:
            prev = traj[-2]
            end_heading = math.atan2(
                ey - prev[1], ex - prev[0])
        else:
            end_heading = theta

        # 角度差归一化到 [-π, π]
        ang_diff = self.norm_angle(goal_angle - end_heading)

        # ---- ④ 打分 ----
        heading_score = 1.0 - abs(ang_diff) / math.pi    # 1=车头正对目标
        # 纯原地旋转/静止: 位置没有推进, 不给"安全分"
        start = traj[0]
        moved = any(
            math.hypot(p[0] - start[0], p[1] - start[1]) > 0.02
            for p in traj[1:])
        if not moved or min_dist >= 990.0:
            dist_score = 0.0
        else:
            dist_score = min(1.0, min_dist / 2.0)        # 越远越安全 → 高分
        vel_score = abs(v) / self.max_vx                 # 越快越赶路
        # 归一化
        heading_score = min(1.0, max(0.0, heading_score))
        dist_score = min(1.0, max(0.0, dist_score))
        vel_score = min(1.0, max(0.0, vel_score))

        # 路径贴合分: 轨迹末端到全局路径的最短距离(越近分越高)
        path_score = 1.0
        if self.w_path > 0.0 and self.global_path is not None \
                and len(self.global_path) > 0:
            lp = self.dist_to_path(ex, ey)
            path_score = max(0.0, 1.0 - lp / 0.6)  # >0.6m 离路太远 → 0 分

        # 推进分只当轨迹确实在接近目标时给分;
        # 原地打转/后退的轨迹推进分为 0, 避免"原地转圈"
        # (碰撞检测里旋转轨迹已算安全, 若再给高分 → 车会一直选择转圈)
        total = (self.w_heading * heading_score
                 + self.w_dist * dist_score
                 + self.w_vel * vel_score
                 + self.w_path * path_score
                 + self.w_prog * prog_score)
        # 严禁倒车: DWA 会因"倒车让运动方向朝目标"而被引诱,
        # 表现 = 车原地后退打转一直到不了目标. 直接否决.
        if v < -0.01:
            return -1e9, False
        return total, True

    def dist_to_path(self, x, y):
        """点 (x,y) 到全局路径的最短欧氏距离."""
        pts = np.asarray(self.global_path, dtype=np.float64)
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        return float(d.min())

    def min_obstacle_dist(self, traj):
        """轨迹到最近障碍的最小距离(跳过起点=车当前所在位置).

        起点就是车位置, 若车当前已贴近某障碍(比如旁边0.2m有墙),
        把起点也计算进去会令所有轨迹被判碰撞 → 机器人"困死"无法起步.
        因此只检查运动产生的后续轨迹点会不会撞。
        另外: 纯旋转轨迹 (w≠0,v=0) 的模拟点全部重叠在起点,
        它们没有实际位移, 也跳过(原地转不会撞)。
        """
        if self.scan_points is None or len(self.scan_points) == 0:
            return 999.0  # 没有激光数据 → 假设空旷
        if len(traj) <= 1:
            return 999.0  # 只有起点一个点 → 无运动可言, 不算碰撞
        start = traj[0]
        traj_arr = []
        for p in traj[1:]:
            # 跳过没有实际位移的模拟点(纯旋转伪点 / 静止)
            if math.hypot(p[0] - start[0], p[1] - start[1]) < 0.02:
                continue
            traj_arr.append(p)
        if not traj_arr:
            return 999.0  # 只有原地转/静止 → 无所谓碰撞
        traj_arr = np.asarray(traj_arr, dtype=np.float64)
        # 计算每个轨迹点(后续)到最近障碍点的距离
        # 向量化: 对每个轨迹点算全场最小 => 再取全局最小
        d = np.sqrt(
            ((traj_arr[:, None, :] - self.scan_points[None, :, :]) ** 2)
            .sum(axis=2)
        )
        return float(d.min())

    @staticmethod
    def norm_angle(a):
        while a > math.pi:
            a -= 2 * math.pi
        while a < -math.pi:
            a += 2 * math.pi
        return a

    # ============================================================
    # 输出
    # ============================================================

    def log_throttled(self, text, interval=1.0):
        """手动节流打印, 避免刷屏."""
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self.last_msg_time >= interval or text != self.last_msg:
            self.last_msg_time = now
            self.last_msg = text
            self.get_logger().info(text)

    def publish_cmd(self, v, w):
        twist = Twist()
        twist.linear.x = float(v)
        twist.angular.z = float(w)
        self.cmd_pub.publish(twist)


def main(args=None):
    rclpy.init(args=args)
    node = DWAController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()