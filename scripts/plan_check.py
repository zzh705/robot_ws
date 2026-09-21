#!/usr/bin/env python3
"""plan_check.py —— 用导航栈里**真正的 A*** 验证 4 个书位停靠点可达。

为什么需要它
------------
停靠点是"书位障碍质心 + 净空"算出来的候选点。必须确认在当前膨胀口径下
A* 真能规划到它 —— 否则地图点击 / 语音找书都会**静默失败**
(global_planner 只会 warn('A* failed') 然后什么都不做)。

做法
----
  1. 从 maps/room.pgm 建占据栅格(map_server trinary 口径)
  2. 按 global_planner 的 inflation_radius 做同样的圆盘膨胀
  3. 直接 import 导航栈里的 AStar8, 对每个停靠点跑搜索
  4. 起点抽样若干"房间内空闲格", 模拟小车随机初始位置

用法(需要 ROS 环境, 因为要 import 导航节点):
    source /opt/tros/humble/setup.bash
    python3 scripts/plan_check.py
"""

import json
import os
import sys

import numpy as np
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src/library_nav/library_nav'))

from obstacle_anchor import load_pgm, load_yaml          # noqa: E402
from global_planner_node import AStar8                   # noqa: E402

INFLATE_R = 0.28        # 必须与 nav.launch.py 的 inflation_radius 一致
OCC_THRESH = 0.65       # room.yaml 的 occupied_thresh
FREE_THRESH = 0.25      # room.yaml 的 free_thresh
OCC_GRID_THR = 60       # global_planner 的 occupancy_threshold
N_STARTS = 12           # 抽样多少个起点


def build_occ_grid(pgm, maxval, occ_thresh, free_thresh, grid_thr):
    """按 map_server 的 trinary 口径把 PGM 转成 OccupancyGrid 数值, 再二值化。

    map_server: occ = (255 - pixel)/255  (negate=0)
      occ > occ_thresh        -> 100 (占据)
      occ < free_thresh       -> 0   (空闲)
      其余(含未知 205)         -> -1
    global_planner 再取 value >= grid_thr 作为障碍 —— -1 不算障碍。
    """
    p = pgm.astype(np.float64) / float(maxval)
    occ = 1.0 - p
    value = np.full(occ.shape, -1, dtype=np.int16)
    value[occ > occ_thresh] = 100
    value[occ < free_thresh] = 0
    return (value >= grid_thr).astype(np.uint8)


def inflate(occ, radius_px):
    rr, cc = np.mgrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
    disk = np.zeros((2 * radius_px + 1, 2 * radius_px + 1))
    disk[rr * rr + cc * cc <= radius_px * radius_px] = 1
    return ndimage.binary_dilation(occ.astype(bool), structure=disk).astype(np.uint8)


def main():
    cfg = load_yaml(os.path.join(ROOT, 'maps/room.yaml'))
    img, w, h, maxval = load_pgm(os.path.join(ROOT, 'maps/room.pgm'))
    with open(os.path.join(ROOT, 'maps/bookmarks.json'), encoding='utf-8') as f:
        bm = json.load(f)

    res = cfg['resolution']
    origin = cfg['origin']

    raw_occ = build_occ_grid(img, maxval, OCC_THRESH, FREE_THRESH, OCC_GRID_THR)
    inflate_px = max(1, int(round(INFLATE_R / res)))
    inflated = inflate(raw_occ, inflate_px)
    astar = AStar8(inflated, res, (origin[0], origin[1]))

    print(f'地图 {w}x{h} res={res} inflate={INFLATE_R}m({inflate_px}px)  '
          f'占据 {int(raw_occ.sum())}px -> 膨胀后 {int(inflated.sum())}px')

    # ---- 1. 停靠点自身是否落在可通行格 ----
    print('\n[1] 停靠点在膨胀图上的可通行性:')
    all_free = True
    for name, b in bm['books'].items():
        gx, gy = b['goal_x'], b['goal_y']
        gr, gc = astar.world_to_grid(gx, gy)
        ok = astar.is_free(gr, gc)
        all_free = all_free and ok
        print(f'  《{name}》 goal=({gx:+.3f},{gy:+.3f}) '
              f'grid(r={gr},c={gc}) 可通行={ok}')
    print(f'  => 全部可通行: {all_free}')

    # ---- 2. 抽样起点, 逐个目标跑真实 A* ----
    # 起点必须与目标落在**同一块**自由连通区。
    # 整图乱采样会把"屋外缓冲空间"也抽进来 —— 那里被外墙隔开,
    # 必然 no path, 那是采样错误, 不能当作停靠点不可达。
    free_lbl, free_n = ndimage.label(
        inflated == 0, structure=np.ones((3, 3), dtype=bool))
    goal_labels = []
    for name, b in bm['books'].items():
        if b.get('goal_x') is None or b.get('goal_y') is None:
            print(f'  !! 《{name}》没有停靠点, 请先重跑 obstacle_anchor.py --write')
            return 2
        gr, gc = astar.world_to_grid(b['goal_x'], b['goal_y'])
        goal_labels.append(int(free_lbl[gr, gc]))
    print(f'\n[2] 目标的自由连通区: '
          f'{dict(zip(bm["books"], goal_labels))}')
    room_label = max(set(goal_labels), key=goal_labels.count)
    if len(set(goal_labels)) != 1:
        print(f'  警告: 目标不在同一连通区, 取多数派 region={room_label}')
    free_cells = np.argwhere(free_lbl == room_label)
    print(f'  房间自由区 region={room_label} 共 {len(free_cells)} 格')
    rng = np.random.default_rng(20260921)
    idx = rng.choice(len(free_cells), size=min(N_STARTS, len(free_cells)),
                     replace=False)
    starts = []
    for r, c in free_cells[idx]:
        x, y = astar.grid_to_world(int(r), int(c))
        starts.append((round(x, 3), round(y, 3)))
    print(f'\n[3] 抽样 {len(starts)} 个起点(模拟小车随机初始位置):')
    print('  ' + ', '.join(f'({x:+.2f},{y:+.2f})' for x, y in starts))

    print('\n[4] 真实 A* 规划结果:')
    total_fail = 0
    for name, b in bm['books'].items():
        goal = (b['goal_x'], b['goal_y'])
        ok_n, fail_n, lens = 0, 0, []
        for s in starts:
            path = astar.search(s, goal)
            if path is None:
                fail_n += 1
            else:
                ok_n += 1
                L = sum(
                    ((path[i + 1][0] - path[i][0]) ** 2
                     + (path[i + 1][1] - path[i][1]) ** 2) ** 0.5
                    for i in range(len(path) - 1))
                lens.append(L)
        total_fail += fail_n
        avg = (sum(lens) / len(lens)) if lens else 0.0
        flag = 'OK ' if fail_n == 0 else 'FAIL'
        print(f'  [{flag}] 《{name}》 成功 {ok_n}/{len(starts)}  '
              f'平均路径长 {avg:.2f} m')

    print(f'\n结论: {"全部可达" if total_fail == 0 else f"存在 {total_fail} 次规划失败"}')
    return 0 if total_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
