#!/usr/bin/env bash
# start_slam.sh — 启动单一 SLAM 基础栈（不开导航栈、不开 GUI，避免抢 /cmd_vel）
APP=/home/sunrise/robot_ws

env_block() {
    source /opt/ros/humble/setup.bash
    source /opt/tros/humble/setup.bash
    source $APP/install/setup.bash
    export AMENT_PREFIX_PATH=$APP/install${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}
    export PYTHONPATH=$APP/install/library_nav/lib/python3.10/site-packages:$APP/install/robot_description/lib/python3.10/site-packages:$APP/install/stm32_bridge/lib/python3.10/site-packages:$APP/install/robot_bringup/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}
    export LD_LIBRARY_PATH=/opt/tros/humble/lib:/opt/tros/humble/lib/aarch64-linux-gnu:/opt/ros/humble/lib:/opt/ros/humble/lib/aarch64-linux-gnu:/usr/hobot/lib:/app/lib:/middleware/lib:/system/usr/lib:/lib:/usr/lib/aarch64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
    export TROS_DISTRO=humble
    export PATH=/opt/tros/humble/bin:/opt/ros/humble/bin:$PATH
}

cd "$APP" || exit 1
env_block

exec ros2 launch robot_bringup robot_nav_all.launch.py \
    enable_slam:=true \
    enable_nav:=false \
    enable_gamepad:=false \
    enable_rviz:=false \
    map_yaml:=$APP/maps/library.yaml \
    slam_config:=$APP/config/mapper_params_online_async.yaml \
    max_linear_x:=0.45 \
    max_angular_z:=0.9