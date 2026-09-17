#!/bin/bash
# run_test.sh — 一键测试 stm32_bridge 全链路（模拟 STM32）
#
# 用法（在 RDK Studio 终端）：
#   bash /home/sunrise/robot_ws/scripts/run_test.sh
#
# 它会自动：
#   1. 启动 fake_stm.py 模拟 STM32（写 /tmp/fake_port.txt）
#   2. 读取模拟串口地址
#   3. 启动 stm32_bridge_node 并指向该地址
#   4. 验证 /odom 和 /tf
# 全部完成后自动清理进程。

set -u

echo "===== 1. 清理旧进程 ====="
pkill -9 -f fake_stm.py 2>/dev/null
pkill -9 -f stm32_bridge_node 2>/dev/null
sleep 1

echo "===== 2. 启动模拟 STM32 ====="
python3 -u /home/sunrise/robot_ws/scripts/fake_stm.py > /tmp/fake_log.txt 2>&1 &
FAKE_PID=$!
sleep 2

SLAVE=$(cat /tmp/fake_port.txt 2>/dev/null)
if [ -z "$SLAVE" ]; then
    echo "[错误] 没读到模拟串口地址，看日志："
    cat /tmp/fake_log.txt
    exit 1
fi
echo "模拟串口: $SLAVE"

echo "===== 3. 启动 stm32_bridge 节点 ====="
source /opt/ros/humble/setup.bash >/dev/null 2>&1
source /home/sunrise/robot_ws/install/setup.bash >/dev/null 2>&1

ros2 run stm32_bridge stm32_bridge_node --ros-args -p port:="$SLAVE" > /tmp/bridge_log.txt 2>&1 &
BRIDGE_PID=$!
sleep 6

echo "===== 4. 节点接收日志（前3条） ====="
grep "odom:" /tmp/bridge_log.txt | head -3

echo "===== 5. /odom 话题 ====="
timeout 5 ros2 topic echo /odom --once 2>&1 | head -12

echo "===== 6. /tf 变换 ====="
timeout 5 ros2 topic echo /tf --once 2>&1 | head -8

echo "===== 7. /odom 频率 ====="
timeout 7 ros2 topic hz /odom 2>&1 | head -2

echo "===== 8. 清理 ====="
kill -9 $FAKE_PID $BRIDGE_PID 2>/dev/null
pkill -9 -f fake_stm.py 2>/dev/null
pkill -9 -f stm32_bridge_node 2>/dev/null
echo "===== 测试结束 ====="