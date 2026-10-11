#!/usr/bin/env python3
"""stm32_bridge launch — 启动 STM32 串口桥接节点

port 默认留空 = 节点内自动探测（优先 /dev/robot_stm32，再用
/dev/serial/by-id 里的 1a86_*，最后回退第一个 /dev/ttyACM*）。

用法：
    ros2 launch stm32_bridge stm32_bridge.launch.py

显式指定其他串口：
    ros2 launch stm32_bridge stm32_bridge.launch.py port:=/dev/ttyACM0
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # 可配置参数：串口设备路径
    port_arg = DeclareLaunchArgument(
        'port',
        default_value='',
        description='STM32 串口设备路径；留空则自动探测'
    )

    imu_arg = DeclareLaunchArgument(
        'publish_imu',
        default_value='true',
        description='是否把下位机上报的 IMU(TYPE=0x04) 发布成 /imu/data'
    )

    imu_frame_arg = DeclareLaunchArgument(
        'imu_frame_id',
        default_value='base_footprint',
        description='IMU 消息的 frame_id。URDF 里目前没有 imu_link, 用 '
                    'base_footprint 可直接在 RViz 显示; 以后加了 imu_link 再改'
    )

    bridge_node = Node(
        package='stm32_bridge',
        executable='stm32_bridge_node',
        name='stm32_bridge',
        output='screen',
        parameters=[{
            'port': LaunchConfiguration('port'),
            'publish_imu': LaunchConfiguration('publish_imu'),
            'imu_frame_id': LaunchConfiguration('imu_frame_id'),
        }],
    )

    return LaunchDescription([
        port_arg,
        imu_arg,
        imu_frame_arg,
        LogInfo(msg='stm32_bridge: port 留空 → 自动探测 /dev/robot_stm32'),
        bridge_node,
    ])