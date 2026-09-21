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
    # 轻量探针: 4s 内收到一条 /scan 即算存活。
    # 原实现 `ros2 topic hz --window 20` 每次吃满一个核 ~8s, 是建图/遥控时的周期性卡顿源。
    python3 /home/sunrise/robot_ws/scripts/scan_alive.py 4 >/dev/null 2>&1
}

# 只重启雷达: 不动 slam_toolbox / 里程计 / rviz, 已建地图不会丢。
# USB 瞬断(EMI)多数能在这一步恢复, 不必整栈重来。
restart_lidar_only() {
    oomph_log "--- restart lidar only ---"
    pkill -9 -x rplidar_node 2>/dev/null
    sleep 3
    nohup bash -c 'source /opt/ros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; ros2 launch rplidar_ros rplidar_a1_launch.py' > /home/sunrise/robot_ws/logs/rplidar.log 2>&1 &
    sleep 8
}

restart_everything() {
    OOM="$(date '+%F %T')"
    # 诊断: ROS 环境? rplidar 进程还在?
    RD="$(pgrep -x rplidar_node >/dev/null && echo 'rplidar_running' || echo 'rplidar_dead')"
    ST="$(pgrep -f stm32_bridge_node >/dev/null && echo 'bridge_running' || echo 'bridge_dead')"
    NO="$(timeout 5 ros2 node list 2>/dev/null | grep -c local_planner_dwa || true)"
    # 导航栈之前在跑吗? 决定重启后要不要一并拉起(地图会重建, 旧目标/旧路径作废)
    NAV_WAS_RUNNING=no
    pgrep -f "nav.launch.py" >/dev/null 2>&1 && NAV_WAS_RUNNING=yes
    oomph_log "=== RESTART CORE + RVIZ [$OOM] [$RD] [$ST] [nav_node=$NO] [nav=$NAV_WAS_RUNNING] ==="

    pkill -9 -f robot.launch.py 2>/dev/null
    pkill -9 -f robot_core.launch.py 2>/dev/null
    pkill -9 -f rplidar_node 2>/dev/null
    pkill -9 -f async_slam_toolbox_node 2>/dev/null
    pkill -9 -f robot_state_publisher 2>/dev/null
    pkill -9 -f static_transform_publisher 2>/dev/null
    pkill -9 -f stm32_bridge_node 2>/dev/null
    pkill -9 -f gamepad_cmd_vel.py 2>/dev/null

    # 导航三层也归 core 管: 不一起停, 重启后就会拿着旧地图/旧目标继续跑。
    # 只有确认之前跑着才动它, 避免误杀 GUI 单独起的 goal_bridge。
    if [ "$NAV_WAS_RUNNING" = yes ]; then
        pkill -9 -f nav.launch.py 2>/dev/null
        pkill -9 -f global_planner_node 2>/dev/null
        pkill -9 -f local_planner_node 2>/dev/null
        pkill -9 -f pid_controller_node 2>/dev/null
        pkill -9 -f goal_bridge_node 2>/dev/null
    fi
    sleep 3

    nohup bash -c 'source /opt/ros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; ros2 launch robot_bringup robot_core.launch.py' > /home/sunrise/robot_ws/logs/core.log 2>&1 &
    sleep 12
    pgrep -x rviz2 > /dev/null || {
        nohup bash -c 'source /opt/ros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; export DISPLAY=:0.0; export XAUTHORITY=/home/sunrise/.Xauthority; ros2 run rviz2 rviz2 -d /home/sunrise/robot_ws/config/robot.rviz' > /home/sunrise/robot_ws/logs/rviz.log 2>&1 &
    }

    # nav 之前在跑 -> 随 core 一起重建(地图已重来, 旧目标/旧路径不再有意义)
    if [ "$NAV_WAS_RUNNING" = yes ]; then
        oomph_log "nav was running -> restart nav.launch.py"
        nohup bash -c 'source /opt/ros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; ros2 launch library_nav nav.launch.py' > /home/sunrise/robot_ws/logs/nav.log 2>&1 &
    fi

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
        oomph_log "/scan silent -> restart lidar only (first try)"
        LAST_FAIL_TIME=$(date +%s)
        restart_lidar_only
        if scan_alive; then
            oomph_log "--- lidar-only restart recovered (map preserved) ---"
            FAIL_COUNT=0
        else
            oomph_log "/scan still silent -> restart_all"
            restart_everything
        fi
    fi
    sleep 15
done