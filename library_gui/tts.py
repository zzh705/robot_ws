#!/usr/bin/env python3
"""library_gui/tts.py — 通过官方 hobot_tts 节点做语音播报。

链路:
    GUI → 本模块 → 发布 std_msgs/String 到 /tts_text → hobot_tts → 扬声器

前提: hobot_tts 已在运行
    ros2 run hobot_tts hobot_tts
  模型需位于 /opt/tros/humble/lib/hobot_tts/tts_model
  (hobot_tts 二进制里写死了这个相对路径)

说明: 旧版只往 /tts_text 发消息, 而当时没有任何节点在跑 hobot_tts,
所以点"🔊 播放"没有任何反应, 也看不到原因。
现在统一返回 (ok, 说明), 由界面把失败原因显示出来。
"""
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

TOPIC = '/tts_text'

_lock = threading.Lock()
_node = None
_pub = None


def _get_publisher():
    """惰性创建发布者(GUI 进程里没有别处 init rclpy)。"""
    global _node, _pub
    if _pub is not None:
        return _node, _pub
    if not rclpy.ok():
        rclpy.init()
    _node = Node('library_tts_client')
    _pub = _node.create_publisher(String, TOPIC, 10)
    return _node, _pub


def speak(text):
    """把 text 交给 hobot_tts 播报; 返回 (ok, 说明)。

    只发一条 ROS 消息, 不等播完, 因此耗时很短
    (但发现订阅者最多会等 2 秒, 用于给出"节点没启动"的明确错误)。
    """
    text = (text or '').strip()
    if not text:
        return False, '空文本'

    try:
        with _lock:
            node, pub = _get_publisher()
            # 等 DDS 完成发现: 刚启动时订阅者可能还看不到
            for _ in range(20):
                if node.count_subscribers(TOPIC) > 0:
                    break
                rclpy.spin_once(node, timeout_sec=0.1)
            n_sub = node.count_subscribers(TOPIC)

            msg = String()
            msg.data = str(text)
            pub.publish(msg)
            rclpy.spin_once(node, timeout_sec=0.2)
    except Exception as e:
        return False, f'发布 {TOPIC} 失败: {e}'

    if n_sub == 0:
        return False, (
            '没有节点订阅 /tts_text —— hobot_tts 没在跑。请先执行: '
            'ros2 run hobot_tts hobot_tts  (模型需解压到 '
            '/opt/tros/humble/lib/hobot_tts/tts_model)'
        )
    return True, f'已发送 {len(text)} 字到 {TOPIC}'


def shutdown():
    global _node, _pub
    if _node is not None:
        _node.destroy_node()
        _node = None
        _pub = None
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    print(speak('你好，我是图书馆机器人'))
