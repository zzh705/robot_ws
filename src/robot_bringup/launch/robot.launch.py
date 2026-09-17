#!/usr/bin/env python3
"""
robot.launch.py — 总启动：核心 SLAM + RVIZ2（root 用户 + 正确显示环境）+ 雷达看护 + STM32 编码器桥。
按以下方式启动即可一次拉起全链路：
    ros2 launch robot_bringup robot.launch.py

指定 STM32 串口：
    ros2 launch robot_bringup robot.launch.py stm32_port:=/dev/ttyACM0

关闭雷达看护（联调测试时用，避免看护在中途重启链路干扰测试）：
    ros2 launch robot_bringup robot.launch.py enable_watchdog:=false
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, ExecuteProcess, DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    # =========================
    # 1. RPLIDAR
    # =========================
    rplidar_launch = os.path.join(
        get_package_share_directory('rplidar_ros'),
        'launch',
        'rplidar_a1_launch.py'
    )

    # =========================
    # 2. Robot Description
    # =========================
    robot_description_launch = os.path.join(
        get_package_share_directory('robot_description'),
        'launch',
        'display.launch.py'
    )

    # =========================
    # 3. SLAM Toolbox
    # =========================
    slam_launch = os.path.join(
        get_package_share_directory('slam_toolbox'),
        'launch',
        'online_async_launch.py'
    )

    # =========================
    # 4. STM32 桥接（编码器里程计）
    # =========================
    stm32_bridge_launch = os.path.join(
        get_package_share_directory('stm32_bridge'),
        'launch',
        'stm32_bridge.launch.py'
    )

    slam_config = '/home/sunrise/robot_ws/config/mapper_params_online_async.yaml'
    rviz_config = '/home/sunrise/robot_ws/config/robot.rviz'
    watchdog_script = '/home/sunrise/robot_ws/scripts/lidar_watchdog.sh'

    # =========================
    # STM32 串口设备路径参数
    # =========================
    stm32_port_arg = DeclareLaunchArgument(
        'stm32_port',
        default_value='/dev/ttyACM0',
        description='STM32 串口设备路径'
    )

    # =========================
    # 雷达看护开关（联调测试时关闭）
    # =========================
    enable_watchdog_arg = DeclareLaunchArgument(
        'enable_watchdog',
        default_value='true',
        description='是否启用雷达 USB 看护（测试时设为 false）'
    )

    return LaunchDescription([

        stm32_port_arg,
        enable_watchdog_arg,

        # =========================
        # 核心：RPLIDAR
        # =========================
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(rplidar_launch)
        ),

        # =========================
        # 核心：Robot Description
        # base_footprint → base_link → laser
        # =========================
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(robot_description_launch)
        ),

        # =========================
        # 临时 TF：odom → base_footprint
        # （STM32 真实数据验证通过后删除此项）
        # =========================
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

        # =========================
        # 核心：SLAM Toolbox
        # =========================
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(slam_launch),
            launch_arguments={
                'slam_params_file': slam_config
            }.items()
        ),

        # =========================
        # STM32 编码器里程计桥接
        # =========================
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(stm32_bridge_launch),
            launch_arguments={
                'port': LaunchConfiguration('stm32_port')
            }.items()
        ),

        # =========================
        # RViz2 — root 运行，连接实体屏
        # =========================
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            arguments=['-d', rviz_config],
            output='screen',
            additional_env={
                'DISPLAY': ':0.0',
                'XAUTHORITY': '/home/sunrise/.Xauthority'
            }
        ),

        # =========================
        # 雷达 USB 看护（断流自动拉起），可用参数关闭
        # =========================
        ExecuteProcess(
            cmd=['bash', watchdog_script],
            output='screen',
            condition=IfCondition(LaunchConfiguration('enable_watchdog'))
        )

    ])