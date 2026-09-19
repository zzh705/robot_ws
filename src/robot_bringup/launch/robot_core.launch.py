#!/usr/bin/env python3
"""
robot_core.launch.py — 只启动核心 SLAM 链路（不启动 rviz / watchdog）。
供 lidar_watchdog.sh 在雷达断流时重启使用，避免递归启动 watchdog。
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    stm32_bridge_launch = os.path.join(
        get_package_share_directory('stm32_bridge'),
        'launch',
        'stm32_bridge.launch.py'
    )

    rplidar_launch = os.path.join(
        get_package_share_directory('rplidar_ros'),
        'launch',
        'rplidar_a1_launch.py'
    )

    robot_description_launch = os.path.join(
        get_package_share_directory('robot_description'),
        'launch',
        'display.launch.py'
    )

    slam_launch = os.path.join(
        get_package_share_directory('slam_toolbox'),
        'launch',
        'online_async_launch.py'
    )

    slam_config = LaunchConfiguration('slam_config')

    return LaunchDescription([

        DeclareLaunchArgument(
            'stm32_port',
            default_value='/dev/ttyACM0',
            description='STM32 串口设备路径'
        ),
        DeclareLaunchArgument(
            'slam_config',
            default_value='/home/sunrise/robot_ws/config/mapper_params_online_async.yaml',
            description='SLAM 参数文件路径'
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(rplidar_launch)
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(robot_description_launch)
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(slam_launch),
            launch_arguments={
                'slam_params_file': slam_config
            }.items()
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(stm32_bridge_launch),
            launch_arguments={
                'port': LaunchConfiguration('stm32_port')
            }.items()
        )

    ])