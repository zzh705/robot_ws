#!/usr/bin/env bash
# start_mapping_session.sh — 一条命令重开一轮完整建图会话
#
#   1. 停录当前轮(保存路径)   2. 全栈停
#   3. 起全新 SLAM(地图清零)  4. 手柄驱动
#   5. 路径录制器(新文件)      6. RViz2(宽视野配置)
#   7. 开录
#
# 用法:
#   bash scripts/start_mapping_session.sh            # 自动用 path_run<N>.json
#   bash scripts/start_mapping_session.sh my_room    # 指定名字 -> logs/my_room.json
set -o pipefail
# 注意: 不能用 set -u —— ROS 的 setup.bash 里有未绑定变量引用
# (AMENT_TRACE_SETUP_FILES), 开了 -u 会在 source 阶段直接退出

APP=/home/sunrise/robot_ws
SCRIPTS=$APP/scripts
LOGS=$APP/logs
mkdir -p "$LOGS"
TAG="${1:-}"

# ---------- 环境 ----------
env_block() {
    source /opt/ros/humble/setup.bash
    source /opt/tros/humble/setup.bash
    source $APP/install/setup.bash
    export AMENT_PREFIX_PATH=$APP/install${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}
    export PYTHONPATH=$APP/install/library_nav/lib/python3.10/site-packages:$APP/install/robot_description/lib/python3.10/site-packages:$APP/install/stm32_bridge/lib/python3.10/site-packages:$APP/install/robot_bringup/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}
    # 必须"前置"而不是"覆盖": source setup.bash 会把
    # /opt/ros/humble/opt/rviz_ogre_vendor/lib 加进来(rviz2 的 libOgreMain 在那),
    # 硬覆盖会让 rviz2 直接报 "error while loading shared libraries" 起不来。
    export LD_LIBRARY_PATH=/opt/tros/humble/lib:/opt/tros/humble/lib/aarch64-linux-gnu:/opt/ros/humble/lib:/opt/ros/humble/lib/aarch64-linux-gnu:/usr/hobot/lib:/app/lib:/middleware/lib:/system/usr/lib:/lib:/usr/lib/aarch64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
    export TROS_DISTRO=humble
    export PATH=/opt/tros/humble/bin:/opt/ros/humble/bin:$PATH
}

# 本脚本自身也要 ROS 环境(第 1 步和第 7 步要调 ros2 topic pub)
env_block

# ---------- 1. 停录并保存当前轮 ----------
echo "[1/7] 停录并保存当前轮 ..."
if pgrep -f "record_path.py" >/dev/null 2>&1; then
    ros2 topic pub --once /record_path std_msgs/msg/Bool "{data: false}" >/dev/null 2>&1 &
    sleep 2
fi

# ---------- 2. 全栈停 ----------
echo "[2/7] 停全部进程 ..."
bash "$SCRIPTS/stop_all.sh" >/dev/null 2>&1
systemctl disable --now rplidar.service >/dev/null 2>&1
sleep 2

# ---------- 3. 全新 SLAM ----------
echo "[3/7] 起 SLAM(地图清零) ..."
setsid bash "$SCRIPTS/start_slam.sh" > /tmp/slam_launch.log 2>&1 < /dev/null &
sleep 14

# ---------- 4~6. 手柄 + 录制器 + RViz ----------
if [ -z "$TAG" ]; then
    # 取已有最大编号 +1, 而不是从 1 开始找空洞 (避免生成 path_run1.json 这种乱序名)
    N=$(ls "$LOGS" 2>/dev/null | sed -n 's/^path_run\([0-9]\+\)\.json$/\1/p' | sort -n | tail -1)
    N=${N:-0}
    N=$((N + 1))
    TAG="path_run$N"
fi
echo "[4/7] 手柄驱动 ..."
setsid bash -c "$(declare -f env_block); APP=$APP; SCRIPTS=$SCRIPTS; env_block; cd $APP; exec python3 -u $SCRIPTS/gamepad_cmd_vel.py" \
    > /tmp/gamepad.log 2>&1 < /dev/null &

echo "[5/7] 路径录制器 -> $TAG.json ..."
setsid bash -c "$(declare -f env_block); APP=$APP; SCRIPTS=$SCRIPTS; env_block; cd $APP; exec python3 -u $SCRIPTS/record_path.py $LOGS/$TAG.json" \
    > /tmp/record.log 2>&1 < /dev/null &

echo "[6/7] RViz2 ..."
setsid bash -c "$(declare -f env_block); APP=$APP; env_block; export DISPLAY=:0; export XAUTHORITY=/var/run/lightdm/root/:0; exec rviz2 -d $APP/config/robot_map.rviz" \
    > /tmp/rviz.log 2>&1 < /dev/null &

sleep 20

# ---------- 7. 开录 ----------
echo "[7/7] 开始录制 ..."
ros2 topic pub --once /record_path std_msgs/msg/Bool "{data: true}" >/dev/null 2>&1
sleep 1

# ---------- 状态 ----------
echo
echo "================ 本轮状态 ================"
echo "录制文件 : $LOGS/$TAG.json"
FAIL=0
for proc in slam_toolbox stm32_bridge_node rplidar_node gamepad_cmd_vel record_path.py rviz2; do
    n=$(pgrep -cf "$proc" 2>/dev/null || echo 0)
    # record_path.py / rviz2 用完整路径匹配, 避免 pgrep -f 匹配到本脚本自身
    case "$proc" in
        record_path.py|rviz2)
            if pgrep -af "$proc" 2>/dev/null | grep -qv "bash -c"; then :; else n=0; fi
            ;;
    esac
    if [ "${n:-0}" -gt 0 ]; then
        printf "  ✅ %-20s\n" "$proc"
    else
        printf "  ❌ %-20s  <-- 没起来!\n" "$proc"
        FAIL=1
    fi
done
echo "  /odom  : $(timeout 6 ros2 topic hz /odom 2>&1 | grep -oE 'average rate: [0-9.]+' | head -1)"
echo "  /scan  : $(timeout 6 ros2 topic hz /scan 2>&1 | grep -oE 'average rate: [0-9.]+' | head -1)"
echo "  /map   : $(timeout 8 ros2 topic echo /map --field info 2>/dev/null | grep -E 'width|height' | head -2 | tr -d ' \n')"
echo "  录制起点: $(grep '起点' /tmp/record.log | tail -1 | sed 's/.*起点/起点/')"
[ "$FAIL" = "1" ] && echo "  >>> 有进程没起来, 看 /tmp/rviz.log /tmp/record.log /tmp/gamepad.log"
echo "========================================="