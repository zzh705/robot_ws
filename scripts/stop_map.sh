#!/bin/bash
# stop_map.sh — 干净停止 SLAM 建图栈（launch 及其子节点）
export HOME=/home/sunrise
pkill -f "robot.launch.py" 2>/dev/null
pkill -f "robot_core.launch.py" 2>/dev/null
sleep 1
for n in lidar_watchdog.sh rplidar_node async_slam_toolbox_node robot_state_publisher static_transform_publisher stm32_bridge_node rviz2; do
  pkill -f "$n" 2>/dev/null
done
sleep 1
echo "建图栈已停止。剩余相关进程:"
pgrep -af 'robot.launch|rplidar_node|slam_toolbox|stm32_bridge_node|rviz2' || echo "(无)"
