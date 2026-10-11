#!/bin/bash
# nav_up.sh — 一键拉起"GUI 地图按钮派单"需要的完整导航栈
#
# 用法:
#   bash scripts/nav_up.sh           # 默认: 静态地图 + A*/DWA/PID + 软更新
#   bash scripts/nav_up.sh slam      # 改用 SLAM 建图 (与静态地图互斥)
#   bash scripts/nav_up.sh nav_off   # 关闭 A*/DWA/PID, 只留雷达+STM32 (远程遥控用)
#
# 输出: 写日志到 logs/nav.log; PID 写到 /tmp/nav_stack.pid
# 排错: tail -f /home/sunrise/robot_ws/logs/nav.log
set -u

WS=/home/sunrise/robot_ws
LOG=$WS/logs/nav.log
PIDF=/tmp/nav_stack.pid
mkdir -p "$WS/logs"

MODE=${1:-static}
case "$MODE" in
  slam)   SLAM_ARG=enable_slam:=true ;;
  nav_off) SLAM_ARG=enable_slam:=false ;;
  *)      SLAM_ARG=enable_slam:=false ;;
esac

echo "[nav_up] MODE=$MODE  SLAM_ARG=$SLAM_ARG"

# 1) 关掉旧栈(不碰 slam_watchdog / lidar_watchdog)
pkill -f 'robot_nav_all.launch.py' 2>/dev/null
pkill -f 'robot_core.launch.py'    2>/dev/null
pkill -f 'global_planner_node'     2>/dev/null
pkill -f 'local_planner_node'      2>/dev/null
pkill -f 'pid_controller_node'     2>/dev/null
pkill -f 'goal_bridge_node'        2>/dev/null
pkill -f 'rplidar_node'            2>/dev/null
pkill -f 'map_server'              2>/dev/null
pkill -f 'async_slam_toolbox_node' 2>/dev/null
sleep 1

# 2) 等串口/USB 释放(否则重连会卡)
for i in 1 2 3 4 5; do
  if ! fuser /dev/ttyACM0 /dev/ttyUSB0 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if [ "$MODE" = "nav_off" ]; then
  echo "[nav_up] nav_off: 只起雷达 + STM32, 跳过导航栈"
  nohup bash -c "
    export HOME=/home/sunrise
    export ROS_DOMAIN_ID=0
    source /opt/ros/humble/setup.bash
    source $WS/install/setup.bash
    ros2 launch robot_bringup robot_nav_all.launch.py \
        enable_slam:=false enable_nav:=false enable_gamepad:=true \
        enable_rviz:=false
  " >> "$LOG" 2>&1 &
  echo $! > "$PIDF"
  echo "[nav_up] PID=$! LOG=$LOG (无 nav)"
  exit 0
fi

# 3) 拉全栈
export HOME=/home/sunrise
export ROS_DOMAIN_ID=0
nohup bash -c "
  source /opt/ros/humble/setup.bash
  source $WS/install/setup.bash
  exec ros2 launch robot_bringup robot_nav_all.launch.py \
      $SLAM_ARG enable_nav:=true enable_gamepad:=false enable_rviz:=false
" >> "$LOG" 2>&1 &

echo $! > "$PIDF"
echo "[nav_up] PID=$! LOG=$LOG"
echo "[nav_up] 等待 8s 自检..."
sleep 8
echo
echo "===== ros2 node list ====="
timeout 6 ros2 node list 2>&1 || true
echo
echo "===== ros2 topic list (含 /cmd_vel /cmd_vel_plan /map /scan) ====="
timeout 6 ros2 topic list 2>&1 | grep -E 'cmd_vel|/map|/scan|goal_pose|global_path|odom' || true
echo
echo "===== 关键链路 =====
  /goal_pose  -> 由 goal_bridge(TCP 9000) 发
  /cmd_vel_plan -> 由 DWA 发, 频率应为 ~20Hz
  /cmd_vel   -> 由 PID 发, 频率与 DWA 一致
  /scan      -> 雷达
  /map       -> 静态(本模式)或 slam_toolbox(SLAM 模式)
  /costmap_scan_marks -> A* 节点发的"雷达实时障碍层", 可在 RViz 上加 Marker 看
  完整日志: tail -F $LOG"