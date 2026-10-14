#!/usr/bin/env bash
# stop_all.sh — 停掉所有机器人进程（避免 pkill -f 匹配到调用者自身命令行）
PATTERNS=(
  "robot_bringup robot.launch"
  "robot_nav_all.launch"
  "slam_toolbox"
  "stm32_bridge_node"
  "rplidar"
  "gamepad_cmd_vel"
  "GUI.py"
  "rosbag2_recorder"
  "robot_state_publisher"
  "map_server"
  "lifecycle_manager"
  "global_planner_node"
  "local_planner_node"
  "pid_controller_node"
  "static_transform_publisher"
  "goal_bridge_node"
  "record_path.py"
  "replay_path.py"
  "rviz2"
  "map_saver_cli"
)

SELF=$$
for p in "${PATTERNS[@]}"; do
  for pid in $(pgrep -f "$p" 2>/dev/null); do
    [ "$pid" = "$SELF" ] && continue
    [ "$pid" = "$PPID" ] && continue
    kill -9 "$pid" 2>/dev/null && echo "killed $pid  ($p)"
  done
done
sleep 2
echo "--- 剩余 ---"
LEFT=0
for p in "${PATTERNS[@]}"; do
  for pid in $(pgrep -f "$p" 2>/dev/null); do
    [ "$pid" = "$SELF" ] && continue
    echo "  STILL $pid $p"
    LEFT=1
  done
done
[ "$LEFT" = "0" ] && echo "  (无)"