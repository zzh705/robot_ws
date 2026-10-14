#!/bin/bash
# ============================================================
# cruise_stop.sh — 巡航收尾(顺序很重要)
#
# 1) 先下发零速到 /cmd_vel_plan: pid_controller 会把零速中转给底盘,
#    STM32 收到的是 0, 不会"记住"上一个非零指令。
# 2) 再停规划器。
#
# ⚠️ pkill 用 [x]xxx 写法: 直接写 pkill -f local_planner_node 会匹配到
#    **本脚本自己的命令行** → 脚本自杀, 后面零速那步根本不执行
#    (2026-10-11 实测踩到: 只停了 DWA, pid 还在重发 wz=0.75)。
# ============================================================
export HOME=/home/sunrise
export ROS_DOMAIN_ID=0
source /opt/tros/humble/setup.bash
source /home/sunrise/robot_ws/install/setup.bash

echo "[cruise_stop] 1/2 下发零速 4s ..."
timeout 4 ros2 topic pub -r 10 /cmd_vel_plan geometry_msgs/msg/Twist \
  "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" \
  >/dev/null 2>&1
sleep 1

echo "[cruise_stop] 2/2 停规划器 ..."
pkill -f "[l]ocal_planner_node"
pkill -f "[g]lobal_planner_node"
pkill -f "[p]id_controller_node"
sleep 1

echo "[cruise_stop] 剩余相关进程:"
pgrep -af "[l]ocal_planner_node|[g]lobal_planner_node|[p]id_controller_node" \
  || echo "(规划器/pid 已全部停止)"
