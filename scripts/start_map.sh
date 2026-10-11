#!/bin/bash
# ============================================================
# start_map.sh — 一键启动 SLAM 建图栈 + 键盘遥控提示
#
# 用法:
#   sudo bash start_map.sh
#
# 启动后:
#   1) 激光 /scan + slam_toolbox(mapping) + STM32 odom + rviz
#   2) 地面遥控该列表用系统键盘遥控
#
# 遥控(另开终端):
#   export ROS_DOMAIN_ID=0
#   source /opt/ros/humble/setup.bash
#   source /home/sunrise/robot_ws/install/setup.bash
#   ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -p repeat_rate:=10.0 -p default_linear.x_speed:=0.2
#
# 保存地图:
#   bash $(dirname $0)/save_map.sh
# ============================================================

export HOME=/home/sunrise
export ROS_DOMAIN_ID=0
source /opt/ros/humble/setup.bash
source /home/sunrise/robot_ws/install/setup.bash
cd /home/sunrise/robot_ws

# 只允许一个建图进程
pkill -f "robot.launch.py" 2>/dev/null
sleep 2

echo "=== 启动 SLAM 建图栈 (看护已开) ==="
nohup bash -c '
  export HOME=/home/sunrise
  export ROS_DOMAIN_ID=0
  source /opt/ros/humble/setup.bash
  source /home/sunrise/robot_ws/install/setup.bash
  ros2 launch robot_bringup robot.launch.py enable_watchdog:=true
' > /tmp/map_build.log 2>&1 &
echo "启动 PID: $!"

echo "等待 15s 让 SLAM/odom 就绪..."
sleep 15

echo "=== 状态检查 ==="
timeout 8 ros2 node list 2>&1

echo ""
echo "======================================================"
echo " 建图已开始! 在另一个终端这样遥控小车:"
echo ""
echo "  export ROS_DOMAIN_ID=0"
echo "  export HOME=/home/sunrise"
echo "  source /opt/ros/humble/setup.bash"
echo "  source /home/sunrise/robot_ws/install/setup.bash"
echo "  ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -p default_linear.x_speed:=0.2"
echo ""
echo " 按键: i=前进 k=停 j=左转 l=右转 u/o=左前/右前" 
echo " 看到 rviz 地图逐渐成型后, 执行: bash $(dirname $0)/save_map.sh"
echo "======================================================"