#!/bin/bash
# lidar_watchdog.sh — RPLIDAR USB 断流自动恢复
# 检测 /scan 话题是否还在发布；卡死/掉线则重启核心链路和 rviz。
LOG=/home/sunrise/robot_ws/logs/watchdog.log
mkdir -p /home/sunrise/robot_ws/logs
export DISPLAY=:0.0
export XAUTHORITY=/home/sunrise/.Xauthority
FAIL_COUNT=0          # 连续失败(重启后仍无 /scan)计数
LAST_FAIL_TIME=0

oomph_log() {
    echo "$(date '+%F %T') $1" >> "$LOG"
}

scan_alive() {
    # 用 --window 限制采样时间, 避免 6s 阻塞拉长检测周期
    timeout 8 ros2 topic hz /scan --window 20 2>/dev/null | grep -q "average rate"
}

restart_everything() {
    OOM="$(date '+%F %T')"
    # 诊断: ROS 环境? rplidar 进程还在?
    RD="$(pgrep -x rplidar_node >/dev/null && echo 'rplidar_running' || echo 'rplidar_dead')"
    ST="$(pgrep -f stm32_bridge_node >/dev/null && echo 'bridge_running' || echo 'bridge_dead')"
    NO="$(timeout 5 ros2 node list 2>/dev/null | grep -c local_planner_dwa || true)"
    oomph_log "=== RESTART CORE + RVIZ [$OOM] [$RD] [$ST] [nav_node=$NO] ==="

    pkill -9 -f robot.launch.py 2>/dev/null
    pkill -9 -f robot_core.launch.py 2>/dev/null
    pkill -9 -f rplidar_node 2>/dev/null
    pkill -9 -f async_slam_toolbox_node 2>/dev/null
    pkill -9 -f robot_state_publisher 2>/dev/null
    pkill -9 -f static_transform_publisher 2>/dev/null
    pkill -9 -f stm32_bridge_node 2>/dev/null
    sleep 3

    nohup bash -c 'source /opt/ros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; ros2 launch robot_bringup robot_core.launch.py' > /home/sunrise/robot_ws/logs/core.log 2>&1 &
    sleep 12
    pgrep -x rviz2 > /dev/null || {
        nohup bash -c 'source /opt/ros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; export DISPLAY=:0.0; export XAUTHORITY=/home/sunrise/.Xauthority; ros2 run rviz2 rviz2 -d /home/sunrise/robot_ws/config/robot.rviz' > /home/sunrise/robot_ws/logs/rviz.log 2>&1 &
    }

    # 重启后验证 /scan 是否恢复  (最多试 2 个窗口, 每个 ~10s)
    RECOVERED=no
    for i in 1 2; do
        if scan_alive; then RECOVERED=yes; break; fi
        sleep 8
    done
    if [ "$RECOVERED" = yes ]; then
        FAIL_COUNT=0
        oomph_log "=== RESTART DONE, /scan recovered ==="
    else
        FAIL_COUNT=$((FAIL_COUNT+1))
        oomph_log "=== RESTART DONE, /scan STILL DEAD (fail#$FAIL_COUNT) ==="
    fi
}

while true; do
    # 连续失败 3 次 -> 停看护 2 分钟, 防止重启风暴把系统反复打挂
    if [ "$FAIL_COUNT" -ge 3 ]; then
        NOW=$(date +%s)
        if [ $((NOW - LAST_FAIL_TIME)) -lt 120 ]; then
            oomph_log "FAIL_COUNT=$FAIL_COUNT, cooling down 120s"
            sleep 30
            continue
        fi
        FAIL_COUNT=0
    fi

    if scan_alive; then
        FAIL_COUNT=0
    else
        oomph_log "/scan silent -> restart_all"
        LAST_FAIL_TIME=$(date +%s)
        restart_everything
    fi
    sleep 15
done