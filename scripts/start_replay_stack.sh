#!/usr/bin/env bash
# start_replay_stack.sh — 回放用最小栈: 只要 /odom + /scan，不建图不导航
#
#   enable_slam:=false   不起 slam_toolbox (不建图, 省 CPU)
#   enable_nav:=false    不起 A*/DWA/PID   (不抢 /cmd_vel)
#   enable_gamepad:=false 不起手柄         (/cmd_vel 留给 replay_path)
#
# 产物: /odom (stm32_bridge) + /scan (rplidar)
set -o pipefail
# 不要 set -u: ROS setup.bash 里有未绑定变量引用 (AMENT_TRACE_SETUP_FILES)
APP=/home/sunrise/robot_ws

env_block() {
    source /opt/ros/humble/setup.bash
    source /opt/tros/humble/setup.bash
    source $APP/install/setup.bash
    export AMENT_PREFIX_PATH=$APP/install${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}
    export PYTHONPATH=$APP/install/library_nav/lib/python3.10/site-packages:$APP/install/robot_description/lib/python3.10/site-packages:$APP/install/stm32_bridge/lib/python3.10/site-packages:$APP/install/robot_bringup/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}
    # 前置而非覆盖: source setup.bash 会把 rviz_ogre_vendor/lib 加进来,
    # 硬覆盖会让 rviz2 报 "error while loading shared libraries" 起不来
    export LD_LIBRARY_PATH=/opt/tros/humble/lib:/opt/tros/humble/lib/aarch64-linux-gnu:/opt/ros/humble/lib:/opt/ros/humble/lib/aarch64-linux-gnu:/usr/hobot/lib:/app/lib:/middleware/lib:/system/usr/lib:/lib:/usr/lib/aarch64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
    export TROS_DISTRO=humble
    export PATH=/opt/tros/humble/bin:/opt/ros/humble/bin:$PATH
}

cd "$APP" || exit 1
env_block

exec ros2 launch robot_bringup robot_nav_all.launch.py \
    enable_slam:=false \
    enable_nav:=false \
    enable_gamepad:=false \
    enable_rviz:=false \
    map_yaml:=$APP/maps/room_run4.yaml