#!/usr/bin/env python3
"""file_cmd_vel.py — 从文件/命名管道读取遥控指令, 发布到 /cmd_vel。

彻底绕开 X 终端焦点问题。读取以下任一来源的字符指令:
  - 普通文件, 如 /tmp/teleop_cmd (按写入增量读取)
  - 具名管道 FIFO, 如 /home/sunrise/teleop_fifo (echo i > fifo)

指令: i=前进  k=停  j=左转  l=右转  u=左前  o=右前  m=后退  q=退出

注: 早期实现不分文件类型, 对 FIFO 也调 f.seek()/f.tell() —— 管道上必然抛
"underlying stream is not seekable", 而且 open() 会一直阻塞到有写者,
结果是 start_file_cmd.sh 里的 echo i > fifo 根本发不出指令。
现在按 stat 判定类型, FIFO 用 O_NONBLOCK + select 读。
"""
import os, stat, sys, time, select, argparse

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class FileCmdVel(Node):
    def __init__(self, speed, turn, cmd_file='/tmp/teleop_cmd'):
        super().__init__('file_cmd_vel')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.speed, self.turn = speed, turn
        self.cmd_file = cmd_file
        self.last = None
        self.last_pos = 0
        self.fifo_fd = None
        self.buf = b''
        self._conflict_warned = False

    # ---------- 指令来源: 普通文件 ----------

    def open_source(self):
        """FIFO 用非阻塞只读打开; 普通文件不需要常驻 fd。"""
        if os.path.exists(self.cmd_file) and \
                stat.S_ISFIFO(os.stat(self.cmd_file).st_mode):
            # O_NONBLOCK: 没有写者时也立刻返回, 不像 open() 那样阻塞住整个循环
            self.fifo_fd = os.open(self.cmd_file, os.O_RDONLY | os.O_NONBLOCK)
            return True
        return False

    def poll_source(self):
        if self.fifo_fd is not None:
            self._poll_fifo()
        else:
            self._poll_file()

    def _poll_fifo(self):
        try:
            ready, _, _ = select.select([self.fifo_fd], [], [], 0)
        except Exception:
            return
        if not ready:
            return
        try:
            chunk = os.read(self.fifo_fd, 4096)
        except BlockingIOError:
            return
        except OSError as e:
            print(f"fifo err: {e}", flush=True)
            return
        if not chunk:
            return  # 写者关闭时 FIFO 读到 EOF, 属正常
        self.buf += chunk
        while b'\n' in self.buf:
            line, self.buf = self.buf.split(b'\n', 1)
            for ch in line.decode('utf-8', 'ignore').strip():
                self.handle(ch)

    def _poll_file(self):
        try:
            size = os.path.getsize(self.cmd_file)
            if size < self.last_pos:
                self.last_pos = 0          # 文件被截断/重写
            if size == self.last_pos:
                return
            with open(self.cmd_file, 'rb') as f:
                f.seek(self.last_pos)
                data = f.read()
                self.last_pos = f.tell()
        except Exception as e:
            print(f"file err: {e}", flush=True)
            return
        for line in data.decode('utf-8', 'ignore').splitlines():
            for ch in line.strip():
                self.handle(ch)

    def check_conflict(self):
        """/cmd_vel 上出现其它发布者时告警一次(导航 pid_controller / 键盘遥控)。"""
        if self._conflict_warned:
            return
        n = self.count_publishers('/cmd_vel')
        if n > 1:
            self._conflict_warned = True
            self.get_logger().warn(
                f'/cmd_vel 上当前有 {n} 个发布者(含本节点)。'
                f'导航栈在跑时两边会互相抢底盘, 遥控前请先停掉 nav.launch.py')

    def send(self, linear, angular):
        msg = Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self.pub.publish(msg)
        if msg.linear.x != 0 or msg.angular.z != 0:
            print(f"cmd_vel: linear.x={linear:.2f} angular.z={angular:.2f}")

    def handle(self, c):
        c = (c or '').strip().lower()
        if not c:
            return
        if c == 'i':
            self.send(self.speed, 0.0)
        elif c == 'j':
            self.send(0.0, self.turn)
        elif c == 'l':
            self.send(0.0, -self.turn)
        elif c == 'u':
            self.send(self.speed * 0.7, self.turn)
        elif c == 'o':
            self.send(self.speed * 0.7, -self.turn)
        elif c == 'm':
            self.send(-self.speed * 0.6, 0.0)
        elif c == 'k' or c == ',' or c == 's':
            self.send(0.0, 0.0)
        elif c == 'q':
            print("收到 q, 退出")
            os.kill(os.getpid(), 15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--speed', type=float, default=0.2)
    ap.add_argument('--turn', type=float, default=0.5)
    ap.add_argument('--cmd-file', type=str, default='/tmp/teleop_cmd')
    args = ap.parse_args()

    # 创建命令文件 (如果不存在)
    if not os.path.exists(args.cmd_file):
        open(args.cmd_file, 'w').close()

    rclpy.init()
    node = FileCmdVel(args.speed, args.turn, args.cmd_file)
    is_fifo = False
    try:
        is_fifo = node.open_source()
    except Exception as e:
        print(f"打开指令源失败: {e}", flush=True)

    print(f"=== file_cmd_vel 已启动 ===", flush=True)
    print(f"  指令来源: {args.cmd_file} ({'FIFO' if is_fifo else '普通文件'})", flush=True)
    print(f"  往该文件写字符: i前进 k停 j左转 l右转 u左前 o右前 m后退 q退出", flush=True)
    print(f"  例: echo i > {args.cmd_file}", flush=True)

    try:
        while rclpy.ok():
            node.poll_source()
            node.check_conflict()
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.send(0.0, 0.0)
        rclpy.shutdown()


if __name__ == '__main__':
    main()