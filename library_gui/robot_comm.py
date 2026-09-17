import json
import socket

ROBOT_HOST = "127.0.0.1"
ROBOT_PORT = 9000
TIMEOUT = 3


def send_go_to(location, book_name):
    """
    将图书名称和图书位置发送给机器人接收程序。

    当前阶段只负责通信，不负责机器人导航。
    """

    payload = {
        "command": "find_book",
        "book_name": book_name or "",
        "location": location or "",
    }

    try:
        with socket.create_connection(
            (ROBOT_HOST, ROBOT_PORT),
            timeout=TIMEOUT
        ) as sock:

            message = json.dumps(
                payload,
                ensure_ascii=False
            ) + "\n"

            sock.sendall(message.encode("utf-8"))

            data = sock.recv(4096).decode("utf-8").strip()

        if not data:
            return False, "机器人没有返回消息"

        response = json.loads(data)

        return (
            bool(response.get("ok")),
            response.get(
                "message",
                "机器人已收到指令"
            )
        )

    except Exception as e:
        return False, f"机器人通信失败：{e}"