#!/usr/bin/env python3
"""static_map_nav.launch.py
纯静态地图导航:
   map_server 发布 /map (= library.pgm)
   static_transform_publisher 写 map → odom (假设车在原点附近, 不真定位)
   robot_state_publisher 维护 odom → base_footprint → laser
   stm32_bridge 读底盘编码器发 /odom
   不依赖 slam_toolbox / amcl, 适合车在固定位置的展厅/测试

注意:
   * 这是为了消除"GUI 地图"与"机器人规划地图"不一致导致派单位置不准的根因
   * 车真要跑起来时, 仍是 odom 提供定位 (里程计会随时间漂移, 但短期 demo 没问题)
   * 想长期稳, 加 amcl (本镜像未装) 或者切回 slam_toolbox 并修 map_start_pose
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([

        # 1) 静态地图: /map = library.pgm 完全一致
        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            output='screen',
            parameters=[{
                'yaml_filename': '/home/sunrise/robot_ws/maps/library.yaml',
                'use_sim_time': False,
            }],
        ),

        # 1b) lifecycle manager: nav2_map_server 是生命周期节点。
        #     没有它, map_server 会停在 unconfigured, /map 永远不会发布
        #     (新版 robot_nav_all.launch.py 里已有同样一段)。
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_map',
            output='screen',
            parameters=[{
                'use_sim_time': False,
                'autostart': True,
                'node_names': ['map_server'],
            }],
        ),

        # 2) 静态 TF: map → odom (假设车当前在地图原点附近, x=0 y=0 朝向 0)
        # 真实情况下应该由 amcl / slam_toolbox 提供; 这里临时给一个常量值
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='map_to_odom_static',
            arguments=[
                '--x', '0', '--y', '0', '--z', '0',
                '--roll', '0', '--pitch', '0', '--yaw', '0',
                '--frame-id', 'map', '--child-frame-id', 'odom',
            ],
        ),

        # 3) 机器人本体 URDF → odom→base_footprint→laser
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{
                'use_sim_time': False,
            }],
        ),

        # 4) STM32 串口桥: 发 /odom + 收 /cmd_vel
        Node(
            package='stm32_bridge',
            executable='stm32_bridge_node',
            name='stm32_bridge',
            output='screen',
            parameters=[{
                    'port': '/dev/robot_stm32',
                    'baud': 115200,
                }],
        ),

        # 5) 雷达
        Node(
            package='rplidar_ros',
            executable='rplidar_node',
            name='rplidar_node',
            output='screen',
            parameters=[{
                'serial_port': '/dev/ttyUSB0',
                'serial_baudrate': 115200,
                'frame_id': 'laser',
                'angle_compensate': True,
            }],
        ),
    ])