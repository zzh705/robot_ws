#!/usr/bin/env python3
"""nav_health.py — GUI 端用: 探测 9000 端口, 提示用户是否需要启动导航栈.

用法:
    python3 scripts/nav_health.py
返回 JSON: {"ok": true/false, "message": "..."}.
GUI 调用, 失败时弹出"启动导航栈"按钮(执行 bash scripts/nav_up.sh).
"""
import json
import socket
import subprocess
import sys
import time


def probe_port(host='127.0.0.1', port=9000, timeout=0.6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def main():
    if probe_port():
        print(json.dumps(
            {'ok': True,
             'message': '导航桥 goal_bridge 在线 (9000)'},
            ensure_ascii=False))
        return 0
    # 顺便就下 ROS2 节点, 帮助排查
    try:
        out = subprocess.run(
            ['bash', '-c',
             'source /opt/ros/humble/setup.bash && '
             'source /home/sunrise/robot_ws/install/setup.bash && '
             'ros2 node list 2>/dev/null'],
            capture_output=True, text=True, timeout=4).stdout.strip()
        n_nodes = len(out.splitlines()) if out else 0
    except Exception:
        n_nodes = -1
    print(json.dumps(
        {'ok': False,
         'message': (f'导航桥未启动(9000 端口无响应). '
                     f'ros2 节点数={n_nodes}. '
                     f'点击"启动导航栈"或手动 bash scripts/nav_up.sh')},
        ensure_ascii=False))
    return 1


if __name__ == '__main__':
    sys.exit(main())