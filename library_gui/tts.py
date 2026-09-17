
import rclpy

from rclpy.node import Node

from std_msgs.msg import String





class TTSNode(Node):

    def __init__(self):

        super().__init__('library_tts_client')



        self.publisher = self.create_publisher(

            String,

            '/tts_text',

            10

        )





_node = None





def tts(text):

    global _node



    if not text:

        return



    if not rclpy.ok():

        rclpy.init()



    if _node is None:

        _node = TTSNode()



    msg = String()

    msg.data = str(text)



    _node.publisher.publish(msg)



    # 给 ROS 一点时间处理发布

    rclpy.spin_once(_node, timeout_sec=0.1)





def shutdown():

    global _node



    if _node is not None:

        _node.destroy_node()

        _node = None



    if rclpy.ok():

        rclpy.shutdown()





if __name__ == '__main__':

    print("开始 TTS 测试")



    tts("你好")



    print("TTS 消息已经发送")



    shutdown()

