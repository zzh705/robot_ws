#!/usr/bin/env python3
"""自主导航总启动(Moss 调优版):
    ros2 launch library_nav nav.launch.py

三层导航: ① A* 全局规划  ② DWA 局部规划  ③ PID 速度闭环
+ 上位机桥接: ④ goal_bridge(TCP 9000 → /goal_pose)
+ /scan 软更新层: 1 步在 global_planner 节点里做完

关键参数(2026-09-23 Moss 调优):
    20Hz 决策(DWA), 显著减少"卡顿"
    max_vx 0.45, max_wz 0.9
    acc_x 1.5, acc_w 3.0      (允许更快的反应)
    inflate_radius 0.30       (与 global_planner 严格一致)
    PID kp=2.0 kd=0.05         (加入少量阻尼, 减少抖动)
    slew_v 0.08 slew_w 0.15    (软启动 20Hz 周期, 与 DWA 加速匹配)
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    max_linear_x_arg = DeclareLaunchArgument(
        'max_linear_x',
        default_value='0.45',
        description='最大前进速度 m/s')
    max_angular_z_arg = DeclareLaunchArgument(
        'max_angular_z',
        default_value='0.9',
        description='最大角速度 rad/s')
    map_yaml_arg = DeclareLaunchArgument(
        'map_yaml',
        default_value='/home/sunrise/robot_ws/maps/library.yaml',
        description='地图 yaml(默认 library.yaml, 与 GUI 一致)')

    return LaunchDescription([

        max_linear_x_arg,
        max_angular_z_arg,
        map_yaml_arg,

        # ① A* 全局规划 (含 /scan 软更新层 + 目标吸附)
        Node(
            package='library_nav',
            executable='global_planner_node',
            name='global_planner',
            output='screen',
            parameters=[{
                'inflation_radius': 0.30,
                # ROS OccupancyGrid 0-100 (由 /map 传来, 已 negate+threshold).
                # 50 = nav2 默认; > 50 当障碍, <=50 当可走. PGM 原始灰度不能这么比.
                'occupancy_threshold': 50,
                'enable_snap': True,
                'snap_radius': 1.0,
                # /scan 软更新
                'enable_scan_layer': True,
                'scan_layer_decay_s': 1.0,
                'scan_inflate_radius': 0.18,
                'scan_min_range': 0.20,
                'scan_max_range': 8.0,
            }],
        ),

        # ② DWA 局部规划
        Node(
            package='library_nav',
            executable='local_planner_node',
            name='local_planner_dwa',
            output='screen',
            parameters=[{
                'max_vx': LaunchConfiguration('max_linear_x'),
                'min_vx': 0.0,
                'max_wz': LaunchConfiguration('max_angular_z'),
                'acc_x': 1.5,
                'acc_w': 3.0,
                'control_period': 0.05,
                'predict_time': 2.0,
                'sim_dt': 0.1,
                'sample_v': 9,
                'sample_w': 11,
                'inflate_radius': 0.30,
                'goal_tolerance': 0.15,
                'lookahead': 0.4,
                'robot_radius': 0.30,
                'w_heading': 0.35,
                'w_dist': 0.30,
                'w_vel': 0.25,
                'w_path': 0.10,
                'w_prog': 0.40,
            }],
        ),

        # ③ PID 速度闭环
        Node(
            package='library_nav',
            executable='pid_controller_node',
            name='pid_controller',
            output='screen',
            parameters=[{
                'max_linear_x': LaunchConfiguration('max_linear_x'),
                'max_linear_y': 0.25,
                'max_angular_z': LaunchConfiguration('max_angular_z'),
                # 加入少量阻尼消除一冲一冲的"卡顿感"
                'kp_x': 2.0, 'ki_x': 0.0, 'kd_x': 0.05,
                'kp_y': 2.0, 'ki_y': 0.0, 'kd_y': 0.05,
                'kp_z': 1.8, 'ki_z': 0.0, 'kd_z': 0.05,
                # 软启动: 20Hz 周期下, 0.08/0.05 = 1.6 m/s²
                'slew_v': 0.08,
                'slew_w': 0.15,
                'control_period': 0.05,
            }],
        ),

        # ④ 上位机找书桥接: TCP 9000 → /goal_pose
        Node(
            package='library_nav',
            executable='goal_bridge_node',
            name='goal_bridge',
            output='screen',
            parameters=[{
                'tcp_host': '127.0.0.1',
                'tcp_port': 9000,
                'map_yaml_path': LaunchConfiguration('map_yaml'),
                'reject_out_of_map': True,
                'edge_warn_m': 0.5,
                # 书区 → 地图坐标(真机标定后改这里)
                'loc_A_x': 1.0,  'loc_A_y': 1.0,
                'loc_B_x': 1.0,  'loc_B_y': 2.5,
                'loc_C_x': 3.0,  'loc_C_y': 2.5,
                'loc_D_x': 3.0,  'loc_D_y': 1.0,
            }],
        ),
    ])