#!/usr/bin/env python3
"""goal_bridge_node —— 上位机 "找书" 与导航三层之间的桥.

GUI 通过 TCP(127.0.0.1:9000)发送:
    {"command": "find_book", "book_name": "三体", "location": "A"}

本节点:
    1. 常驻监听 9000 端口(与 GUI 的 robot_comm.send_go_to 兼容)
    2. 解析 location → 通过映射表得到地图坐标(map 系)
    3. 发布 /goal_pose → 触发导航三层(A*→DWA→PID)
    4. 回给 GUI: {"ok": true, "message": "..."}

location 映射: 库表 location 是区号 (A/B/C/D), 在此映射为地图坐标 (x, y).
坐标在 nav.launch.py 里通过参数传入, 真机标定后只需改 launch.
"""
import json
import socket
import threading

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped


class GoalBridge(Node):
    def __init__(self):
        super().__init__('goal_bridge')

        # =====================
        # location -> 地图坐标 映射表(参数, 标定后改 launch 即可)
        # =====================
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

        # =====================
        # 目标点发布
        # =====================
        self.goal_pub = self.create_publisher(
            PoseStamped, '/goal_pose', 10)

        # =====================
        # TCP 服务器线程(接收 GUI 指令)
        # =====================
        self.host = self.declare_parameter('tcp_host', '127.0.0.1').value
        self.port = self.declare_parameter('tcp_port', 9000).value

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(5)
        self.server.settimeout(1.0)  # 让 accept 定时醒来, 节点可正常关闭

        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

        self.get_logger().info(
            f'Listening on {self.host}:{self.port}')

    # ============================================================
    # TCP 服务: 每连接一请求
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
        # 读一行(以 \n 结尾)
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
        book = payload.get('book_name', '')
        location = payload.get('location', '')

        self.get_logger().info(
            f'Recv from {addr}: command={cmd} book={book} loc={location}')

        if cmd != 'find_book':
            self._reply(conn, False, f'未知命令: {cmd}')
            return

        coord = self.locations.get(location)
        if coord is None:
            self._reply(conn, False,
                        f'未配置位置映射: {location or "(空)"} (支持 A/B/C/D)')
            return

        # 发布 /goal_pose(map 系)
        self.publish_goal(book, location, coord)
        self._reply(conn, True,
                    f'正在前往 {location} 区 (x={coord[0]:.2f}, y={coord[1]:.2f})')

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
    node = GoalBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()