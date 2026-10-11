#!/bin/bash
# restart_stack.sh — 干净重启整栈：rplidar + robot_state_publisher + slam_toolbox +
# stm32_bridge + 手柄节点 + rviz2 + 雷达看护。
#
# 用途：建图前想要一张全新地图（slam_toolbox 重启 = 地图清零），或进程状态乱了需要重置。
# 用法：bash /home/sunrise/robot_ws/scripts/restart_stack.sh
#      然后 tail -f /home/sunrise/robot_ws/logs/core.log 看进度（约 20~40s 就绪）
set -u

WS=/home/sunrise/robot_ws
LOG=$WS/logs/core.log
mkdir -p "$WS/logs"

echo "[restart_stack] 停止旧进程 ..."
pkill -f 'lidar_watchdog.sh' 2>/dev/null
pkill -f 'robot.launch.py' 2>/dev/null
pkill -f 'robot_core.launch.py' 2>/dev/null
pkill -f 'rplidar_node' 2>/dev/null
pkill -f 'async_slam_toolbox_node' 2>/dev/null
pkill -f 'stm32_bridge_node' 2>/dev/null
pkill -f 'robot_state_publisher' 2>/dev/null
pkill -f 'gamepad_cmd_vel.py' 2>/dev/null
pkill -x rviz2 2>/dev/null
sleep 4

echo "[restart_stack] 等待串口释放 ..."
for i in 1 2 3 4 5; do
    if ! fuser /dev/ttyACM0 /dev/ttyUSB0 >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

echo "[restart_stack] 启动整栈 ..."
export DISPLAY=:0.0
export XAUTHORITY=/home/sunrise/.Xauthority
export ROS_DOMAIN_ID=0
nohup bash -c "source /opt/ros/humble/setup.bash; source $WS/install/setup.bash; exec ros2 launch robot_bringup robot.launch.py enable_watchdog:=true" >> "$LOG" 2>&1 &
echo "[restart_stack] 已下发（日志：$LOG）"