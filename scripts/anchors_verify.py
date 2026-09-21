#!/usr/bin/env python3
"""anchors_verify.py —— 校验 anchors 提取结果: 打印每个锚点邻域的真实栅格。

用途: 确认锚点(障碍质心)附近的占据情况, 并据此计算"停靠点"——
      导航目标不能直接落在障碍上, 否则 A* 会判定 goal in obstacle。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obstacle_anchor import load_pgm, load_yaml  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    cfg = load_yaml(os.path.join(ROOT, 'maps/room.yaml'))
    img, w, h, mv = load_pgm(os.path.join(ROOT, 'maps/room.pgm'))
    occ = img < 89
    with open(os.path.join(ROOT, 'maps/bookmarks.json'), encoding='utf-8') as f:
        bm = json.load(f)

    res = cfg['resolution']
    for name, b in bm['books'].items():
        c0 = int(round(b['pixel'][0]))
        r0 = int(round(b['pixel'][1]))
        print(f'--- 《{name}》 centroid pixel(row={r0}, col={c0})  '
              f'world=({b["x"]:+.3f},{b["y"]:+.3f}) ---')
        for r in range(r0 - 5, r0 + 6):
            line = ''.join('#' if occ[r, c] else '.' for c in range(c0 - 6, c0 + 7))
            tag = ' <== 质心' if r == r0 else ''
            print(f'  {r:3d} {line}{tag}')
        print()

    # 站位数分布: 每个锚点周围 0.1~1.0m 环带内有多少空闲格
    import numpy as np
    print('=' * 60)
    print('各锚点周边空闲格统计(半径 0.3/0.5/0.7/1.0 m 环带):')
    for name, b in bm['books'].items():
        c0 = int(round(b['pixel'][0]))
        r0 = int(round(b['pixel'][1]))
        out = []
        for rad_m in (0.3, 0.5, 0.7, 1.0):
            rp = int(round(rad_m / res))
            sub = occ[max(0, r0 - rp):r0 + rp + 1,
                      max(0, c0 - rp):c0 + rp + 1]
            out.append(f'{rad_m}m:{int((~sub).sum())}')
        print(f'  《{name}》: ' + '  '.join(out))


if __name__ == '__main__':
    main()
