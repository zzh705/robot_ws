#!/usr/bin/env bash
# ============================================================
#  start_library_gui.sh — 图书馆机器人上位机一键启动 / 开机自启
#
#  拉起四样东西：
#    1) goal_bridge_node       监听 127.0.0.1:9000
#    2) 统一导航栈 robot_nav_all (rplidar + STM32 + map_server +
#                                A* + DWA + PID + scan 软更新层)
#    3) GUI.py                 PySide6 图书馆界面（跑在 :0.0 桌面）
#    4) hobot_tts              订阅 /tts_text，把 AI 回答念出来
#
#  默认 RUN_NAV=1：导航栈会拉起；GUI 点击地图后 /goal_pose 会真的驱动小车。
#  只想调试 GUI 不动车：RUN_NAV=0 ./start_library_gui.sh start
#
#  用法：
#    ./start_library_gui.sh            启动（默认）
#    ./start_library_gui.sh start
#    ./start_library_gui.sh stop
#    ./start_library_gui.sh restart
#    ./start_library_gui.sh status
#    ./start_library_gui.sh start_nav  只拉导航栈
#    ./start_library_gui.sh stop_nav   只停导航栈
#    ./start_library_gui.sh diag       快速诊断 ROS 链路
#
#  开机自启：
#    ~/.config/autostart/library-gui.desktop 以 sunrise 身份调用本脚本
#
#  日志：本目录 logs/ 下 goal_bridge.log / gui.log / autostart.log / nav.log
#
#  幂等：已在跑的不重复拉起；9000 被别的进程占用时【不抢端口】，只告警。
# ============================================================

set +u

APP_DIR="/home/sunrise/robot_ws/library_gui"
WS_DIR="/home/sunrise/robot_ws"
ROS_SETUP="/opt/ros/humble/setup.bash"
TROS_SETUP="/opt/tros/humble/setup.bash"
WS_SETUP="${WS_DIR}/install/setup.bash"
PYTHON="/usr/bin/python3"

RUN_USER="sunrise"
DISPLAY_ID=":0.0"
XAUTH="/home/sunrise/.Xauthority"
X_SOCK="/tmp/.X11-unix/X0"

BRIDGE_HOST="127.0.0.1"
BRIDGE_PORT="9000"

# hobot_tts 的模型目录写死在二进制里（相对包路径），不要挪
TTS_MODEL_DIR="/opt/tros/humble/lib/hobot_tts/tts_model"

LOG_DIR="${APP_DIR}/logs"
BRIDGE_LOG="${LOG_DIR}/goal_bridge.log"
GUI_LOG="${LOG_DIR}/gui.log"
MAIN_LOG="${LOG_DIR}/autostart.log"
NAV_LOG="${LOG_DIR}/nav.log"
TTS_LOG="${LOG_DIR}/tts.log"

RUN_BRIDGE="${RUN_BRIDGE:-1}"
RUN_GUI="${RUN_GUI:-1}"
RUN_NAV="${RUN_NAV:-1}"
RUN_TTS="${RUN_TTS:-1}"

mkdir -p "${LOG_DIR}"

# 完整 ROS+TROS+ws 环境 (供 setsid 子 shell 用)
# 必须是纯命令, 不能依赖 shell 函数( setsid 子 shell 里函数不会传过来)
ROS_ENV_HEAD='source /opt/ros/humble/setup.bash; source /opt/tros/humble/setup.bash; source /home/sunrise/robot_ws/install/setup.bash; export AMENT_PREFIX_PATH=/opt/tros/humble:/opt/ros/humble:/home/sunrise/robot_ws/install; export LD_LIBRARY_PATH=/opt/tros/humble/lib:/opt/tros/humble/lib/aarch64-linux-gnu:/opt/ros/humble/lib:/opt/ros/humble/lib/aarch64-linux-gnu:/usr/hobot/lib:/app/lib:/middleware/lib:/system/lib:/system/usr/lib:/lib:/usr/lib/aarch64-linux-gnu; export TROS_DISTRO=humble; export PATH=/opt/tros/humble/bin:/opt/ros/humble/bin:$PATH;'

# 日志轮转: 单文件超 5MB 时压缩为 .1.gz, 依次顺延, 最多保留 3 份
rotate_logs() {
    for f in "${BRIDGE_LOG}" "${GUI_LOG}" "${MAIN_LOG}" "${NAV_LOG}" "${TTS_LOG}"; do
        [ -f "$f" ] || continue
        size_k="$(du -k "$f" 2>/dev/null | awk '{print $1}')"
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

log() {
    echo "$(date '+%F %T') $*" >> "${MAIN_LOG}"
    echo "$(date '+%F %T') $*"
}

# ------------------------------------------------------------
#  探测小工具
# ------------------------------------------------------------

port_listening() {
    ss -lnt 2>/dev/null | grep -qF ":${BRIDGE_PORT} "
}

port_owner() {
    ss -lntp 2>/dev/null \
        | grep -F ":${BRIDGE_PORT} " \
        | sed -n 's/.*users:(("\([^"]*\)".*/\1/p' \
        | head -1
}

bridge_pids() {
    pgrep -f "goal_bridge_node" 2>/dev/null | grep -v -e "^$$\$" -e "^${PPID}\$"
}

gui_pids() {
    pgrep -f "python3 GUI.py" 2>/dev/null | grep -v -e "^$$\$" -e "^${PPID}\$"
}

nav_pids() {
    pgrep -f "robot_nav_all.launch.py" 2>/dev/null
}

tts_pids() {
    pgrep -f "lib/hobot_tts/hobot_tts" 2>/dev/null
}

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
        [ -e "${X_SOCK}" ] && return 0
        sleep 1
    done
    return 1
}

# 健康探测: 节点数 + 关键 topic 是否齐
# 这是"GUI 点了地图车不动"问题的快速自检, 不通过就在 status/diag 提示
probe_nav_stack() {
    local n t
    n="$(timeout 6 ros2 node list 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${n:-0}" -lt 4 ]; then
        log "[health] ros2 node 只有 ${n} 个 (<4), 栈未起"
        return 1
    fi
    for t in /goal_pose /scan /odom /cmd_vel /cmd_vel_plan /global_path /map; do
        if ! timeout 3 ros2 topic list 2>/dev/null | grep -qxF "$t"; then
            log "[health] 缺 topic $t"
            return 1
        fi
    done
    log "[health] OK: ${n} 节点, 关键 topic 齐"
    return 0
}

# ------------------------------------------------------------
#  启动 goal_bridge
# ------------------------------------------------------------

start_bridge() {
    if [ "${RUN_BRIDGE}" != "1" ]; then
        log "[bridge] RUN_BRIDGE=0，跳过"
        return 0
    fi

    if port_listening; then
        if [ -n "$(bridge_pids)" ]; then
            log "[bridge] 已在运行（pid $(bridge_pids | tr '\n' ' ')），跳过"
        else
            log "[bridge] ${BRIDGE_PORT} 已被其他进程监听（非本用户时看不到进程名，多半是 root 起的 goal_bridge）"
            log "[bridge]    按"不抢端口"处理，跳过启动。要让本脚本接管，请先停掉占用者"
        fi
        return 0
    fi

    log "[bridge] 启动 goal_bridge_node（${BRIDGE_HOST}:${BRIDGE_PORT}）"

    setsid nohup bash -c "${ROS_ENV_HEAD} exec ros2 run library_nav goal_bridge_node \
        --ros-args -p tcp_host:=${BRIDGE_HOST} -p tcp_port:=${BRIDGE_PORT}" \
        >> "${BRIDGE_LOG}" 2>&1 &

    if wait_for_port; then
        log "[bridge] OK：${BRIDGE_PORT} 已监听"
        return 0
    fi

    log "[bridge] !! 12s 内没等到 ${BRIDGE_PORT} 监听，看 ${BRIDGE_LOG}"
    return 1
}

# ------------------------------------------------------------
#  启动统一导航栈 (默认开启)
# ------------------------------------------------------------

start_nav() {
    if [ "${RUN_NAV}" != "1" ]; then
        log "[nav] RUN_NAV=0，跳过（用户显式关闭，GUI 不会让轮子动）"
        return 0
    fi

    if [ -n "$(nav_pids)" ]; then
        log "[nav] 已在运行（pid $(nav_pids | tr '\n' ' ')），跳过（停栈用 $0 stop_nav）"
        return 0
    fi

    log "[nav] !! 拉起统一导航栈 (robot_nav_all)"
    log "[nav]    地图按钮派单将驱动小车，确认轮子已架空"
    log "[nav]    不动车: RUN_NAV=0 ./start_library_gui.sh start"

    setsid nohup bash -c "${ROS_ENV_HEAD} exec ros2 launch robot_bringup robot_nav_all.launch.py \
        map_yaml:=/home/sunrise/robot_ws/maps/library.yaml \
        enable_slam:=false \
        enable_nav:=true \
        enable_gamepad:=false \
        enable_rviz:=false \
        max_linear_x:=0.45 \
        max_angular_z:=0.9 \
        control_period:=0.05" \
        >> "${NAV_LOG}" 2>&1 &

    # 启动后健康探测: 节点 + 关键 topic 齐了才算成功
    local i
    for i in 1 2 3 4 5 6; do
        sleep 4
        if probe_nav_stack; then
            log "[nav] 健康 OK（${i}*4s 后）"
            return 0
        fi
    done
    log "[nav] !! 健康探测失败，日志 ${NAV_LOG}"
    return 1
}

stop_nav() {
    if [ -z "$(nav_pids)" ]; then
        log "[nav] 没在跑"
        return 0
    fi
    log "[nav] 停统一导航栈 pid=$(nav_pids | tr '\n' ' ')"
    pkill -f "robot_nav_all.launch.py"
    pkill -f "global_planner_node"
    pkill -f "local_planner_node"
    pkill -f "pid_controller_node"
    pkill -f "map_server"
    pkill -f "lifecycle_manager"
    pkill -f "rplidar_node"
    pkill -f "robot_state_publisher"
    pkill -f "stm32_bridge"
    pkill -f "static_transform_publisher"
    sleep 1
    log "[nav] 已停"
}

# ------------------------------------------------------------
#  启动 GUI
# ------------------------------------------------------------

start_tts() {
    if [ "${RUN_TTS}" != "1" ]; then
        log "[tts] RUN_TTS=0，跳过"
        return 0
    fi

    if [ -n "$(tts_pids)" ]; then
        log "[tts] 已在运行（pid $(tts_pids | tr '\n' ' ')），跳过"
        return 0
    fi

    if [ ! -d "${TTS_MODEL_DIR}" ]; then
        log "[tts] !! 模型缺失 ${TTS_MODEL_DIR}，界面的朗读按钮会报错"
        log "[tts]    解压: tar -xzf ${APP_DIR}/tts_model.tar.gz -C /opt/tros/humble/lib/hobot_tts/"
        return 1
    fi

    log "[tts] 启动 hobot_tts（订阅 /tts_text）"

    setsid nohup bash -c "${ROS_ENV_HEAD} cd /opt/tros/humble/lib/hobot_tts && exec ros2 run hobot_tts hobot_tts --ros-args -p playback_device:=plughw:1,0" \
        >> "${TTS_LOG}" 2>&1 &

    sleep 3
    if [ -n "$(tts_pids)" ]; then
        log "[tts] OK：pid $(tts_pids | tr '\n' ' ')"
        return 0
    fi

    log "[tts] !! hobot_tts 没起来，看 ${TTS_LOG}"
    return 1
}

start_gui() {
    if [ "${RUN_GUI}" != "1" ]; then
        log "[gui] RUN_GUI=0，跳过"
        return 0
    fi

    if [ -n "$(gui_pids)" ]; then
        log "[gui] 已在运行（pid $(gui_pids | tr '\n' ' ')），跳过"
        return 0
    fi

    if ! wait_for_display; then
        log "[gui] !! 60s 内没等到 X 桌面 ${DISPLAY_ID}，跳过启动界面"
        return 1
    fi

    log "[gui] 启动 GUI.py（DISPLAY=${DISPLAY_ID}）"

    cd "${APP_DIR}" || return 1

    setsid nohup env \
        DISPLAY="${DISPLAY_ID}" \
        XAUTHORITY="${XAUTH}" \
        HOME="/home/${RUN_USER}" \
        "${PYTHON}" GUI.py >> "${GUI_LOG}" 2>&1 &

    sleep 4
    if [ -n "$(gui_pids)" ]; then
        log "[gui] OK：pid $(gui_pids | tr '\n' ' ')"
        return 0
    fi

    log "[gui] !! GUI 没起来，看 ${GUI_LOG}"
    return 1
}

# ------------------------------------------------------------
#  停止 / 状态
# ------------------------------------------------------------

stop_all() {
    if [ -n "$(gui_pids)" ]; then
        log "[gui] 停止 pid $(gui_pids | tr '\n' ' ')"
        pkill -f "python3 GUI.py" \
            || log "[gui] 停止失败（进程不属于当前用户，需 root 停）"
        sleep 1
    else
        log "[gui] 本来就没在跑"
    fi

    stop_nav

    if [ -n "$(bridge_pids)" ]; then
        log "[bridge] 停止 pid $(bridge_pids | tr '\n' ' ')"
        pkill -f "goal_bridge_node" \
            || log "[bridge] 停止失败（进程不属于当前用户，需 root 停）"
        sleep 1
    else
        log "[bridge] 本来就没在跑"
    fi

    if [ -n "$(tts_pids)" ]; then
        log "[tts] 停止 pid $(tts_pids | tr '\n' ' ')"
        pkill -f "lib/hobot_tts/hobot_tts" || log "[tts] 停止失败（需 root 停）"
        sleep 1
    else
        log "[tts] 本来就没在跑"
    fi
}

status_all() {
    local owner bp gp nav_count topic_count
    owner="$(port_owner)"
    bp="$(bridge_pids | tr '\n' ' ')"
    gp="$(gui_pids | tr '\n' ' ')"
    nav_count="$(timeout 4 ros2 node list 2>/dev/null | wc -l | tr -d ' ')"
    topic_count="$(timeout 4 ros2 topic list 2>/dev/null | wc -l | tr -d ' ')"

    echo "---------- 图书馆机器人上位机 状态 ----------"
    if [ -n "${bp}" ]; then
        echo "goal_bridge : 运行中  pid=${bp}"
    else
        echo "goal_bridge : 未运行"
    fi
    local listen_state="否"
    port_listening && listen_state="是（持有者：${owner:-未知/其他用户}）"
    echo "9000 监听   : ${listen_state}"
    if [ -n "${gp}" ]; then
        echo "GUI.py      : 运行中  pid=${gp}"
    else
        echo "GUI.py      : 未运行"
    fi
    echo "ROS 节点    : ${nav_count:-0} 个   topic: ${topic_count:-0} 个"
    if [ -n "$(nav_pids)" ]; then
        echo "导航栈      : 运行中 (robot_nav_all)"
    else
        echo "导航栈      : 未运行  (GUI 派单不会动)"
    fi
    if pgrep -f "map_server" >/dev/null 2>&1; then
        echo "静态地图    : 运行中"
    else
        echo "静态地图    : 未运行"
    fi
    if pgrep -f "rplidar_node" >/dev/null 2>&1; then
        echo "雷达        : 运行中"
    else
        echo "雷达        : 未运行"
    fi
    if pgrep -f "stm32_bridge" >/dev/null 2>&1; then
        echo "底盘桥接    : 运行中"
    else
        echo "底盘桥接    : 未运行"
    fi
    if [ -n "$(tts_pids)" ]; then
        echo "语音播报    : 运行中  pid=$(tts_pids | tr '\n' ' ')"
    else
        echo "语音播报    : 未运行（hobot_tts）"
    fi
    echo "---------------------------------------------"
}

# ------------------------------------------------------------
#  入口
# ------------------------------------------------------------

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
        log "===== start_nav ====="
        start_nav
        status_all
        ;;
    stop_nav)
        log "===== stop_nav ====="
        stop_nav
        status_all
        ;;
    diag)
        echo "===== ros2 node list ====="
        timeout 6 ros2 node list 2>&1 || true
        echo
        echo "===== ros2 topic list ====="
        timeout 6 ros2 topic list 2>&1 || true
        echo
        echo "===== 关键 topic 频率 (1 秒) ====="
        for t in /scan /odom /cmd_vel /cmd_vel_plan /global_path /goal_pose /map; do
            rate="$(timeout 4 ros2 topic hz "$t" 2>/dev/null | head -1)"
            echo "  $t : ${rate:-no data}"
        done
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|start_nav|stop_nav|diag}"
        exit 2
        ;;
esac