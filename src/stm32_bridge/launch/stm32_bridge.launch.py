#!/usr/bin/env python3
"""stm32_bridge launch — 启动 STM32 串口桥接节点

用法（默认用 /dev/ttyACM0）：
    ros2 launch stm32_bridge stm32_bridge.launch.py

指定其他串口：
    ros2 launch stm32_bridge stm32_bridge.launch.py port:=/dev/ttyACM0
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # 可配置参数：串口设备路径
    port_arg = DeclareLaunchArgument(
        'port',
        default_value='/dev/ttyACM0',
        description='STM32 串口设备路径'
    )

    bridge_node = Node(
        package='stm32_bridge',
        executable='stm32_bridge_node',
        name='stm32_bridge',
        output='screen',
        parameters=[{
            'port': LaunchConfiguration('port'),
        }],
    )

    return LaunchDescription([
        port_arg,
        bridge_node,
    ])