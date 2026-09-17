#!/bin/bash
# lidar_watchdog.sh — RPLIDAR USB 断流自动恢复
# 检测 /scan 话题是否还在发布；卡死/掉线则重启核心链路和 rviz。
LOG=/home/sunrise/robot_ws/logs/watchdog.log
mkdir -p /home/sunrise/robot_ws/logs
export DISPLAY=:0.0
export XAUTHORITY=/home/sunrise/.Xauthority

oomph_log() {
    echo "$(date '+%F %T') $1" >> "$LOG"
}

restart_everything() {
    oomph_log "=== RESTART CORE + RVIZ ==="
    pkill -9 -f robot.launch.py 2>/dev/null
    pkill -9 -f robot_core.launch.py 2>/dev/null
    pkill -9 -f rplidar_node 2>/dev/null
    pkill -9 -f async_slam_toolbox_node 2>/dev/null
    pkill -9 -f robot_state_publisher 2>/dev/null
    pkill -9 -f static_transform_publisher 2>/dev/null
    sleep 3
    nohup bash -c 'source /opt/ros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; ros2 launch robot_bringup robot_core.launch.py' > /home/sunrise/robot_ws/logs/core.log 2>&1 &
    sleep 12
    pgrep -x rviz2 > /dev/null || {
        nohup bash -c 'source /opt/ros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; export DISPLAY=:0.0; export XAUTHORITY=/home/sunrise/.Xauthority; ros2 run rviz2 rviz2 -d /home/sunrise/robot_ws/config/robot.rviz' > /home/sunrise/robot_ws/logs/rviz.log 2>&1 &
    }
    oomph_log "=== RESTART DONE ==="
}

while true; do
    RES=$(timeout 6 ros2 topic hz /scan 2>/dev/null | head -1)
    if echo "$RES" | grep -q "average rate"; then
        :
    else
        oomph_log "/scan silent -> restart_all"
        restart_everything
    fi
    sleep 15
done