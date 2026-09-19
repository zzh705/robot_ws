#!/usr/bin/env bash
# ============================================================
#  start_library_gui.sh — 图书馆机器人上位机一键启动 / 开机自启
#
#  拉起两样东西：
#    1) goal_bridge_node   监听 127.0.0.1:9000
#                          GUI 的 find_book 请求 → ROS2 /goal_pose
#    2) GUI.py             PySide6 图书馆界面（跑在 :0.0 桌面）
#
#  用法：
#    ./start_library_gui.sh            启动（默认）
#    ./start_library_gui.sh start
#    ./start_library_gui.sh stop
#    ./start_library_gui.sh restart
#    ./start_library_gui.sh status
#
#  开关（环境变量）：
#    RUN_BRIDGE=0   只起界面，不起 goal_bridge
#    RUN_GUI=0      只起 goal_bridge（无桌面时用）
#    RUN_NAV=1      额外拉起导航三层（A*/DWA/PID）—— 默认关闭！
#                   打开后 /goal_pose 会真的驱动小车，务必先架空轮子
#
#  开机自启：
#    ~/.config/autostart/library-gui.desktop 以 sunrise 身份调用本脚本
#    （模板见同目录 library-gui.desktop）
#
#  日志：本目录 logs/ 下 goal_bridge.log / gui.log / autostart.log
#
#  幂等：已在跑的不重复拉起；9000 被别的进程占用时【不抢端口】，只告警。
# ============================================================

set -u

APP_DIR="/home/sunrise/robot_ws/library_gui"
WS_DIR="/home/sunrise/robot_ws"
ROS_SETUP="/opt/ros/humble/setup.bash"
WS_SETUP="${WS_DIR}/install/setup.bash"
PYTHON="/usr/bin/python3"

RUN_USER="sunrise"
DISPLAY_ID=":0.0"
XAUTH="/home/sunrise/.Xauthority"
X_SOCK="/tmp/.X11-unix/X0"

BRIDGE_HOST="127.0.0.1"
BRIDGE_PORT="9000"

LOG_DIR="${APP_DIR}/logs"
BRIDGE_LOG="${LOG_DIR}/goal_bridge.log"
GUI_LOG="${LOG_DIR}/gui.log"
MAIN_LOG="${LOG_DIR}/autostart.log"

RUN_BRIDGE="${RUN_BRIDGE:-1}"
RUN_GUI="${RUN_GUI:-1}"
RUN_NAV="${RUN_NAV:-0}"

mkdir -p "${LOG_DIR}"

log() {
    echo "$(date '+%F %T') $*" >> "${MAIN_LOG}"
    echo "$(date '+%F %T') $*"
}

# ------------------------------------------------------------
#  探测小工具
# ------------------------------------------------------------

# 9000 是否已被监听。
# 只看端口状态、不看进程名：非 root 身份下 ss -p 看不到别人的进程，
# 若拿“进程名非空”当判据，会把“别人占着”误判成“端口空闲”而去抢。
port_listening() {
    ss -lnt 2>/dev/null | grep -qF ":${BRIDGE_PORT} "
}

# 9000 当前持有者进程名（best-effort，非 root 时可能为空）
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
            log "[bridge]    按“不抢端口”处理，跳过启动。要让本脚本接管，请先停掉占用者"
        fi
        return 0
    fi

    log "[bridge] 启动 goal_bridge_node（${BRIDGE_HOST}:${BRIDGE_PORT}）"

    setsid nohup bash -c "
        source '${ROS_SETUP}'
        source '${WS_SETUP}'
        exec ros2 run library_nav goal_bridge_node \
            --ros-args -p tcp_host:=${BRIDGE_HOST} -p tcp_port:=${BRIDGE_PORT}
    " >> "${BRIDGE_LOG}" 2>&1 &

    if wait_for_port; then
        log "[bridge] OK：${BRIDGE_PORT} 已监听"
        return 0
    fi

    log "[bridge] !! 12s 内没等到 ${BRIDGE_PORT} 监听，看 ${BRIDGE_LOG}"
    return 1
}

# ------------------------------------------------------------
#  启动导航三层（默认关闭）
# ------------------------------------------------------------

start_nav() {
    if [ "${RUN_NAV}" != "1" ]; then
        log "[nav] RUN_NAV=0，跳过（默认不起导航，避免开机就动）"
        return 0
    fi

    if pgrep -f "nav.launch.py" >/dev/null 2>&1; then
        log "[nav] 已在运行，跳过"
        return 0
    fi

    log "[nav] !! 拉起导航三层，/goal_pose 将真的驱动小车，确认轮子已架空"

    setsid nohup bash -c "
        source '${ROS_SETUP}'
        source '${WS_SETUP}'
        exec ros2 launch library_nav nav.launch.py
    " >> "${LOG_DIR}/nav.log" 2>&1 &

    sleep 3
    log "[nav] 已下发启动，日志 ${LOG_DIR}/nav.log"
}

# ------------------------------------------------------------
#  启动 GUI
# ------------------------------------------------------------

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

    if [ -n "$(bridge_pids)" ]; then
        log "[bridge] 停止 pid $(bridge_pids | tr '\n' ' ')"
        pkill -f "goal_bridge_node" \
            || log "[bridge] 停止失败（进程不属于当前用户，需 root 停）"
        sleep 1
    else
        log "[bridge] 本来就没在跑"
    fi

    if pgrep -f "nav.launch.py" >/dev/null 2>&1; then
        log "[nav] 停止"
        pkill -f "nav.launch.py"
        pkill -f "global_planner_node"
        pkill -f "local_planner_node"
        pkill -f "pid_controller_node"
        sleep 1
    fi
}

status_all() {
    local owner bp gp listen_state
    owner="$(port_owner)"
    bp="$(bridge_pids | tr '\n' ' ')"
    gp="$(gui_pids | tr '\n' ' ')"
    listen_state="否"
    port_listening && listen_state="是（持有者：${owner:-未知/其他用户}）"

    echo "---------- 图书馆机器人上位机 状态 ----------"
    if [ -n "${bp}" ]; then
        echo "goal_bridge : 运行中  pid=${bp}"
    else
        echo "goal_bridge : 未运行"
    fi
    echo "9000 监听   : ${listen_state}"
    if [ -n "${gp}" ]; then
        echo "GUI.py      : 运行中  pid=${gp}"
    else
        echo "GUI.py      : 未运行"
    fi
    if pgrep -f "nav.launch.py" >/dev/null 2>&1; then
        echo "导航三层    : 运行中"
    else
        echo "导航三层    : 未运行"
    fi
    echo "---------------------------------------------"
}

# ------------------------------------------------------------
#  入口
# ------------------------------------------------------------

case "${1:-start}" in
    start)
        log "===== start ====="
        start_bridge
        start_nav
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
        start_gui
        status_all
        ;;
    status)
        status_all
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 2
        ;;
esac
