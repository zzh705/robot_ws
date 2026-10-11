#!/usr/bin/env python3
"""
gamepad_teleop.launch.py — 手柄遥控启动文件
用法:
    ros2 launch robot_bringup gamepad_teleop.launch.py
    ros2 launch robot_bringup gamepad_teleop.launch.py joy_dev:=/dev/input/js0
"""
import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    joy_dev = LaunchConfiguration('joy_dev')
    joy_config = LaunchConfiguration('joy_config')

    joy_dev_arg = DeclareLaunchArgument(
        'joy_dev',
        default_value='/dev/input/js0',
        description='Joystick device path'
    )
    joy_config_arg = DeclareLaunchArgument(
        'joy_config',
        default_value='/home/sunrise/robot_ws/config/teleop_joy_config.yaml',
        description='Teleop joy config file'
    )

    return LaunchDescription([
        joy_dev_arg,
        joy_config_arg,

        # joy_node — 读取手柄输入发布 /joy
        Node(
            package='joy',
            executable='joy_node',
            name='joy_node',
            parameters=[joy_config],
            output='screen',
        ),

        # teleop_twist_joy — 将 /joy 转换为 /cmd_vel
        Node(
            package='teleop_twist_joy',
            executable='teleop_node',
            name='teleop_twist_joy_node',
            parameters=[joy_config],
            remappings=[('/cmd_vel', '/cmd_vel')],
            output='screen',
        ),
    ])
