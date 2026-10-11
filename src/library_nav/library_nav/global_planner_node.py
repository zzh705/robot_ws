#!/usr/bin/env python3
"""A* 全局规划节点 —— 自主导航三层中的最上层.

订阅:
    /map          (nav_msgs/msg/OccupancyGrid)  已建好的栅格地图(带膨胀层)
    /scan         (sensor_msgs/msg/LaserScan)   实时激光, 叠成"软更新"障碍层
    /goal_pose    (geometry_msgs/msg/PoseStamped) 目标点(map 系)

发布:
    /global_path  (nav_msgs/msg/Path)   A* 找出的全局路径(供 DWA 跟踪)
    /costmap_scan_marks (visualization_msgs/MarkerArray) 实时障碍叠加层
                                          (可在 RViz 里开 MarkerArray 显示)

流程:
    1. 收到 /map → 构建栅格 + 膨胀层(车体半径)
    2. 收到 /scan → 把激光点云投到 map 系, 叠到 costmap (带时间衰减)
    3. 收到 /goal_pose → 起点(车当前位姿) + 终点 → A* 搜索
       终点在障碍/未知格 → 在 N 米内找最近可走点(吸附)
    4. 发布 /global_path(m 个点, map 系)

A* 核心: f = g + h, 启发式=八邻域对角距离
"""
import math
import heapq

import numpy as np
import rclpy
from rclpy.node import Node
from nav_msgs.msg import OccupancyGrid, Path
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import LaserScan
from visualization_msgs.msg import Marker, MarkerArray
from tf2_ros import Buffer, TransformListener


# 8 邻域方向(顺序: 上下左右 + 四个斜角)
DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (1, -1), (-1, 1), (1, 1)]
DIAG_COST = math.sqrt(2.0)


class AStar8:
    """在栅格地图上执行 A* 搜索.

    grid_map: 0=可通过, 1=障碍, None|未知统一当障碍
    """

    def __init__(self, occ: np.ndarray, resolution: float, origin):
        self.occ = occ
        self.res = resolution
        self.origin = origin  # (x, y) 地图原点(左上角)的世界坐标

        self.h, self.w = occ.shape

    def world_to_grid(self, x, y):
        gx = int(round((x - self.origin[0]) / self.res))
        gy = int(round((y - self.origin[1]) / self.res))
        return gy, gx

    def grid_to_world(self, row, col):
        x = self.origin[0] + (col + 0.5) * self.res
        y = self.origin[1] + (row + 0.5) * self.res
        return x, y

    def is_free(self, r, c):
        if r < 0 or r >= self.h or c < 0 or c >= self.w:
            return False
        return self.occ[r, c] == 0

    def search(self, start_world, goal_world):
        """start_world/goal_world 是世界坐标(x,y)."""
        sr, sc = self.world_to_grid(*start_world)
        gr, gc = self.world_to_grid(*goal_world)

        if not self.is_free(sr, sc):
            # 起点在障碍上(车跑到了不该跑的地方, 比如被推进墙边)
            # 仍尝试: 临时把它当作可走, 让 A* 找到一条尽量绕出障碍的路径
            print(f'[A*] start in obstacle: r={sr} c={sc}', flush=True)
        if not self.is_free(gr, gc):
            # 终点在障碍/未知格, A* 会直接拒
            return None

        g_score = np.full((self.h, self.w), np.inf)
        g_score[sr, sc] = 0.0
        parent = {}
        open_heap = [(self.heuristic(sr, sc, gr, gc), sr, sc)]
        closed = set()

        while open_heap:
            f, r, c = heapq.heappop(open_heap)
            if (r, c) in closed:
                continue
            closed.add((r, c))
            if (r, c) == (gr, gc):
                return self.reconstruct_path(parent, (sr, sc), (gr, gc))

            g = g_score[r, c]
            for i, (dr, dc) in enumerate(DIRS):
                nr, nc = r + dr, c + dc
                if not self.is_free(nr, nc) or (nr, nc) in closed:
                    continue
                step = DIAG_COST if i >= 4 else 1.0
                ng = g + step
                if ng < g_score[nr, nc]:
                    g_score[nr, nc] = ng
                    parent[(nr, nc)] = (r, c)
                    h = self.heuristic(nr, nc, gr, gc)
                    heapq.heappush(open_heap, (ng + h, nr, nc))

        print('[A*] no path found', flush=True)
        return None

    @staticmethod
    def heuristic(r, c, gr, gc):
        dr = abs(r - gr)
        dc = abs(c - gc)
        return max(dr, dc) + (DIAG_COST - 1.0) * min(dr, dc)

    def reconstruct_path(self, parent, start, goal):
        path_g = [goal]
        cur = goal
        while cur != start:
            cur = parent[cur]
            path_g.append(cur)
        path_g.reverse()
        world = []
        for (r, c) in path_g:
            x, y = self.grid_to_world(r, c)
            world.append((x, y))
        return world

    def snap_to_free(self, x, y, radius_m=1.0):
        """目标格被占/未知时, 在 radius_m 米内找最近可走点.

        返回 (x, y, snapped, dist). snapped=False 时 (x,y)==(x,y) 且 dist=0.
        找不到最近可走点 (整圈都是) → 0.
        """
        sr, sc = self.world_to_grid(x, y)
        if 0 <= sr < self.h and 0 <= sc < self.w and self.is_free(sr, sc):
            return x, y, False, 0.0
        r_px = max(1, int(radius_m / self.res))
        best = None
        best_d2 = None
        for r in range(1, r_px + 1):
            for dr in (-r, 0, r):
                for dc in (-r, 0, r):
                    if abs(dr) != r and abs(dc) != r:
                        continue
                    rr = sr + dr
                    cc = sc + dc
                    if not (0 <= rr < self.h and 0 <= cc < self.w):
                        continue
                    if self.is_free(rr, cc):
                        d2 = dr * dr + dc * dc
                        if best_d2 is None or d2 < best_d2:
                            best_d2 = d2
                            best = (rr, cc)
            if best is not None:
                break
        if best is None:
            return x, y, False, 0.0
        rr, cc = best
        sx, sy = self.grid_to_world(rr, cc)
        return sx, sy, True, math.hypot(sx - x, sy - y)


# ============================================================
# ROS2 节点
# ============================================================

class GlobalPlannerNode(Node):
    def __init__(self):
        super().__init__('global_planner')

        # ---------- 地图层 ----------
        self.declare_parameter('inflation_radius', 0.30)  # 车半径 + 安全边
        # occupancy_threshold 是 ROS OccupancyGrid 0..100 的占据阈值
        # 来自 /map (ros nav2_map_server 已做 negate/threshold 转换)
        # 50 = 经典 nav2 默认; > 50 视为占据, <= 50 视为可走
        self.declare_parameter('occupancy_threshold', 50)
        self.declare_parameter('min_rebuild_interval', 2.0)

        # ---------- 目标点吸附 ----------
        self.declare_parameter('snap_radius', 1.0)
        self.declare_parameter('enable_snap', True)

        # ---------- /scan 软更新层 ----------
        self.declare_parameter('enable_scan_layer', True)
        self.declare_parameter('scan_layer_decay_s', 1.0)
        self.declare_parameter('scan_inflate_radius', 0.18)
        self.declare_parameter('scan_min_range', 0.20)
        self.declare_parameter('scan_max_range', 8.0)
        self.declare_parameter('scan_layer_publish', True)

        self.inflation_r = self.get_parameter('inflation_radius').value
        self.occ_thr = self.get_parameter('occupancy_threshold').value
        self.rebuild_interval = self.get_parameter('min_rebuild_interval').value
        self.snap_r = self.get_parameter('snap_radius').value
        self.snap_on = self.get_parameter('enable_snap').value
        self.scan_on = self.get_parameter('enable_scan_layer').value
        self.scan_decay = self.get_parameter('scan_layer_decay_s').value
        self.scan_inflate = self.get_parameter('scan_inflate_radius').value
        self.scan_min = self.get_parameter('scan_min_range').value
        self.scan_max = self.get_parameter('scan_max_range').value
        self.scan_pub = self.get_parameter('scan_layer_publish').value

        # ---------- 状态 ----------
        self.map_msg = None
        self._map_raw = None
        self._last_build = 0.0
        self.astar = None
        self.robot_frame = 'base_footprint'

        # /scan 软更新: 最近一帧的点云(odom 系), 每帧加时间戳
        self.scan_points = []  # [(x_odom, y_odom, stamp)]
        self._last_scan_stamp = None

        # ---------- 通信 ----------
        self.map_sub = self.create_subscription(
            OccupancyGrid, '/map', self.on_map, 1)
        self.scan_sub = self.create_subscription(
            LaserScan, '/scan', self.on_scan, 10)
        self.goal_sub = self.create_subscription(
            PoseStamped, '/goal_pose', self.on_goal, 10)
        self.path_pub = self.create_publisher(Path, '/global_path', 1)
        if self.scan_pub:
            self.marker_pub = self.create_publisher(
                MarkerArray, '/costmap_scan_marks', 1)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.get_logger().info(
            f'A* ready: inflation={self.inflation_r}m occ_thr={self.occ_thr} '
            f'scan_layer={self.scan_on} decay={self.scan_decay}s '
            f'snap={self.snap_on} r={self.snap_r}m')

    # ============================================================
    # /map 回调: 构建栅格 + 膨胀层
    # ============================================================
    def on_map(self, msg: OccupancyGrid):
        raw = bytes(msg.data)
        if raw == self._map_raw:
            return
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self._last_build < self.rebuild_interval:
            return
        self._last_build = now
        self._map_raw = raw
        self.map_msg = msg

        self._rebuild_static_layer()

    def _rebuild_static_layer(self):
        msg = self.map_msg
        w, h = msg.info.width, msg.info.height
        res = msg.info.resolution
        ox, oy = msg.info.origin.position.x, msg.info.origin.position.y

        # /map 是 nav2_map_server 已转换的 OccupancyGrid:
        #   value < 0            -> unknown (=-1), 默认当障碍防危险
        #   value > occ_thr       -> 占据
        #   其余                  -> 可走
        # 旧实现拿 raw PGM 灰度 0-254 与 60 比, 把整间房全判成障碍 (96.6% 占据),
        # 导致 A* 在一团黑里找不到路. 这里是该 bug 的根因.
        data = np.asarray(msg.data, dtype=np.int8).reshape((h, w))
        occ = ((data > self.occ_thr) | (data < 0)).astype(np.uint8)

        from scipy import ndimage
        inflate_px = max(1, int(round(self.inflation_r / res)))
        radius = np.zeros((2 * inflate_px + 1, 2 * inflate_px + 1))
        rr, cc = np.mgrid[-inflate_px:inflate_px + 1,
                          -inflate_px:inflate_px + 1]
        radius[rr * rr + cc * cc <= inflate_px * inflate_px] = 1
        static_inflated = ndimage.binary_dilation(
            occ.astype(bool), structure=radius).astype(np.uint8)

        self.static_occ = static_inflated
        self.static_meta = (ox, oy, res, w, h)
        self._rebuild_combined_occ()
        self.get_logger().info(
            f'Map (re)built {w}x{h} res={res}, '
            f'{occ.sum()} occupied px -> {static_inflated.sum()} inflated px')

    def _rebuild_combined_occ(self):
        """把 /scan 软更新层叠进 static_occ.

        软更新层的语义:
            scan 实时探测到点的 → 在 inflated 层里也临时标 1, 持续 scan_decay 秒
            之后自动"褪色"成 0, 不污染静态地图.
        这就是用户要的"把 /scan 的实时障碍叠到 costmap 上"——
        临时放的椅子墩子会立刻被 A* 看见, 不挡一会就消失.
        """
        ox, oy, res, w, h = self.static_meta
        # 起点: 静态膨胀层
        combined = self.static_occ.copy()

        if not self.scan_on or not self.scan_points:
            self.astar = AStar8(combined, res, (ox, oy))
            return

        # 只保留 scan_decay 秒内的点
        now = self.get_clock().now().nanoseconds / 1e9
        fresh = [(px, py) for (px, py, st) in self.scan_points
                 if now - st <= self.scan_decay]
        self.scan_points = [(px, py, st) for (px, py, st) in self.scan_points
                            if now - st <= self.scan_decay]

        if not self.scan_points:
            self.astar = AStar8(combined, res, (ox, oy))
            return

        # 把 odom 系的点投到 map 系
        try:
            tx, ty, yaw = self._lookup_yaw('map', 'odom')
            cy, sy = math.cos(yaw), math.sin(yaw)
            scan_map = [(tx + px * cy - py * sy, ty + px * sy + py * cy)
                        for (px, py, _) in fresh]
        except Exception as e:
            self.get_logger().warn(
                f'tf odom->map 不可用, 跳过 scan 软更新: {e}')
            self.astar = AStar8(combined, res, (ox, oy))
            return

        # 在栅格里打点 + 二次膨胀
        scan_layer = np.zeros((h, w), dtype=np.uint8)
        for (x, y) in scan_map:
            col = int((x - ox) / res)
            row = int((y - oy) / res)
            if 0 <= row < h and 0 <= col < w:
                scan_layer[row, col] = 1
        if scan_layer.any():
            from scipy import ndimage
            r_px = max(1, int(round(self.scan_inflate / res)))
            radius = np.zeros((2 * r_px + 1, 2 * r_px + 1))
            rr, cc = np.mgrid[-r_px:r_px + 1, -r_px:r_px + 1]
            radius[rr * rr + cc * cc <= r_px * r_px] = 1
            scan_layer = ndimage.binary_dilation(
                scan_layer.astype(bool), structure=radius).astype(np.uint8)
            combined = np.maximum(combined, scan_layer)
            self.get_logger().info(
                f'Scan layer: {len(fresh)} fresh pts -> '
                f'{scan_layer.sum()} px in costmap '
                f'(+{(combined.sum() - self.static_occ.sum())} over static)')

        self.astar = AStar8(combined, res, (ox, oy))

    # ============================================================
    # /scan 回调: 缓存最近 1 秒的点云(odom 系)
    # ============================================================
    def on_scan(self, msg: LaserScan):
        if not self.scan_on:
            return
        n = len(msg.ranges)
        angles = msg.angle_min + np.arange(n) * msg.angle_increment
        ranges = np.asarray(msg.ranges, dtype=np.float64)
        valid = np.isfinite(ranges) \
            & (ranges > self.scan_min) \
            & (ranges < msg.range_max - 0.1) \
            & (ranges < self.scan_max)
        r = ranges[valid]
        a = angles[valid]
        # laser 系下的点(平面)
        pts_laser = np.stack([r * np.cos(a), r * np.sin(a)], axis=1)
        # laser → base_footprint → odom, 简化为 base_footprint → odom
        try:
            tx, ty, yaw = self._lookup_yaw('odom', 'base_footprint')
            cy, sy = math.cos(yaw), math.sin(yaw)
            rot = np.array([[cy, -sy], [sy, cy]])
            pts_odom = pts_laser @ rot.T + np.array([tx, ty])
        except Exception:
            return

        # 直接转 odom 系坐标 + 时间戳
        now = self.get_clock().now().nanoseconds / 1e9
        if self._last_scan_stamp is not None and now - self._last_scan_stamp < 0.05:
            return  # 节流: 同一帧的多个 scan 不重复叠
        self._last_scan_stamp = now
        # 太密的栅格每帧加 2000+ 个点会把 costmap 撑爆, 随机抽样到 ~400
        if len(pts_odom) > 400:
            sel = np.random.choice(len(pts_odom), 400, replace=False)
            pts_odom = pts_odom[sel]
        self.scan_points = [(float(x), float(y), now)
                            for (x, y) in pts_odom]

    # ============================================================
    # /goal_pose 回调: A* 规划
    # ============================================================
    def on_goal(self, msg: PoseStamped):
        if self.astar is None or self.map_msg is None:
            self.get_logger().warn('No map yet, ignore goal')
            return

        goal_world = self.frame_to_map(
            msg.header.frame_id,
            (msg.pose.position.x, msg.pose.position.y))
        if goal_world is None:
            self.get_logger().warn('Cannot transform goal frame, ignore')
            return

        start_world = self.get_robot_pose_map()
        if start_world is None:
            self.get_logger().warn('No robot pose in map, ignore')
            return

        # 1) 目标点吸附到最近可走格 ——
        # GUI 派单很可能落在墙/桌沿; 没必要让桥拒收,
        # 在 A* 这一层做 "snap 到可走点" 更稳.
        snapped_x, snapped_y, did_snap, snap_dist = \
            self.astar.snap_to_free(*goal_world, radius_m=self.snap_r)
        if did_snap:
            self.get_logger().info(
                f'Goal snapped {snap_dist * 100:.0f}cm to '
                f'({snapped_x:+.2f},{snapped_y:+.2f})')

        # 2) 起点吸附(车当前位置贴墙时; 通常用不上, 兜底)
        start_snapped, _, did_snap2, _ = \
            self.astar.snap_to_free(*start_world, radius_m=self.snap_r)
        if did_snap2:
            self.get_logger().warn(
                f'Start snapped to ({start_snapped[0]:+.2f},'
                f'{start_snapped[1]:+.2f})')
            start_world = start_snapped

        # 3) A*
        self.get_logger().info(
            f'Plan: start({start_world[0]:.2f},{start_world[1]:.2f}) '
            f'-> goal({snapped_x:+.2f},{snapped_y:+.2f})')
        path_world = self.astar.search(start_world, (snapped_x, snapped_y))
        if path_world is None:
            self.get_logger().warn(
                'A* failed (no path). 起点附近可能全是障碍; '
                '把车挪一下再点')
            return

        self.publish_path(path_world, msg.header)

    # ============================================================
    # TF 工具
    # ============================================================
    def _lookup_yaw(self, target, source):
        from rclpy.time import Time
        from rclpy.duration import Duration
        t = self.tf_buffer.lookup_transform(
            target, source, Time(), timeout=Duration(seconds=0.2))
        q = t.transform.rotation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        return t.transform.translation.x, t.transform.translation.y, yaw

    def frame_to_map(self, frame, point):
        if frame in ('', 'map'):
            return point
        try:
            tx, ty, yaw = self._lookup_yaw('map', frame)
        except Exception as e:
            self.get_logger().warn(f'tf {frame}->map failed: {e}')
            return None
        cy, sy = math.cos(yaw), math.sin(yaw)
        px, py = point
        return (tx + px * cy - py * sy, ty + px * sy + py * cy)

    def get_robot_pose_map(self):
        try:
            tx, ty, _ = self._lookup_yaw('map', self.robot_frame)
            return (tx, ty)
        except Exception as e:
            self.get_logger().warn(f'no map->{self.robot_frame} tf: {e}')
            return None

    # ============================================================
    # 发布
    # ============================================================
    def publish_path(self, path_world, header):
        path = Path()
        path.header.frame_id = 'map'
        path.header.stamp = self.get_clock().now().to_msg()
        for (x, y) in path_world:
            ps = PoseStamped()
            ps.header.frame_id = 'map'
            ps.pose.position.x = x
            ps.pose.position.y = y
            ps.pose.orientation.w = 1.0
            path.poses.append(ps)
        self.path_pub.publish(path)
        self.get_logger().info(
            f'Published global_path with {len(path.poses)} points')

    # ============================================================
    # 节流
    # ============================================================
    def log_throttled(self, text, interval=2.0):
        if not hasattr(self, '_log_last_t'):
            self._log_last_t = 0.0
            self._log_last = ''
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self._log_last_t >= interval or text != self._log_last:
            self._log_last_t = now
            self._log_last = text
            self.get_logger().info(text)


def main(args=None):
    rclpy.init(args=args)
    node = GlobalPlannerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()