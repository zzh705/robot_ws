#!/bin/bash
# ============================================================
# save_map.sh — 保存 slam_toolbox 已建地图到 maps/ 目录
#
# 用法:
#   bash save_map.sh [地图名]
#   例:  bash save_map.sh library   →  maps/library.yaml / library.pgm
# ============================================================

export HOME=/home/sunrise
export ROS_DOMAIN_ID=0
source /opt/ros/humble/setup.bash
source /home/sunrise/robot_ws/install/setup.bash
cd /home/sunrise/robot_ws

MAP_NAME="${1:-library}"
MAP_DIR="/home/sunrise/robot_ws/maps"
mkdir -p "${MAP_DIR}"

echo "=== 查找 slam_toolbox 服务 ==="
SVC=$(timeout 8 ros2 service list 2>/dev/null | grep -x "/slam_toolbox/save_map" | head -1)
echo "服务: ${SVC}"

if [ -z "${SVC}" ]; then
  echo "!! 没找到 save_map 服务 —— SLAM 没在跑?"
  echo "!! 检查: timeout 10 ros2 node list | grep slam"
  exit 1
fi

# slam_toolbox 的 SaveMap 服务路径通常是 /slam_toolbox/save_map
echo "=== 保存地图到 ${MAP_DIR}/${MAP_NAME}.yaml ==="
# 注意：SaveMap.name 是 std_msgs/String，必须包一层 {data: '...'}；
# 写成 {name: '...'} 会报 "expected to be a dictionary but is a str"
timeout 20 ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap \
  "{name: {data: '${MAP_DIR}/${MAP_NAME}'}}" 2>&1

echo ""
echo "=== 结果 ==="
ls -la "${MAP_DIR}/" 2>&1

# slam_toolbox 的 save_map 需要在 slam_toolbox 线程内部写文件;
# 若上面失败, 备胎方案: 用 nav2_map_server 的 map_saver_cli
if [ ! -f "${MAP_DIR}/${MAP_NAME}.pgm" ]; then
  echo "== 尝试备胎: map_saver_cli =="
  timeout 20 ros2 run nav2_map_server map_saver_cli -f "${MAP_DIR}/${MAP_NAME}" --ros-args \
    -p map_topic:=/map 2>&1 || echo "map_saver_cli 失败(可能没装 nav2)"
fi

echo "=== 完成 ==="
# 额外存一份位姿图：以后想继续建图 / 手动改回环都靠它
echo "=== 保存位姿图 ${MAP_DIR}/${MAP_NAME}.posegraph ==="
timeout 25 ros2 service call /slam_toolbox/serialize_map slam_toolbox/srv/SerializePoseGraph \
  "{filename: '${MAP_DIR}/${MAP_NAME}'}" 2>&1 | tail -2

echo "=== 完成 ==="