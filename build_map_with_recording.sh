#!/usr/bin/env bash
# build_map_with_recording.sh — 手柄录制+回放建图完整流程
#
# 用法:
#   ./build_map_with_recording.sh record   # 步骤1: 手柄遥控录制路线 (同时建图)
#   ./build_map_with_recording.sh replay   # 步骤2: 自动回放路线 (继续建图)
#   ./build_map_with_recording.sh save     # 步骤3: 保存最终地图
#
# 前提:
#   - 已连接小车 SSH
#   - ROS 环境已配置 (source /opt/ros/humble/setup.bash 等)

set -euo pipefail

APP=/home/sunrise/robot_ws
ROS_SETUP=/opt/ros/humble/setup.bash
TROS_SETUP=/opt/tros/humble/setup.bash
WS_SETUP=$APP/install/setup.bash
PATH_FILE=$APP/logs/recorded_path.json

mkdir -p $APP/logs

# 环境加载函数
env_block() {
    source "$ROS_SETUP"
    source "$TROS_SETUP"
    source "$WS_SETUP"
    export AMENT_PREFIX_PATH=$APP/install${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}
    export PYTHONPATH=$APP/install/library_nav/lib/python3.10/site-packages:$APP/install/robot_description/lib/python3.10/site-packages:$APP/install/stm32_bridge/lib/python3.10/site-packages:$APP/install/robot_bringup/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}
    export LD_LIBRARY_PATH=/opt/tros/humble/lib:/opt/tros/humble/lib/aarch64-linux-gnu:/opt/ros/humble/lib:/opt/ros/humble/lib/aarch64-linux-gnu:/usr/hobot/lib:/app/lib:/middleware/lib:/system/lib:/system/usr/lib:/lib:/usr/lib/aarch64-linux-gnu
    export TROS_DISTRO=humble
    export PATH=/opt/tros/humble/bin:/opt/ros/humble/bin:$PATH
}

case "${1:-}" in
    record)
        echo "=== 步骤1: 启动 SLAM + 手柄遥控 + 录制 ==="
        echo "请确保小车架空(轮子不着地)或在安全区域"
        echo "按手柄按键0(急停键)切换录制开/关"
        echo "录制完成后按 Ctrl-C 退出"

        env_block

        # 启动 SLAM + 基础驱动 (不启动导航栈，避免抢 /cmd_vel)
        ros2 launch robot_bringup robot_nav_all.launch.py \
            enable_slam:=true \
            enable_nav:=false \
            enable_gamepad:=false \
            enable_rviz:=false \
            map_yaml:=$APP/maps/library.yaml \
            slam_config:=$APP/config/mapper_params_online_async.yaml \
            max_linear_x:=0.45 \
            max_angular_z:=0.9 &
        SLAM_PID=$!

        sleep 5

        # 启动手柄遥控
        python3 $APP/scripts/gamepad_cmd_vel.py &
        GAMEPAD_PID=$!

        sleep 2

        # 启动录制节点
        python3 $APP/scripts/record_path.py $PATH_FILE
        RECORD_EXIT=$?

        # 清理
        kill $GAMEPAD_PID 2>/dev/null || true
        kill $SLAM_PID 2>/dev/null || true
        wait $GAMEPAD_PID 2>/dev/null || true
        wait $SLAM_PID 2>/dev/null || true

        if [ $RECORD_EXIT -eq 0 ]; then
            echo "✅ 录制完成，路径已保存到 $PATH_FILE"
        else
            echo "⚠️ 录制被中断"
        fi
        ;;

    replay)
        echo "=== 步骤2: 启动 SLAM + 自动回放路线 ==="
        echo "小车将自动跟踪录制的路线，SLAM 继续建图"
        echo "按 Ctrl-C 可随时停止"

        if [ ! -f "$PATH_FILE" ]; then
            echo "❌ 找不到路径文件 $PATH_FILE，请先运行 record"
            exit 1
        fi

        env_block

        # 启动 SLAM + 基础驱动 (不启动导航栈)
        ros2 launch robot_bringup robot_nav_all.launch.py \
            enable_slam:=true \
            enable_nav:=false \
            enable_gamepad:=false \
            enable_rviz:=false \
            map_yaml:=$APP/maps/library.yaml \
            slam_config:=$APP/config/mapper_params_online_async.yaml \
            max_linear_x:=0.45 \
            max_angular_z:=0.9 &
        SLAM_PID=$!

        sleep 5

        # 启动回放节点
        python3 $APP/scripts/replay_path.py $PATH_FILE \
            --lookahead 0.3 \
            --speed 0.15 \
            --max-wz 0.5
        REPLAY_EXIT=$?

        # 清理
        kill $SLAM_PID 2>/dev/null || true
        wait $SLAM_PID 2>/dev/null || true

        if [ $REPLAY_EXIT -eq 0 ]; then
            echo "✅ 回放完成"
        else
            echo "⚠️ 回放被中断"
        fi
        ;;

    save)
        echo "=== 步骤3: 保存地图 ==="
        env_block
        ros2 run nav2_map_server map_saver_cli -f $APP/maps/my_map \
            --ros-args -p use_sim_time:=false
        echo "✅ 地图已保存到 $APP/maps/my_map.pgm + .yaml"
        ;;

    *)
        echo "用法: $0 {record|replay|save}"
        echo "  record  - 手柄遥控录制路线 (同时建图)"
        echo "  replay  - 自动回放路线 (继续建图)"
        echo "  save    - 保存最终地图"
        exit 1
        ;;
esac