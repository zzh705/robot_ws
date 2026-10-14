#!/usr/bin/env python3
"""cruise_explore.py — 自主巡航建图（配合 slam_toolbox + A* + DWA）

做什么
    每一步:
      1) 读 /scan, 按"车身坐标系"每 15° 算一个方向的净空(最近障碍距离)
      2) 只在净空 > --min-clear 的方向里挑目标点(优先没去过的方向)
      3) 把目标点发到 /goal_pose(map 系), 由 A* 规划 + DWA 绕障执行
      4) 跟踪 /odom 判断"到达 / 卡死", 记下 /map 的增长

安全设计
    * 只发"短距离"目标(--max-step, 默认 1.0m), 不一口气跑很远
    * 目标方向必须先有足够净空, 不允许朝贴脸的障碍冲
    * 卡死检测: 连续 N 秒位移 < 5cm 就放弃该目标
    * 连续失败 --max-fail 次自动停止
    * 任何时刻可以 Ctrl-C / kill 本脚本停止发新目标;
      彻底停车用: ./start_library_gui.sh stop_nav

坐标约定(已实测确认)
    URDF: base_link→laser yaw = 180°, 所以 激光系角度 = 车身角度 + 180°
    /goal_pose 用 'map' 系; 车的位置/朝向一律从 TF map->base_footprint 取,
    目标 = 车位姿 + step * (cos(yaw + 车身角), sin(yaw + 车身角))。
    (旧版直接拿 /odom 坐标 + 车身角当 map 系目标: map->odom 一漂就全歪,
     2026-10-11 实测漂到 (1.1m, 1.2m, -116°) → 发的目标车根本不去。)

用法
    python3 scripts/cruise_explore.py --dry-run          # 只看净空和打算去哪, 不动车
    python3 scripts/cruise_explore.py --goals 6          # 真的跑 6 个目标点
    python3 scripts/cruise_explore.py --goals 6 --max-step 0.8 --min-clear 0.9
"""
import argparse
import math
import sys
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry, OccupancyGrid
from rclpy.node import Node
from rclpy.duration import Duration
from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy)
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener

LASER_TO_BODY_DEG = 180.0     # URDF 里 base_link→laser 的 yaw(已实测确认)


class Cruise(Node):
    def __init__(self, args):
        super().__init__('cruise_explore')
        self.args = args
        self.scan = None
        self.odom = None
        self.map = None
        self.goal_pub = self.create_publisher(PoseStamped, '/goal_pose', 10)
        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        # /map 是 latched(TRANSIENT_LOCAL) —— 用默认 VOLATILE 会订不到,
        # 一直收不到地图(表现为"地图格数: None")。
        map_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(OccupancyGrid, '/map', self.on_map, map_qos)
        # 车位姿必须走 TF map->base_footprint: /goal_pose 是 map 系,
        # 而 /odom 与 map 之间差一个会漂的 map->odom。
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    # ---------- callbacks ----------
    def on_scan(self, msg):
        self.scan = msg

    def on_odom(self, msg):
        p = msg.pose.pose.position
        self.odom = (p.x, p.y, msg)

    def on_map(self, msg):
        self.map = msg

    # ---------- helpers ----------
    def spin_for(self, dur):
        t_end = time.time() + dur
        while time.time() < t_end:
            rclpy.spin_once(self, timeout_sec=0.1)

    def clearances(self, cone_deg=15.0, cap=3.0):
        """返回 {车身角度(15° 步进): 该方向 ±cone 锥内的最近障碍距离}"""
        s = self.scan
        out = {}
        if s is None:
            return out
        body = []
        for i, r in enumerate(s.ranges):
            if not math.isfinite(r) or r <= 0.05:
                continue
            a = math.degrees(s.angle_min + s.angle_increment * i) + LASER_TO_BODY_DEG
            body.append((a % 360.0, min(r, cap)))
        for phi in range(0, 360, 15):
            near = [r for a, r in body
                    if min(abs(a - phi), 360 - abs(a - phi)) <= cone_deg]
            out[phi] = min(near) if near else cap
        return out

    def pose(self):
        """车在 map 系的位姿 (x, y, yaw)."""
        try:
            t = self.tf_buffer.lookup_transform(
                'map', 'base_footprint', Time(),
                timeout=Duration(seconds=0.2))
        except Exception:
            return None
        q = t.transform.rotation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        return (t.transform.translation.x, t.transform.translation.y, yaw)

    def map_cells(self):
        if self.map is None:
            return None
        return sum(1 for v in self.map.data if v > 50)

    def send_goal(self, x, y, yaw=0.0):
        """发 map 系目标; yaw 传"行进方向", 不要传 0.

        旧版一律 orientation.w=1.0 (yaw=0) → 每个目标都隐含"最终朝 map +x",
        目标在别的方向时 DWA 得先原地转到 +x 才肯前进, 实测 6s+ 还在 Aligning
        (vx=0), 被本脚本的"6s 无位移"误判成卡死 → 白丢目标。
        """
        m = PoseStamped()
        m.header.frame_id = 'map'
        m.header.stamp = self.get_clock().now().to_msg()
        m.pose.position.x = float(x)
        m.pose.position.y = float(y)
        m.pose.orientation.z = math.sin(yaw / 2.0)
        m.pose.orientation.w = math.cos(yaw / 2.0)
        self.goal_pub.publish(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--goals', type=int, default=6, help='最多跑几个目标点')
    ap.add_argument('--max-step', type=float, default=1.0, help='单个目标最远距离 m')
    ap.add_argument('--min-clear', type=float, default=0.85,
                    help='该方向净空低于此值就不去 m')
    ap.add_argument('--dwell', type=float, default=22.0, help='每个目标最多等几秒')
    ap.add_argument('--max-fail', type=int, default=3, help='连续失败几次就停')
    ap.add_argument('--dry-run', action='store_true', help='只算不动车')
    args = ap.parse_args()

    rclpy.init()
    node = Cruise(args)
    print('等待 /scan /odom /map ...', flush=True)
    node.spin_for(6.0)
    if node.scan is None or node.odom is None:
        print('!! 收不到 /scan 或 /odom，导航栈没起来？')
        return 1

    p0 = node.pose()
    if p0 is None:
        print('!! 拿不到 map->base_footprint TF, SLAM/odom 没起来?')
        return 1
    print(f'起点(map): x={p0[0]:+.2f} y={p0[1]:+.2f} '
          f'yaw={math.degrees(p0[2]):+.0f}°')
    print(f'地图已建格数: {node.map_cells()}')

    visited = []
    fails = 0
    done = 0
    for k in range(1, args.goals + 1):
        node.spin_for(1.0)                      # 刷新一帧
        cl = node.clearances()
        if not cl:
            print('!! 没有可用扫描'); break
        cur = node.pose()
        if cur is None:
            print('  !! map->base_footprint TF 丢失, 停止')
            break

        # 排序打印(便于人工判断)
        ordered = sorted(cl.items(), key=lambda kv: -kv[1])
        print(f'\n--- 第 {k}/{args.goals} 个目标 ---')
        print('  净空最好的 6 个方向(车身系): ' +
              ', '.join(f'{d}°:{v:.2f}m' for d, v in ordered[:6]))
        print('  净空最差的 3 个方向: ' +
              ', '.join(f'{d}°:{v:.2f}m' for d, v in ordered[-3:]))

        # 选点: 净空够 + 优先没去过的方向
        best = None
        for phi, clear in ordered:
            if clear < args.min_clear:
                continue
            step = min(clear - 0.35, args.max_step)
            if step < 0.35:
                continue
            # phi 是车身系方向 → 转到 map 系要叠加车头朝向 yaw
            bearing = cur[2] + math.radians(phi)
            gx = cur[0] + step * math.cos(bearing)
            gy = cur[1] + step * math.sin(bearing)
            novelty = min([math.hypot(gx - vx, gy - vy) for vx, vy in visited],
                          default=99.0)
            score = min(clear, 2.5) + 0.6 * min(novelty, 3.0)
            if best is None or score > best[0]:
                best = (score, phi, clear, step, gx, gy, novelty)

        if best is None:
            print('  !! 没有任何方向净空足够(全被围住了) —— 停止')
            break
        _, phi, clear, step, gx, gy, novelty = best
        print(f'  选中: 车身 {phi}° 净空 {clear:.2f}m → 目标 ({gx:+.2f},{gy:+.2f}) '
              f'步长 {step:.2f}m 新颖度 {novelty:.2f}m')

        if args.dry_run:
            print('  (dry-run: 不发目标)')
            continue

        visited.append((gx, gy))
        before = node.pose()
        cells0 = node.map_cells()
        node.send_goal(gx, gy, bearing)
        print('  已发 /goal_pose, 等待执行 ...', flush=True)

        t_end = time.time() + args.dwell
        stuck_since = time.time()
        last = node.pose()
        reached = False
        while time.time() < t_end:
            node.spin_for(0.5)
            cur = node.pose()
            if cur is None:
                continue
            if math.hypot(cur[0] - gx, cur[1] - gy) < 0.20:
                reached = True
                break
            # "有进展"= 位移 >4cm **或** 转角 >9°: DWA 先原地 Aligning
            # (vx=0) 再前进, 只看位移会把"正在转身"误判成卡死。
            if (math.hypot(cur[0] - last[0], cur[1] - last[1]) > 0.04
                    or abs(cur[2] - last[2]) > 0.15):
                last = cur
                stuck_since = time.time()
            elif time.time() - stuck_since > 6.0:
                print('  卡死(6s 无位移且无转角) → 放弃该目标')
                break

        moved = math.hypot(cur[0] - before[0], cur[1] - before[1])
        cells1 = node.map_cells()
        print(f'  结果: {"到达 ✓" if reached else "未到达 ✗"}  '
              f'位移 {moved:.2f}m  地图格数 {cells0} → {cells1}')
        if reached or moved > 0.25:
            done += 1
            fails = 0
        else:
            fails += 1
            if fails >= args.max_fail:
                print(f'!! 连续 {fails} 次没动/没到，停止巡航'); break

    print(f'\n=== 巡航结束: 成功 {done} 个目标, 地图格数 {node.map_cells()} ===')
    print('提示: 保存地图 ./scripts/save_map.sh  或  python3 map_store.py --save "巡航建图"')
    node.destroy_node()
    return 0


if __name__ == '__main__':
    sys.exit(main())
