#!/usr/bin/env python3
"""把编码器脉冲数转换成轮子速度 m/s"""

import math

# ============ 你和 STM32 队友必须对齐的参数 ============
# 轮径 97mm = 0.097m
WHEEL_DIAMETER = 0.097
WHEEL_CIRCUMFERENCE = math.pi * WHEEL_DIAMETER  # 周长 = 0.3047m

# TODO: 拿到后填这里（让 STM32 队友告诉你）
# 每转一圈编码器发出多少个脉冲
TICKS_PER_REV = 1440  # 例如: 390, 600, 1320 等
class EncoderVelocity:
    """
    功能：输入当前时刻的四个轮子累计脉冲数，输出四个轮子当前速度 m/s。
    
    原理：
      速度 = (当前脉冲数 - 上次脉冲数) / 每转脉冲数 × 轮子周长 / 时间间隔
    """

    def __init__(self):
        # 存储上一次收到的数据，第一次收到时会初始化
        self.prev_fl = None
        self.prev_fr = None
        self.prev_rl = None
        self.prev_rr = None
        self.prev_time_ms = None  # 上一次时间戳

    def update(self, timestamp_ms, fl, rl, fr, rr):
        """
        输入参数（从 STM32 的 ENCODER 帧解出来）：
          timestamp_ms : STM32 的时间戳，单位毫秒
          fl : Front Left  左前轮累计脉冲
          rl : Rear Left   左后轮累计脉冲
          fr : Front Right 右前轮累计脉冲
          rr : Rear Right  右后轮累计脉冲
          
        输出：(v_fl, v_fr, v_rl, v_rr)，每个单位是 m/s
        """
        
        # 第一次调用：没有上一次数据，记录当前值，返回 0
        if self.prev_time_ms is None:
            self.prev_fl = fl
            self.prev_fr = fr
            self.prev_rl = rl
            self.prev_rr = rr
            self.prev_time_ms = timestamp_ms
            return (0.0, 0.0, 0.0, 0.0)

        # 计算时间间隔 dt（秒）
        dt = (timestamp_ms - self.prev_time_ms) / 1000.0  # 毫秒→秒
        if dt <= 0.001:  # 小于1毫秒的数据太碎，丢弃
            return (0.0, 0.0, 0.0, 0.0)

        # 计算脉冲增量：当前值 - 上次值
        # int32 天然支持环绕溢出，直接相减即可
        d_fl = fl - self.prev_fl
        d_fr = fr - self.prev_fr
        d_rl = rl - self.prev_rl
        d_rr = rr - self.prev_rr

        # TODO: 拿到 TICKS_PER_REV 后取消下面三行注释
        # v_fl = d_fl / TICKS_PER_REV * WHEEL_CIRCUMFERENCE / dt
        # v_fr = d_fr / TICKS_PER_REV * WHEEL_CIRCUMFERENCE / dt
        # v_rl = d_rl / TICKS_PER_REV * WHEEL_CIRCUMFERENCE / dt
        # v_rr = d_rr / TICKS_PER_REV * WHEEL_CIRCUMFERENCE / dt

        # 临时先用 0，等 TICKS_PER_REV 拿到后替换上面三行
        v_fl = d_fl / TICKS_PER_REV * WHEEL_CIRCUMFERENCE / dt
        v_fr = d_fr / TICKS_PER_REV * WHEEL_CIRCUMFERENCE / dt
        v_rl = d_rl / TICKS_PER_REV * WHEEL_CIRCUMFERENCE / dt
        v_rr = d_rr / TICKS_PER_REV * WHEEL_CIRCUMFERENCE / dt

        # 更新存储
        self.prev_fl = fl
        self.prev_fr = fr
        self.prev_rl = rl
        self.prev_rr = rr
        self.prev_time_ms = timestamp_ms

        return (v_fl, v_fr, v_rl, v_rr)