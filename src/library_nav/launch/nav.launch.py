#!/usr/bin/env python3
"""自主导航总启动:
    ros2 launch library_nav nav.launch.py

三层导航: ① A* 全局规划  ② DWA 局部规划  ③ PID 速度闭环
+ 上位机桥接: ④ goal_bridge(TCP 9000 → /goal_pose)
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    # =====================
    # 可调参数
    # =====================
    max_linear_x_arg = DeclareLaunchArgument(
        'max_linear_x',
        default_value='0.4',
        description='最大前进速度 m/s')
    max_angular_z_arg = DeclareLaunchArgument(
        'max_angular_z',
        default_value='0.5',
        description='最大角速度 rad/s')

    return LaunchDescription([

        max_linear_x_arg,
        max_angular_z_arg,

        # =====================
        # ① A* 全局规划
        # =====================
        Node(
            package='library_nav',
            executable='global_planner_node',
            name='global_planner',
            output='screen',
            parameters=[{
                'inflation_radius': 0.28,
                'occupancy_threshold': 60,
            }],
        ),

        # =====================
        # ② DWA 局部规划
        # =====================
        Node(
            package='library_nav',
            executable='local_planner_node',
            name='local_planner_dwa',
            output='screen',
            parameters=[{
                'max_vx': LaunchConfiguration('max_linear_x'),
                'max_wz': LaunchConfiguration('max_angular_z'),
            }],
        ),

        # =====================
        # ③ PID 速度闭环
        # =====================
        Node(
            package='library_nav',
            executable='pid_controller_node',
            name='pid_controller',
            output='screen',
            parameters=[{
                'max_linear_x': LaunchConfiguration('max_linear_x'),
                'max_angular_z': LaunchConfiguration('max_angular_z'),
            }],
        ),

        # =====================
        # ④ 上位机找书桥接: TCP 9000 → /goal_pose
        # =====================
        Node(
            package='library_nav',
            executable='goal_bridge_node',
            name='goal_bridge',
            output='screen',
            parameters=[{
                'tcp_host': '127.0.0.1',
                'tcp_port': 9000,
                # ---------- 书区 → 地图坐标映射 ----------
                # 真机标定后修改此处, frame=map
                'loc_A_x': 1.0,  'loc_A_y': 1.0,
                'loc_B_x': 1.0,  'loc_B_y': 2.5,
                'loc_C_x': 3.0,  'loc_C_y': 2.5,
                'loc_D_x': 3.0,  'loc_D_y': 1.0,
            }],
        ),
    ])