#!/usr/bin/env python3
"""goal_bridge_node —— 上位机"找书 / 地图点击"与导航三层之间的桥.

GUI 通过 TCP(127.0.0.1:9000)发送 JSON + \\n:

  # 任意坐标(地图点击 / 语音找书都走这条)
  {"command": "goto", "x": 1.5, "y": 0.5, "book_name": "三体"}

  # 区号映射(向下兼容旧 GUI, 不推荐继续用)
  {"command": "find_book", "book_name": "三体", "location": "A"}

本节点:
    1. 常驻监听 9000 端口(与 GUI 的 robot_comm.send_go_to 兼容)
    2. 解析 payload: `goto` 直接用 (x,y); `find_book` 用 location 映射表
    3. 发布 /goal_pose → 触发导航三层(A*→DWA→PID)
    4. 回给 GUI: {"ok": bool, "message": str}

坐标系: ROS map 系。坐标超出地图范围可拒绝(参数 reject_out_of_map,
        默认 True); 地图范围优先取自实时 /map 话题, 启动期无 /map 时
        退到 maps/<yaml>.yaml 静态读(launch 可显式传 map_yaml_path:=...).
"""
import json
import socket
import threading

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import OccupancyGrid


class GoalBridge(Node):
    def __init__(self):
        super().__init__('goal_bridge')

        # ============================================================
        # location -> 地图坐标 映射表(参数, 标定后改 launch 即可)
        # ============================================================
        self.declare_parameter('loc_A_x', 1.0)
        self.declare_parameter('loc_A_y', 1.0)
        self.declare_parameter('loc_B_x', 1.0)
        self.declare_parameter('loc_B_y', 2.5)
        self.declare_parameter('loc_C_x', 3.0)
        self.declare_parameter('loc_C_y', 2.5)
        self.declare_parameter('loc_D_x', 3.0)
        self.declare_parameter('loc_D_y', 1.0)

        self.locations = {
            'A': (self.get_parameter('loc_A_x').value,
                  self.get_parameter('loc_A_y').value),
            'B': (self.get_parameter('loc_B_x').value,
                  self.get_parameter('loc_B_y').value),
            'C': (self.get_parameter('loc_C_x').value,
                  self.get_parameter('loc_C_y').value),
            'D': (self.get_parameter('loc_D_x').value,
                  self.get_parameter('loc_D_y').value),
        }
        self.get_logger().info(
            f'Goal bridge ready. Map: A{self.locations["A"]} '
            f'B{self.locations["B"]} C{self.locations["C"]} '
            f'D{self.locations["D"]}')

        # ============================================================
        # 目标点发布
        # ============================================================
        self.goal_pub = self.create_publisher(
            PoseStamped, '/goal_pose', 10)

        # ============================================================
        # TCP 服务器参数
        # ============================================================
        self.host = self.declare_parameter('tcp_host', '127.0.0.1').value
        self.port = self.declare_parameter('tcp_port', 9000).value
        self.declare_parameter('reject_out_of_map', True)
        self.reject_oob = self.get_parameter('reject_out_of_map').value

        # ============================================================
        # 地图范围(用于坐标范围校验)。
        # 1) 启动期读 maps/room.yaml(可由 launch 改 map_yaml_path)静态获取
        # 2) SLAM 在线后, /map 实时话题来一次就更准一次
        # ============================================================
        from pathlib import Path
        self.map_extents = None
        self._load_map_extents_from_yaml()

        self.map_sub = self.create_subscription(
            OccupancyGrid, '/map', self._on_map, 1)

        # ============================================================
        # 启动 TCP 服务器
        # ============================================================
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server.bind((self.host, self.port))
        except OSError as exc:
            self.server.close()
            self.get_logger().error(
                f'无法监听 {self.host}:{self.port} -> {exc} | '
                f'排查: ss -ltnp | grep :{self.port} ; pgrep -af goal_bridge_node | '
                f'处理: 先停掉占用者, 或用 tcp_port:=9001 换端口'
                f'(同时要改 GUI 侧 robot_comm.ROBOT_PORT)'
            )
            raise
        self.server.listen(5)
        self.server.settimeout(1.0)

        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

        self.get_logger().info(
            f'Listening on {self.host}:{self.port}; '
            f'reject_out_of_map={self.reject_oob}; '
            f'map extents={self.map_extents}')

    # ============================================================
    # 地图范围: YAML 静态 + /map 实时
    # ============================================================
    def _load_map_extents_from_yaml(self):
        from pathlib import Path
        yaml_path = self.declare_parameter(
            'map_yaml_path', '/home/sunrise/robot_ws/maps/room.yaml').value
        ox, oy, w, h, res = -10.0, -10.0, 0, 0, 0.05
        image_name = None
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or ':' not in line:
                        continue
                    key, _, val = line.partition(':')
                    key, val = key.strip(), val.strip()
                    if key == 'resolution':
                        try: res = float(val)
                        except ValueError: pass
                    elif key == 'origin':
                        try:
                            nums = val.strip('[]').split(',')
                            ox, oy = float(nums[0]), float(nums[1])
                        except Exception: pass
                    elif key == 'image':
                        image_name = val
            pgm_path = Path(yaml_path).parent / (image_name or 'room.pgm')
            with open(pgm_path, 'rb') as f:
                head = b''
                while head.count(b'\n') < 3:
                    head += f.read(64)
                parts = head.split(b'\n')
                # PGM 头形如 P5\nW H\n255\n<data>
                # parts[1] = b'W H', split() 后 = [b'W', b'H']
                wh = parts[1].split()
                w, h = int(wh[0]), int(wh[1])
            self.map_extents = (ox, oy, ox + w * res, oy + h * res)
            self.get_logger().info(
                f'map extents from {yaml_path}: '
                f'x=[{ox:.2f}, {ox + w * res:.2f}] '
                f'y=[{oy:.2f}, {oy + h * res:.2f}]')
        except Exception as e:
            self.get_logger().warn(
                f'读地图 YAML 失败 ({e}), 用兜底 20x20m')
            self.map_extents = (-10.0, -10.0, 10.0, 10.0)

    def _on_map(self, msg):
        mi = msg.info
        self.map_extents = (mi.origin.position.x, mi.origin.position.y,
                            mi.origin.position.x + mi.width * mi.resolution,
                            mi.origin.position.y + mi.height * mi.resolution)
        self.get_logger().info(
            f'map extents from /map updated: '
            f'x=[{self.map_extents[0]:.2f}, {self.map_extents[2]:.2f}] '
            f'y=[{self.map_extents[1]:.2f}, {self.map_extents[3]:.2f}]')

    # ============================================================
    # TCP 服务
    # ============================================================
    def _serve(self):
        while rclpy.ok():
            try:
                conn, addr = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(conn, addr)
            except Exception as e:
                self.get_logger().error(f'handle error: {e}')
            finally:
                conn.close()

    def _handle(self, conn, addr):
        data = b''
        while b'\n' not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        line = data.split(b'\n', 1)[0]
        try:
            payload = json.loads(line.decode('utf-8'))
        except Exception as e:
            self._reply(conn, False, f'JSON解析失败: {e}')
            return

        cmd = payload.get('command', '')
        book = payload.get('book_name', '') or ''
        location = payload.get('location', '') or ''
        x = payload.get('x', None)
        y = payload.get('y', None)
        frame = payload.get('frame', 'map')

        self.get_logger().info(
            f'Recv from {addr}: command={cmd} book={book} '
            f'loc={location} x={x} y={y} frame={frame}')

        # ---- 新: 任意坐标 goto(地图点击 / 语音找书都走这条) ----
        if cmd == 'goto':
            try:
                fx = float(x); fy = float(y)
            except (TypeError, ValueError):
                self._reply(conn, False,
                            f'goto 缺坐标或非数值: x={x} y={y}')
                return
            if frame != 'map':
                self._reply(conn, False,
                            f'目前仅支持 map 系, 收到 frame={frame}')
                return
            # 范围校验: 避免 GUI 把 (0,0) 当成"起点"误发
            if self.reject_oob and self.map_extents is not None:
                ox, oy, fx_max, fy_max = self.map_extents
                if not (ox <= fx <= fx_max and oy <= fy <= fy_max):
                    self._reply(
                        conn, False,
                        f'目标 ({fx:.2f},{fy:.2f}) 超出地图范围 '
                        f'x∈[{ox:.2f},{fx_max:.2f}] '
                        f'y∈[{oy:.2f},{fy_max:.2f}]')
                    return
            self.publish_goal(book, f'({fx:.2f},{fy:.2f})', (fx, fy))
            self._reply(conn, True,
                        f'正在前往 ({fx:.2f},{fy:.2f})'
                        + (f' ({book})' if book else ''))
            return

        # ---- 旧: 区号映射 find_book(保持兼容) ----
        if cmd == 'find_book':
            coord = self.locations.get(location)
            if coord is None:
                self._reply(conn, False,
                            f'未配置位置映射: {location or "(空)"} '
                            f'(支持 A/B/C/D)')
                return
            self.publish_goal(book, location, coord)
            self._reply(conn, True,
                        f'正在前往 {location} 区 '
                        f'(x={coord[0]:.2f}, y={coord[1]:.2f})'
                        + (f' ({book})' if book else ''))
            return

        self._reply(conn, False, f'未知命令: {cmd}(支持 goto / find_book)')

    def publish_goal(self, book, location, coord):
        goal = PoseStamped()
        goal.header.frame_id = 'map'
        goal.header.stamp = self.get_clock().now().to_msg()
        goal.pose.position.x = coord[0]
        goal.pose.position.y = coord[1]
        goal.pose.orientation.w = 1.0
        self.goal_pub.publish(goal)
        self.get_logger().info(
            f'Published /goal_pose for "{book}" at {location}: {coord}')

    @staticmethod
    def _reply(conn, ok, message):
        resp = json.dumps(
            {'ok': ok, 'message': message}, ensure_ascii=False) + '\n'
        try:
            conn.sendall(resp.encode('utf-8'))
        except OSError:
            pass


def main(args=None):
    rclpy.init(args=args)
    try:
        node = GoalBridge()
    except OSError as exc:
        print(f'[goal_bridge] 启动失败(端口 9000 被占用?): {exc}', flush=True)
        rclpy.shutdown()
        raise SystemExit(1)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            rclpy.shutdown()
        except Exception:
            pass
        node.destroy_node()


if __name__ == '__main__':
    main()