#!/usr/bin/env python3
"""robot_nav_all.launch.py — 一键拉起 GUI 派单要的完整链路。

启动顺序(从下到上):
    1) rplidar                 /scan
    2) robot_state_publisher   base_footprint → laser
    3) stm32_bridge            编码器 → /odom + TF odom→base_footprint
    4) map_server              静态 /map = maps/library.yaml (与 GUI 地图一致)
    5) static_transform        map→odom (临时定位; 真要稳就上 amcl)
    6) goal_bridge_node        9000 TCP → /goal_pose
    7) global_planner_node     A* → /global_path
    8) local_planner_node      DWA → /cmd_vel_plan
    9) pid_controller_node     PID → /cmd_vel → STM32

默认:
    enable_slam:=true         也起 slam_toolbox 做 SLAM (机器人移动时需要)
    enable_rviz:=false        板端不开 GUI, 远程调试时改 true
    enable_gamepad:=false     手柄与 DWA 互抢 /cmd_vel, 默认关闭
    map_yaml:=maps/library.yaml
    max_linear_x:=0.45
    control_period:=0.05      DWA 20Hz (比 10Hz 显著更跟手, 卡顿会减少)

用法:
    ros2 launch robot_bringup robot_nav_all.launch.py
    ros2 launch robot_bringup robot_nav_all.launch.py enable_slam:=false
    ros2 launch robot_bringup robot_nav_all.launch.py enable_gamepad:=true
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    LogInfo,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    # ----- 共享路径 -----
    rplidar_launch = os.path.join(
        get_package_share_directory('rplidar_ros'),
        'launch', 'rplidar_a1_launch.py')
    robot_description_launch = os.path.join(
        get_package_share_directory('robot_description'),
        'launch', 'display.launch.py')
    slam_launch = os.path.join(
        get_package_share_directory('slam_toolbox'),
        'launch', 'online_async_launch.py')
    stm32_bridge_launch = os.path.join(
        get_package_share_directory('stm32_bridge'),
        'launch', 'stm32_bridge.launch.py')

    # ----- 参数声明 -----
    args = [
        DeclareLaunchArgument(
            'enable_slam', default_value='false',
            description='是否启用 slam_toolbox 持续建图。默认 false: 用静态地图'
                        '(map_server + 静态 map→odom) 派单, 不需要同时建图。'
                        '置 true 会与静态 map_server / 静态 map→odom 互斥'
                        '(双发 /map 与 map→odom 会让 A* 与 DWA 全错位), '
                        '此时静态那两处会自动停用(UnlessCondition)。'),
        DeclareLaunchArgument(
            'enable_rviz', default_value='false',
            description='是否启动 RViz2 (板端默认关闭)'),
        DeclareLaunchArgument(
            'enable_gamepad', default_value='false',
            description='是否启用手柄遥控 (会与 DWA 抢 /cmd_vel)'),
        DeclareLaunchArgument(
            'enable_nav', default_value='true',
            description='是否拉起 A*/DWA/PID 三层; false 时仅给 /goal_pose 收'),
        DeclareLaunchArgument(
            'stm32_port', default_value='/dev/robot_stm32',
            description='STM32 串口设备路径'),
        DeclareLaunchArgument(
            'map_yaml',
            default_value='/home/sunrise/robot_ws/maps/library.yaml',
            description='map_server 与 goal_bridge 默认地图 (与 GUI 一致)'),
        DeclareLaunchArgument(
            'map_frame_x', default_value='0',
            description='static map→odom 平移 x'),
        DeclareLaunchArgument(
            'map_frame_y', default_value='0',
            description='static map→odom 平移 y'),
        DeclareLaunchArgument(
            'map_frame_yaw', default_value='0',
            description='static map→odom 旋转 yaw (单位: rad, '
                        'static_transform_publisher 的 --yaw 是弧度)'),
        DeclareLaunchArgument(
            'slam_config',
            default_value='/home/sunrise/robot_ws/config/mapper_params_online_async.yaml',
            description='slam_toolbox 参数文件'),
        DeclareLaunchArgument(
            'max_linear_x', default_value='0.45',
            description='DWA/PID 最大前进速度 m/s'),
        DeclareLaunchArgument(
            'max_angular_z', default_value='0.9',
            description='DWA/PID 最大角速度 rad/s'),
        DeclareLaunchArgument(
            'control_period', default_value='0.05',
            description='DWA 决策周期 s (默认 0.05 = 20Hz)'),
        DeclareLaunchArgument(
            'inflation_radius', default_value='0.28',
            description='障碍膨胀半径 m —— A* 与 DWA 共用这一个值(单一来源)。'
                        '实测车体 0.33×0.25 m → 半对角线 0.207 m 是几何下限, '
                        '0.28 = 0.207 + 7.3cm 余量。窄通道过不去时可调到 0.22~0.25, '
                        '但要同步改 global_planner_node/local_planner_node 的默认值'
                        '与 scripts/plan_check.py、library_gui/map_view.py。'),
        DeclareLaunchArgument(
            'rviz_config',
            default_value='/home/sunrise/robot_ws/config/robot.rviz',
            description='RViz2 配置'),
    ]

    # ----- 节点 -----
    nodes = []

    # 1) 雷达
    nodes.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(rplidar_launch)))

    # 2) Robot description (URDF → TF base_footprint → laser)
    nodes.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(robot_description_launch)))

    # 3) STM32 桥接
    nodes.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(stm32_bridge_launch),
        launch_arguments={'port': LaunchConfiguration('stm32_port')}.items()))

    # 4) 静态地图
    nodes.append(Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[{
            'yaml_filename': LaunchConfiguration('map_yaml'),
            'use_sim_time': False,
        }],
        # SLAM 在线时由 slam_toolbox 提供 /map; 同时存在会冲突
        condition=UnlessCondition(LaunchConfiguration('enable_slam')),
    ))

    # 4b) lifecycle: 让 map_server 转 active, 否则 /map 不会发
    nodes.append(Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_map',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'autostart': True,
            'node_names': ['map_server'],
        }],
        condition=UnlessCondition(LaunchConfiguration('enable_slam')),
    ))

    # 5) 静态 TF: map → odom
    nodes.append(Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='map_to_odom_static',
        arguments=[
            '--x', LaunchConfiguration('map_frame_x'),
            '--y', LaunchConfiguration('map_frame_y'),
            '--z', '0',
            '--roll', '0', '--pitch', '0',
            '--yaw', LaunchConfiguration('map_frame_yaw'),
            '--frame-id', 'map', '--child-frame-id', 'odom',
        ],
        # SLAM 在线时由 slam_toolbox 的 odom→map 提供; 否则用静态常量.
        condition=UnlessCondition(LaunchConfiguration('enable_slam')),
    ))

    # 6) goal_bridge: TCP 9000 → /goal_pose
    #    map_yaml_path 与 map_server 用同一份, 范围校验才一致
    nodes.append(Node(
        package='library_nav',
        executable='goal_bridge_node',
        name='goal_bridge',
        output='screen',
        parameters=[{
            'tcp_host': '127.0.0.1',
            'tcp_port': 9000,
            'map_yaml_path': LaunchConfiguration('map_yaml'),
            'loc_A_x': 1.0,  'loc_A_y': 1.0,
            'loc_B_x': 1.0,  'loc_B_y': 2.5,
            'loc_C_x': 3.0,  'loc_C_y': 2.5,
            'loc_D_x': 3.0,  'loc_D_y': 1.0,
        }],
    ))

    # 7~9) 导航三层 (enable_nav=false 时不拉起)
    nav_block = [
        # A* 全局规划
        Node(
            package='library_nav',
            executable='global_planner_node',
            name='global_planner',
            output='screen',
            parameters=[{
                'inflation_radius': LaunchConfiguration('inflation_radius'),
                # ROS OccupancyGrid 0-100 (由 /map 传来, 已 negate+threshold 转换).
                # 50 = nav2 默认; > 50 当障碍, <=50 当可走.
                # 旧值 60 是错误的: 代码里会拿 raw PGM 0-254 灰度比 60, 导致整间房 96.6% 像素被判障碍.
                'occupancy_threshold': 50,
                # 软更新: 把 /scan 最近 N 秒的命中点叠到 costmap
                'enable_scan_layer': True,
                'scan_layer_decay_s': 1.0,
                'scan_inflate_radius': 0.18,
            }],
            condition=IfCondition(LaunchConfiguration('enable_nav')),
        ),

        # DWA 局部规划
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
                'control_period': LaunchConfiguration('control_period'),
                'inflate_radius': LaunchConfiguration('inflation_radius'),
                'goal_tolerance': 0.15,
                'w_heading': 0.35,
                'w_dist': 0.30,
                'w_vel': 0.25,
                'w_path': 0.10,
                'w_prog': 0.40,
            }],
            condition=IfCondition(LaunchConfiguration('enable_nav')),
        ),

        # PID 速度跟踪
        Node(
            package='library_nav',
            executable='pid_controller_node',
            name='pid_controller',
            output='screen',
            parameters=[{
                'max_linear_x': LaunchConfiguration('max_linear_x'),
                'max_angular_z': LaunchConfiguration('max_angular_z'),
                'kp_x': 2.0, 'ki_x': 0.0, 'kd_x': 0.05,
                'kp_y': 2.0, 'ki_y': 0.0, 'kd_y': 0.05,
                'kp_z': 1.8, 'ki_z': 0.0, 'kd_z': 0.05,
                'slew_v': 0.08,    # 20Hz 周期, 0.08/0.05 = 1.6 m/s²
                'slew_w': 0.15,    # 20Hz 周期, 0.15/0.05 = 3.0 rad/s²
                'control_period': LaunchConfiguration('control_period'),
            }],
            condition=IfCondition(LaunchConfiguration('enable_nav')),
        ),
    ]
    nodes.extend(nav_block)

    # 8) SLAM toolbox (可关: 用静态地图时关掉)
    nodes.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(slam_launch),
        launch_arguments={'slam_params_file': LaunchConfiguration('slam_config')}.items(),
        condition=IfCondition(LaunchConfiguration('enable_slam'))))

    # 9) 手柄遥控 (默认关, 避免与 DWA 抢底盘)
    nodes.append(ExecuteProcess(
        cmd=['python3', '-u', '/home/sunrise/robot_ws/scripts/gamepad_cmd_vel.py'],
        output='screen',
        condition=IfCondition(LaunchConfiguration('enable_gamepad'))))

    # 10) RViz (默认关)
    nodes.append(Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', LaunchConfiguration('rviz_config')],
        output='screen',
        condition=IfCondition(LaunchConfiguration('enable_rviz')),
        additional_env={
            'DISPLAY': ':0.0',
            'XAUTHORITY': '/home/sunrise/.Xauthority',
        }))

    nodes.append(LogInfo(msg='robot_nav_all: 全节点已下发 (enable_nav=%s)' %
                         LaunchConfiguration('enable_nav')))

    return LaunchDescription(args + nodes)


if __name__ == '__main__':
    pass