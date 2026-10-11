#!/usr/bin/env bash
# start_full_stack.sh —— 图书馆机器人一键拉起全栈 (Moss 2026-09-23)
#
# 启动后下发的进程:
#   1) goal_bridge_node        127.0.0.1:9000 (GUI 派单入口)
#   2) ros2 launch robot_bringup robot_nav_all.launch.py
#      包含: rplidar + robot_state_publisher + stm32_bridge
#            + nav2_map_server (静态 library.yaml) + lifecycle_manager
#            + map→odom 静态 TF + goal_bridge_node
#            + A* 全局规划(带 /scan 软更新层 + 目标点吸附)
#            + DWA 局部规划(20Hz)
#            + PID 速度闭环(kd 阻尼消除卡顿)
#   3) GUI.py (PySide6)         桌面端
#   4) hobot_tts                /tts_text
#
# 用法:
#   ./start_full_stack.sh start        # 全栈起 (默认; /goal_pose 会驱动小车, 务必架空)
#   ./start_full_stack.sh stop         # 全栈停
#   ./start_full_stack.sh restart      # 重启全栈
#   ./start_full_stack.sh status       # 状态
#   ./start_full_stack.sh diag         # 快速诊断
#
# 环境变量 (可选):
#   RUN_GUI=0        不起 GUI  (无桌面时)
#   RUN_TTS=0        不起 hobot_tts
#   RUN_NAV=0        不起导航栈 (调试 GUI 用; /goal_pose 不会动底盘)
#   RUN_BRIDGE=0     不起 goal_bridge_node
#   ROS_HOST=10.1.27.42   板端 IP, 默认走 127.0.0.1

set +u

APP=/home/sunrise/robot_ws
APP_GUI=$APP/library_gui
ROS_SETUP=/opt/ros/humble/setup.bash
TROS_SETUP=/opt/tros/humble/setup.bash
WS_SETUP=$APP/install/setup.bash

LOGS=$APP/library_gui/logs
BRIDGE_LOG=$LOGS/goal_bridge.log
GUI_LOG=$LOGS/gui.log
MAIN_LOG=$LOGS/autostart.log
NAV_LOG=$LOGS/nav.log
TTS_LOG=$LOGS/tts.log

DISPLAY_ID=:0.0
XAUTH=/home/sunrise/.Xauthority
X_SOCK=/tmp/.X11-unix/X0

RUN_BRIDGE=${RUN_BRIDGE:-1}
RUN_GUI=${RUN_GUI:-1}
RUN_NAV=${RUN_NAV:-1}
RUN_TTS=${RUN_TTS:-1}

mkdir -p "$LOGS"

# ============================================================
#  环境注入 (这段是关键: ros humble 不能被覆盖, 只能 prepend)
# ============================================================
env_block() {
    echo "source '$ROS_SETUP'"
    echo "source '$TROS_SETUP'"
    echo "source '$WS_SETUP'"
    echo 'export AMENT_PREFIX_PATH='$APP'/install${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}'
    echo 'export PYTHONPATH='$APP'/install/library_nav/lib/python3.10/site-packages:'$APP'/install/robot_description/lib/python3.10/site-packages:'$APP'/install/stm32_bridge/lib/python3.10/site-packages:'$APP'/install/robot_bringup/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}'
    echo 'export LD_LIBRARY_PATH=/opt/tros/humble/lib:/opt/tros/humble/lib/aarch64-linux-gnu:/opt/ros/humble/lib:/opt/ros/humble/lib/aarch64-linux-gnu:/usr/hobot/lib:/app/lib:/middleware/lib:/system/lib:/system/usr/lib:/lib:/usr/lib/aarch64-linux-gnu'
    echo 'export TROS_DISTRO=humble'
    echo 'export PATH=/opt/tros/humble/bin:/opt/ros/humble/bin:$PATH'
}

# ============================================================
#  辅助函数
# ============================================================
log() {
    echo "$(date '+%F %T') $*" >> "$MAIN_LOG"
    echo "$(date '+%F %T') $*"
}

rotate_logs() {
    for f in "$BRIDGE_LOG" "$GUI_LOG" "$MAIN_LOG" "$NAV_LOG" "$TTS_LOG"; do
        [ -f "$f" ] || continue
        size_k=$(du -k "$f" 2>/dev/null | awk '{print $1}')
        [ "${size_k:-0}" -gt 5120 ] || continue
        i=3
        while [ "$i" -gt 1 ]; do
            [ -f "$f.$((i-1)).gz" ] && mv -f "$f.$((i-1)).gz" "$f.$i.gz"
            i=$((i-1))
        done
        gzip -c "$f" > "$f.1.gz" 2>/dev/null
        : > "$f"
    done
}

bridge_pids() { pgrep -f 'goal_bridge_node' 2>/dev/null; }
gui_pids()    { pgrep -f 'python3 GUI.py' 2>/dev/null; }
nav_pids()    { pgrep -f 'robot_nav_all.launch.py' 2>/dev/null; }
tts_pids()    { pgrep -f 'lib/hobot_tts/hobot_tts' 2>/dev/null; }

port_listening() { ss -lnt 2>/dev/null | grep -qF ':9000 '; }

wait_for_port() {
    local i
    for i in $(seq 1 24); do
        port_listening && return 0
        sleep 0.5
    done
    return 1
}

wait_for_display() {
    local i
    for i in $(seq 1 60); do
        [ -e "$X_SOCK" ] && return 0
        sleep 1
    done
    return 1
}

probe_health() {
    local n
    n=$(timeout 6 ros2 node list 2>/dev/null | wc -l | tr -d ' ')
    [ "${n:-0}" -lt 4 ] && { echo "nav node 只有 $n (<4)"; return 1; }
    for t in /goal_pose /scan /odom /cmd_vel /cmd_vel_plan /global_path /map; do
        timeout 3 ros2 topic list 2>/dev/null | grep -qxF "$t" || { echo "缺 $t"; return 1; }
    done
    echo "OK ($n nodes, key topics齐)"
    return 0
}

# ============================================================
#  启动: goal_bridge
# ============================================================
start_bridge() {
    [ "$RUN_BRIDGE" = "1" ] || { log "[bridge] RUN_BRIDGE=0 跳过"; return 0; }
    if [ -n "$(bridge_pids)" ]; then
        log "[bridge] 已在 (pid $(bridge_pids | tr '\n' ' '))"
        return 0
    fi
    if port_listening; then
        log "[bridge] 9000 被占 (非本用户进程?), 不抢端口"
        return 0
    fi
    log "[bridge] 启动 goal_bridge_node"
    setsid nohup bash -c "$(env_block); exec ros2 run library_nav goal_bridge_node --ros-args -p tcp_host:=127.0.0.1 -p tcp_port:=9000" >> "$BRIDGE_LOG" 2>&1 &
    wait_for_port && log "[bridge] OK 9000 监听" || { log "[bridge] 失败, 看 $BRIDGE_LOG"; return 1; }
}

# ============================================================
#  启动: 统一导航栈
# ============================================================
start_nav() {
    [ "$RUN_NAV" = "1" ] || { log "[nav] RUN_NAV=0 跳过"; return 0; }
    if [ -n "$(nav_pids)" ]; then
        log "[nav] 已在 (pid $(nav_pids | tr '\n' ' '))"
        return 0
    fi
    log "[nav] 拉起统一导航栈 robot_nav_all (地图按钮派单将驱动小车)"
    setsid nohup bash -c "$(env_block); exec ros2 launch robot_bringup robot_nav_all.launch.py \
        map_yaml:=$APP/maps/library.yaml \
        enable_slam:=false \
        enable_nav:=true \
        enable_gamepad:=false \
        enable_rviz:=false \
        max_linear_x:=0.45 \
        max_angular_z:=0.9 \
        control_period:=0.05" >> "$NAV_LOG" 2>&1 &
    local i
    for i in 1 2 3 4 5 6 7 8; do
        sleep 4
        if probe_health; then
            log "[nav] 健康 OK (${i}*4s)"
            return 0
        fi
    done
    log "[nav] 健康探测失败, 看 $NAV_LOG"
    return 1
}

stop_nav() {
    [ -z "$(nav_pids)" ] && { log "[nav] 没跑"; return 0; }
    log "[nav] 停栈 pid=$(nav_pids | tr '\n' ' ')"
    pkill -f 'robot_nav_all.launch.py'
    pkill -f 'global_planner_node'
    pkill -f 'local_planner_node'
    pkill -f 'pid_controller_node'
    pkill -f 'map_server'
    pkill -f 'lifecycle_manager'
    pkill -f 'rplidar_node'
    pkill -f 'robot_state_publisher'
    pkill -f 'stm32_bridge'
    pkill -f 'static_transform_publisher'
    sleep 1
}

# ============================================================
#  启动: TTS
# ============================================================
start_tts() {
    [ "$RUN_TTS" = "1" ] || { log "[tts] RUN_TTS=0 跳过"; return 0; }
    [ -n "$(tts_pids)" ] && { log "[tts] 已在"; return 0; }
    if [ ! -d /opt/tros/humble/lib/hobot_tts/tts_model ]; then
        log "[tts] 模型缺失, 跳过 (解包: tar -xzf $APP_GUI/tts_model.tar.gz -C /opt/tros/humble/lib/hobot_tts/)"
        return 1
    fi
    log "[tts] 启动 hobot_tts"
    setsid nohup bash -c "$(env_block); cd /opt/tros/humble/lib/hobot_tts && exec ros2 run hobot_tts hobot_tts --ros-args -p playback_device:=plughw:1,0" >> "$TTS_LOG" 2>&1 &
    sleep 3
    [ -n "$(tts_pids)" ] && log "[tts] OK" || log "[tts] 失败, 看 $TTS_LOG"
}

# ============================================================
#  启动: GUI
# ============================================================
start_gui() {
    [ "$RUN_GUI" = "1" ] || { log "[gui] RUN_GUI=0 跳过"; return 0; }
    [ -n "$(gui_pids)" ] && { log "[gui] 已在"; return 0; }
    wait_for_display || { log "[gui] 等不到 X 桌面, 跳过"; return 1; }
    log "[gui] 启动 GUI.py"
    cd "$APP_GUI" || return 1
    setsid nohup env DISPLAY="$DISPLAY_ID" XAUTHORITY="$XAUTH" \
        HOME=/home/sunrise \
        /usr/bin/python3 GUI.py >> "$GUI_LOG" 2>&1 &
    sleep 4
    [ -n "$(gui_pids)" ] && log "[gui] OK" || log "[gui] 失败, 看 $GUI_LOG"
}

# ============================================================
#  停止
# ============================================================
stop_all() {
    [ -n "$(gui_pids)" ]    && { pkill -f 'python3 GUI.py';        sleep 1; log "[gui] 停"; }
    [ -n "$(tts_pids)" ]    && { pkill -f 'lib/hobot_tts/hobot_tts'; sleep 1; log "[tts] 停"; }
    [ -n "$(bridge_pids)" ] && { pkill -f 'goal_bridge_node';     sleep 1; log "[bridge] 停"; }
    stop_nav
}

# ============================================================
#  状态
# ============================================================
status_all() {
    echo "---------- 图书馆机器人上位机 状态 ----------"
    local nav_n
    nav_n=$(timeout 4 ros2 node list 2>/dev/null | wc -l | tr -d ' ')
    echo "goal_bridge : $(bridge_pids | tr '\n' ' ')"
    echo "GUI.py      : $(gui_pids    | tr '\n' ' ')"
    echo "ROS 节点    : ${nav_n:-0} 个"
    echo "导航栈      : $(nav_pids | tr '\n' ' ')"
    echo "语音播报    : $(tts_pids | tr '\n' ' ')"
    echo "9000 监听   : $(port_listening && echo 是 || echo 否)"
    echo "---------------------------------------------"
}

# ============================================================
#  入口
# ============================================================
rotate_logs

case "${1:-start}" in
    start)
        log "===== start ====="
        start_bridge
        start_nav
        start_tts
        start_gui
        status_all
        log "===== start done ====="
        ;;
    stop)
        log "===== stop ====="
        stop_all
        status_all
        ;;
    restart)
        log "===== restart ====="
        stop_all
        sleep 1
        start_bridge
        start_nav
        start_tts
        start_gui
        status_all
        ;;
    status)
        status_all
        ;;
    start_nav)
        start_bridge
        start_nav
        status_all
        ;;
    stop_nav)
        stop_nav
        status_all
        ;;
    diag)
        echo "== node list =="
        timeout 6 ros2 node list 2>&1 | head -30
        echo "== topic list =="
        timeout 6 ros2 topic list 2>&1 | head -40
        echo "== topic rates =="
        for t in /scan /odom /cmd_vel /cmd_vel_plan /global_path /goal_pose /map; do
            r=$(timeout 4 ros2 topic hz "$t" 2>/dev/null | head -1)
            echo "  $t : ${r:-no data}"
        done
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|start_nav|stop_nav|diag}"
        exit 2
        ;;
esac