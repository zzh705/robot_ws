#!/bin/bash
# start_file_cmd.sh —— 以 sunrise ROS 环境启动 file_cmd_vel 遥控
export HOME=/home/sunrise
export ROS_DOMAIN_ID=0
source /opt/ros/humble/setup.bash
source /home/sunrise/robot_ws/install/setup.bash
pkill -f file_cmd_vel.py 2>/dev/null
sleep 1
rm -f /home/sunrise/teleop_fifo /tmp/file_cmd.log /tmp/teleop_cmd
mkfifo -m 666 /home/sunrise/teleop_fifo
nohup python3 /home/sunrise/robot_ws/scripts/file_cmd_vel.py --cmd-file /home/sunrise/teleop_fifo > /tmp/file_cmd.log 2>&1 &
echo "STARTED_PID=$!"
sleep 3
echo "==LOG=="
cat /tmp/file_cmd.log 2>&1
echo "==ALIVE=="
pgrep -af file_cmd_vel.py | grep -v grep || echo NONE