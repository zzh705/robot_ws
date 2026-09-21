"""robot_comm —— GUI 与板端 goal_bridge 节点之间的通信层。

支持的命令:

  1. 任意坐标派单(GUI 地图点击 / 语音找书都走这条)
     send_goto_xy(x=1.5, y=0.5, book_name="三体")
     -> 协议: {"command": "goto", "x": 1.5, "y": 0.5,
                "book_name": "三体", "frame": "map"}

  2. 区号映射派单(向下兼容旧 GUI "寻找图书" 详情页)
     send_go_to(location="A", book_name="三体")
     -> 协议: {"command": "find_book", "book_name": "三体",
                "location": "A"}

返回: (ok: bool, message: str)
"""
import json
import socket

ROBOT_HOST = "127.0.0.1"
ROBOT_PORT = 9000
TIMEOUT = 3


def _send(payload):
    """底层发送: JSON + \\n, 接收一行响应。"""
    try:
        with socket.create_connection(
            (ROBOT_HOST, ROBOT_PORT), timeout=TIMEOUT) as sock:
            sock.sendall(
                (json.dumps(payload, ensure_ascii=False) + "\n")
                .encode("utf-8"))
            data = sock.recv(4096).decode("utf-8").strip()
        if not data:
            return False, "机器人没有返回消息"
        resp = json.loads(data)
        return bool(resp.get("ok")), resp.get(
            "message", "机器人已收到指令")
    except Exception as e:
        return False, f"机器人通信失败：{e}"


def send_goto_xy(x, y, book_name="", frame="map"):
    """派单: 让机器人前往地图坐标 (x, y)。

    GUI 地图点击 -> send_goto_xy(click_x, click_y)
    语音找书     -> send_goto_xy(bookmark['goal_x'], bookmark['goal_y'],
                                 book_name=书名)
    """
    payload = {
        "command": "goto",
        "x": float(x),
        "y": float(y),
        "frame": frame,
        "book_name": book_name or "",
    }
    return _send(payload)


def send_go_to(location, book_name=""):
    """派单: 让机器人前往区号 (A/B/C/D) —— 仅向下兼容。

    新代码请用 send_goto_xy(x, y)。库表 location 不为空时仍可走这条。
    """
    payload = {
        "command": "find_book",
        "book_name": book_name or "",
        "location": location or "",
    }
    return _send(payload)
