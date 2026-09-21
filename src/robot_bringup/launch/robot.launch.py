#!/usr/bin/env python3
"""
robot.launch.py — 总启动：核心 SLAM + RVIZ2 + 雷达看护 + STM32 编码器桥 + 手柄遥控(可选)。
按以下方式启动即可一次拉起全链路：
    ros2 launch robot_bringup robot.launch.py

指定 STM32 串口：
    ros2 launch robot_bringup robot.launch.py stm32_port:=/dev/robot_stm32

启用手柄遥控 (默认开启，走 scripts/gamepad_cmd_vel.py，只发布 /cmd_vel)：
    ros2 launch robot_bringup robot.launch.py enable_gamepad:=true

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

    # =========================
    # 5. 手柄遥控 (可选)
    #    统一走 scripts/gamepad_cmd_vel.py：只发 /cmd_vel，不碰 STM32 串口。
    #    STM32 串口必须由 stm32_bridge 独占（它要用编码器帧积分 /odom），
    #    第二个进程抢同一个 tty 会让 /odom 跳变、建图扇区重叠。
    # =========================
    gamepad_script = '/home/sunrise/robot_ws/scripts/gamepad_cmd_vel.py'

    slam_config = LaunchConfiguration('slam_config')
    rviz_config = LaunchConfiguration('rviz_config')
    watchdog_script = LaunchConfiguration('watchdog_script')

    # =========================
    # STM32 串口设备路径参数
    # =========================
    stm32_port_arg = DeclareLaunchArgument(
        'stm32_port',
        default_value='/dev/robot_stm32',
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

    # =========================
    # 手柄遥控开关（默认开启）
    # =========================
    enable_gamepad_arg = DeclareLaunchArgument(
        'enable_gamepad',
        default_value='true',
        description='是否启用手柄遥控 (需要连接手柄设备)'
    )

    slam_config_arg = DeclareLaunchArgument(
        'slam_config',
        default_value='/home/sunrise/robot_ws/config/mapper_params_online_async.yaml',
        description='SLAM 参数文件路径'
    )
    rviz_config_arg = DeclareLaunchArgument(
        'rviz_config',
        default_value='/home/sunrise/robot_ws/config/robot.rviz',
        description='RViz 配置文件路径'
    )
    watchdog_script_arg = DeclareLaunchArgument(
        'watchdog_script',
        default_value='/home/sunrise/robot_ws/scripts/lidar_watchdog.sh',
        description='雷达看护脚本路径'
    )

    return LaunchDescription([
        stm32_port_arg,
        enable_watchdog_arg,
        enable_gamepad_arg,
        slam_config_arg,
        rviz_config_arg,
        watchdog_script_arg,

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
        # 手柄遥控 (可选) — 唯一 /cmd_vel 发布者
        # =========================
        ExecuteProcess(
            cmd=['python3', '-u', gamepad_script],
            output='screen',
            condition=IfCondition(LaunchConfiguration('enable_gamepad'))
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
            # 板端是软件渲染(llvmpipe)，rviz 是最大 CPU 消耗源：
            # 降优先级 + 限制在 4-7 核，把 0-3 核留给 SLAM/里程计/手柄链路。
            prefix='nice -n 5 taskset -c 4-7',
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
