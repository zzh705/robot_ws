#!/usr/bin/env python3
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import LogInfo
from launch_ros.actions import Node
from launch.substitutions import LaunchConfiguration
import glob


def generate_launch_description():
    channel_type =  LaunchConfiguration('channel_type', default='serial')
    # 端口选择: 优先 udev 稳定别名 /dev/rplidar, 再取第一个 /dev/ttyUSB*。
    # 注意 STM32 走 ttyACM*/by-id, 不要和雷达抢同一个口。
    if os.path.exists('/dev/rplidar'):
        _serial_default = '/dev/rplidar'
    else:
        _serial_candidates = sorted(glob.glob('/dev/ttyUSB*'))
        _serial_default = _serial_candidates[0] if _serial_candidates else '/dev/ttyUSB0'
    serial_port = LaunchConfiguration('serial_port', default=_serial_default)
    serial_baudrate = LaunchConfiguration('serial_baudrate', default='115200')
    frame_id = LaunchConfiguration('frame_id', default='laser')
    inverted = LaunchConfiguration('inverted', default='false')
    angle_compensate = LaunchConfiguration('angle_compensate', default='true')
    # A1 系列只支持 Standard / Express；Sensitivity、Boost 是其它型号(S2/T1 等)的模式。
    # 这个默认值原先是 'Sensitivity' 且没有真正传给节点, 所以一直没暴露;
    # 一旦传进节点就会:
    #   [ERROR] Can not start scan: 80008001!
    #   [ERROR] Failed to set scan mode   → 节点 exit 255
    # 因此默认用 A1 一定支持的 Standard; 想更高采样率改成 Express, 留空 = 节点自适应。
    scan_mode = LaunchConfiguration('scan_mode', default='Standard')
    
    return LaunchDescription([

        DeclareLaunchArgument(
            'channel_type',
            default_value=channel_type,
            description='Specifying channel type of lidar'),
        
        DeclareLaunchArgument(
            'serial_port',
            default_value=serial_port,
            description='Specifying usb port to connected lidar'),

        DeclareLaunchArgument(
            'serial_baudrate',
            default_value=serial_baudrate,
            description='Specifying usb port baudrate to connected lidar'),
        
        DeclareLaunchArgument(
            'frame_id',
            default_value=frame_id,
            description='Specifying frame_id of lidar'),

        DeclareLaunchArgument(
            'inverted',
            default_value=inverted,
            description='Specifying whether or not to invert scan data'),

        DeclareLaunchArgument(
            'angle_compensate',
            default_value=angle_compensate,
            description='Specifying whether or not to enable angle_compensate of scan data'),
        DeclareLaunchArgument(
            'scan_mode',
            default_value=scan_mode,
            description='Specifying scan mode of lidar'),


        Node(
            package='rplidar_ros',
            executable='rplidar_node',
            name='rplidar_node',
            parameters=[{'channel_type':channel_type,
                         'serial_port': serial_port,
                         'serial_baudrate': serial_baudrate,
                         'frame_id': frame_id,
                         'inverted': inverted,
                         'angle_compensate': angle_compensate,
                         # scan_mode 之前只声明没传, 节点侧参数一直是空串
                         'scan_mode': scan_mode}],
            output='screen'),
    ])