#!/usr/bin/env python3
"""A* 全局规划节点 —— 自主导航三层中的最上层.

订阅:
    /map          (nav_msgs/msg/OccupancyGrid)  已建好的栅格地图(带膨胀层)
    /goal_pose    (geometry_msgs/msg/PoseStamped) 目标点(可指定任意 frame, 内部转到 map 系)

发布:
    /global_path  (nav_msgs/msg/Path)   A* 找出的全局路径(供 DWA 跟踪)

流程:
    1. 收到 /map → 构建栅格 + 膨胀层(车体半径)
    2. 收到 /goal_pose → 起点(当前 TF) + 终点 → A* 搜索
    3. 发布 /global_path(m个点, map 系)

A* 核心: f = g + h
    g: 从起点走到该格的实际代价
    h: 该格到终点的欧氏距离(启发式, 八邻域可用 openlist 优先 f)
"""
import math
import heapq

import numpy as np
import rclpy
from rclpy.node import Node
from nav_msgs.msg import OccupancyGrid, Path
from geometry_msgs.msg import PoseStamped
from tf2_ros import Buffer, TransformListener


# ============================================================
# 8 邻域方向(顺序: 上下左右 + 四个斜角)
# ============================================================
DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1),   # 直线
        (-1, -1), (1, -1), (-1, 1), (1, 1)]  # 斜角
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

    # ---------- 坐标转换 ----------
    def world_to_grid(self, x, y):
        """世界坐标 → 栅格(整数行列)"""
        gx = int(round((x - self.origin[0]) / self.res))
        gy = int(round((y - self.origin[1]) / self.res))
        return gy, gx

    def grid_to_world(self, row, col):
        """栅格 → 世界坐标(格中心)"""
        x = self.origin[0] + (col + 0.5) * self.res
        y = self.origin[1] + (row + 0.5) * self.res
        return x, y

    def is_free(self, r, c):
        if r < 0 or r >= self.h or c < 0 or c >= self.w:
            return False
        return self.occ[r, c] == 0

    # ---------- A* 搜索 ----------
    def search(self, start_world, goal_world):
        """start_world/goal_world 是世界坐标(x,y).
        返回世界坐标点列表 [(x1,y1), (x2,y2), ...] 含起点不含终点; 失败返回 None.
        """
        sr, sc = self.world_to_grid(*start_world)
        gr, gc = self.world_to_grid(*goal_world)

        if not self.is_free(sr, sc):
            print(f'[A*] start in obstacle: r={sr} c={sc}', flush=True)
            return None
        if not self.is_free(gr, gc):
            print(f'[A*] goal in obstacle: r={gr} c={gc}', flush=True)
            return None

        # g_score[r][c]
        g_score = np.full((self.h, self.w), np.inf)
        g_score[sr, sc] = 0.0

        parent = {}

        # open 优先队列: (f, row, col); closed 集合用 visited 标记
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
        """启发式: 到终点的直角距离(八邻域下保证 ≥ 实际最短代价)"""
        dr = abs(r - gr)
        dc = abs(c - gc)
        return max(dr, dc) + (DIAG_COST - 1.0) * min(dr, dc)

    def reconstruct_path(self, parent, start, goal):
        """从 goal 回溯到 start"""
        path_g = [goal]
        cur = goal
        while cur != start:
            cur = parent[cur]
            path_g.append(cur)
        path_g.reverse()          # start → goal 的栅格序列
        # 转世界坐标
        world = []
        for (r, c) in path_g:
            x, y = self.grid_to_world(r, c)
            world.append((x, y))
        return world


# ============================================================
# ROS2 节点
# ============================================================

class GlobalPlannerNode(Node):
    def __init__(self):
        super().__init__('global_planner')

        self.declare_parameter('inflation_radius', 0.28)  # 车半径 + 安全边
        self.declare_parameter('occupancy_threshold', 60)  # 地图值 >= 此视为障碍(%)
        self.declare_parameter('goal_frame', 'map')

        self.inflation_r = self.get_parameter('inflation_radius').value
        self.occ_thr = self.get_parameter('occupancy_threshold').value

        self.map_msg = None
        self.astar = None
        self.robot_frame = 'base_footprint'

        self.map_sub = self.create_subscription(
            OccupancyGrid, '/map', self.on_map, 1)
        self.goal_sub = self.create_subscription(
            PoseStamped, '/goal_pose', self.on_goal, 1)
        self.path_pub = self.create_publisher(Path, '/global_path', 1)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.get_logger().info(
            f'A* ready: inflation={self.inflation_r}m occ_thr={self.occ_thr}')

    # ---------- 地图缓存 + 膨胀 ----------
    def on_map(self, msg: OccupancyGrid):
        if self.map_msg is not None:
            return  # 地图已就绪(避免重复膨胀)
        self.map_msg = msg

        w, h = msg.info.width, msg.info.height
        res = msg.info.resolution
        ox, oy = msg.info.origin.position.x, msg.info.origin.position.y

        data = np.asarray(msg.data, dtype=np.int8).reshape((h, w))
        # 障碍: 值 >= 阈值; 未知(-1)也当作障碍(保守, 避免踩进没建图区域)
        occ = (data >= self.occ_thr).astype(np.uint8)

        # ----- 膨胀层: 把每个障碍向外"吹"一圈 -----
        inflate_px = max(1, int(round(self.inflation_r / res)))
        from scipy import ndimage
        radius = np.zeros((2 * inflate_px + 1, 2 * inflate_px + 1))
        rr, cc = np.mgrid[-inflate_px:inflate_px + 1,
                          -inflate_px:inflate_px + 1]
        radius[rr * rr + cc * cc <= inflate_px * inflate_px] = 1
        inflated = ndimage.binary_dilation(
            occ.astype(bool), structure=radius).astype(np.uint8)

        self.astar = AStar8(inflated, res, (ox, oy))
        self.get_logger().info(
            f'Map {w}x{h} res={res}, inflation {inflate_px}px, '
            f'{occ.sum()} occupied px -> {inflated.sum()} inflated px')

    # ---------- 目标触发规划 ----------
    def on_goal(self, msg: PoseStamped):
        if self.astar is None or self.map_msg is None:
            self.get_logger().warn('No map yet, ignore goal')
            return

        # 终点: 从 goal_frame 转到 map 系
        goal_world = self.frame_to_map(
            msg.header.frame_id,
            (msg.pose.position.x, msg.pose.position.y))

        if goal_world is None:
            self.get_logger().warn('Cannot transform goal frame, ignore')
            return

        # 起点: 机器人当前在 map 系的位置
        start_world = self.get_robot_pose_map()
        if start_world is None:
            self.get_logger().warn('No robot pose in map, ignore')
            return

        self.get_logger().info(
            f'Plan: start({start_world[0]:.2f},{start_world[1]:.2f}) '
            f'-> goal({goal_world[0]:.2f},{goal_world[1]:.2f})')

        path_world = self.astar.search(start_world, goal_world)
        if path_world is None:
            self.get_logger().warn('A* failed (no path)')
            return

        self.publish_path(path_world, msg.header)

    # ---------- TF 工具 ----------
    def frame_to_map(self, frame, point):
        """把任意 frame 里的点变换到 map 系. 可直接用 map 自身."""
        if frame in ('', 'map'):
            return point
        try:
            t = self.tf_buffer.lookup_transform(
                'map', frame, rclpy.time.Time(), timeout=rclpy.duration.Duration(seconds=0.5))
            ex, ey = point[0] + t.transform.translation.x, \
                     point[1] + t.transform.translation.y
            return ex, ey
        except Exception as e:
            self.get_logger().warn(f'tf {frame}->map failed: {e}')
            return None

    def get_robot_pose_map(self):
        try:
            t = self.tf_buffer.lookup_transform(
                'map', self.robot_frame, rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=0.5))
            return (t.transform.translation.x, t.transform.translation.y)
        except Exception as e:
            self.get_logger().warn(f'no map->{self.robot_frame} tf: {e}')
            return None

    # ---------- 发布路径 ----------
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