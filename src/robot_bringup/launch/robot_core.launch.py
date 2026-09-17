#!/usr/bin/env python3
"""
robot_core.launch.py — 只启动核心 SLAM 链路（不启动 rviz / watchdog）。
供 lidar_watchdog.sh 在雷达断流时重启使用，避免递归启动 watchdog。
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():

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

    slam_config = '/home/sunrise/robot_ws/config/mapper_params_online_async.yaml'

    return LaunchDescription([

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(rplidar_launch)
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(robot_description_launch)
        ),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='odom_to_base_footprint',
            arguments=[
                '0', '0', '0',
                '0', '0', '0',
                'odom',
                'base_footprint'
            ]
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(slam_launch),
            launch_arguments={
                'slam_params_file': slam_config
            }.items()
        )

    ])