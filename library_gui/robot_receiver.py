import json
import socket


HOST = "127.0.0.1"
PORT = 9000


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind((HOST, PORT))
    server.listen(5)

    print(
        f"机器人接收程序已启动：{HOST}:{PORT}",
        flush=True
    )

    print(
        "当前为测试模式：只接收和显示信息，不执行机器人运动。",
        flush=True
    )

    while True:
        conn, addr = server.accept()

        print(f"\n收到连接：{addr}", flush=True)

        try:
            data = b""

            while b"\n" not in data:
                chunk = conn.recv(4096)

                if not chunk:
                    break

                data += chunk

            if not data:
                continue

            message = data.split(b"\n", 1)[0]

            payload = json.loads(
                message.decode("utf-8")
            )

            print(
                "\n========================================",
                flush=True
            )

            print(
                "收到寻找图书指令",
                flush=True
            )

            print(
                f"书名：{payload.get('book_name', '')}",
                flush=True
            )

            print(
                f"位置：{payload.get('location', '')}",
                flush=True
            )

            print(
                "========================================",
                flush=True
            )

            response = {
                "ok": True,
                "message": "已收到图书位置，当前为测试模式"
            }

            response_data = (
                json.dumps(
                    response,
                    ensure_ascii=False
                ) + "\n"
            )

            conn.sendall(
                response_data.encode("utf-8")
            )

        except Exception as e:

            print(
                f"处理消息失败：{e}",
                flush=True
            )

            response = {
                "ok": False,
                "message": f"接收失败：{e}"
            }

            response_data = (
                json.dumps(
                    response,
                    ensure_ascii=False
                ) + "\n"
            )

            conn.sendall(
                response_data.encode("utf-8")
            )

        finally:
            conn.close()


if __name__ == "__main__":
    main()