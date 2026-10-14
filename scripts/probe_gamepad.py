#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_gamepad.py — 连续打印所有轴/键/帽的值，用来反推手柄映射。

用法:
    python3 probe_gamepad.py [秒数]      # 默认 20s
    python3 probe_gamepad.py 20 > /tmp/probe.log

操作指引（照着做一遍，每步约 3 秒）:
    1. 不动            -> 读静息值
    2. 左摇杆 往上     -> 找"前进"轴
    3. 左摇杆 往右     -> 找"横移"轴
    4. 右摇杆 往右     -> 找"旋转"轴
    5. 按 A / X / LB   -> 找按键编号
"""
import sys
import time

import pygame

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0


def main():
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("NO_GAMEPAD")
        return
    j = pygame.joystick.Joystick(0)
    j.init()
    print(f"# 手柄: {j.get_name()}  axes={j.get_numaxes()} "
          f"buttons={j.get_numbuttons()} hats={j.get_numhats()}", flush=True)
    print(f"{'t':>6} " + " ".join(f"ax{i:<7}" for i in range(j.get_numaxes()))
          + "  btns  hat0", flush=True)

    t_end = time.time() + SECS
    t0 = time.time()
    pressed = set()
    while time.time() < t_end:
        pygame.event.pump()
        for ev in pygame.event.get():
            if ev.type == pygame.JOYBUTTONDOWN:
                pressed.add(ev.button)
            elif ev.type == pygame.JOYBUTTONUP:
                pressed.discard(ev.button)
        ax = [j.get_axis(i) for i in range(j.get_numaxes())]
        hat = j.get_hat(0) if j.get_numhats() else (0, 0)
        print(f"{time.time() - t0:6.2f} "
              + " ".join(f"{v:+7.3f}  " for v in ax)
              + f" {sorted(pressed)}  {hat}", flush=True)
        time.sleep(0.05)
    pygame.quit()


if __name__ == '__main__':
    main()