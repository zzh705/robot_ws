#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_buttons.py — 只在按键按下/松开时打印一行，不受操作时间限制。

用法: python3 probe_buttons.py [秒数]      # 默认 120

测试方法: 依次按下并松开每一个键（含 LB/RB/LT/RT/方向键），脚本会逐个报出编号。
"""
import sys
import time

import pygame

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0

BUTTON_NAMES = {
    0: 'A(下)', 1: 'B(右)', 2: 'X(左)', 3: 'Y(上)',
    4: 'LB', 5: 'RB', 6: 'LT', 7: 'RT',
    8: 'Back/Select', 9: 'Start', 10: 'L3', 11: 'R3',
    12: 'Home', 13: 'Capture', 14: '?', 15: '?',
}


def main():
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("NO_GAMEPAD", flush=True)
        return
    j = pygame.joystick.Joystick(0)
    j.init()
    print(f"# 手柄: {j.get_name()}  buttons={j.get_numbuttons()} "
          f"axes={j.get_numaxes()}  运行 {SECS:.0f}s", flush=True)
    print("# 请依次按下并松开每一个键 ->", flush=True)
    t_end = time.time() + SECS
    held = set()
    while time.time() < t_end:
        pygame.event.pump()
        for ev in pygame.event.get():
            if ev.type == pygame.JOYBUTTONDOWN:
                held.add(ev.button)
                print(f'  DOWN 按钮{ev.button:2d} = '
                      f'{BUTTON_NAMES.get(ev.button, "?"):12s} 当前按住: {sorted(held)}',
                      flush=True)
            elif ev.type == pygame.JOYBUTTONUP:
                held.discard(ev.button)
                print(f'  UP   按钮{ev.button:2d} = '
                      f'{BUTTON_NAMES.get(ev.button, "?"):12s} 剩余: {sorted(held)}',
                      flush=True)
            elif ev.type == pygame.JOYHATMOTION:
                print(f'  HAT  hat{ev.hat} 方向={ev.value}', flush=True)
            elif ev.type == pygame.JOYAXISMOTION:
                print(f'  AXIS 轴{ev.axis} = {ev.value:+.3f}', flush=True)
        time.sleep(0.02)
    print('# 结束', flush=True)
    pygame.quit()


if __name__ == '__main__':
    main()