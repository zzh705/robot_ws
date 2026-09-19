# robot_ws 图书馆机器人

ROS2 Humble 工作区:SLAM 建图 + A*/DWA 导航 + STM32 编码器里程计桥 + 语音 GUI。

## 目录
- `src/library_nav/` — 自研导航栈(global_planner / local_planner_dwa / pid_controller / goal_bridge)
- `src/stm32_bridge/` — STM32 串口 ↔ ROS 桥(协议/驱动/里程计)
- `src/robot_bringup/` — 一键启动(核心链路 + rviz + 雷达看护)
- `src/rplidar_ros/` — 雷达驱动
- `library_gui/` — 上位机 PySide6 界面(图书检索/语音/控制)

## 启动全栈
```bash
ros2 launch robot_bringup robot.launch.py
```