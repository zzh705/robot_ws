#!/usr/bin/env python3
"""obstacle_anchor.py —— 从 SLAM 地图里提取"障碍物锚点"。

背景
----
地图 room.pgm 是一间矩形房间: 一堵外墙 + 内部 4 个独立障碍物。
这 4 个障碍物被当作"书位"锚点使用(地图点击 / 语音找书都指向它们)。

做法
----
对占据栅格做连通域分析:
  * 与图像边界相连的最大连通域  -> 外墙(丢弃)
  * 其余面积 >= --min-area 的连通域 -> 内部障碍物(保留)
取每个障碍物连通域的几何中心(质心), 换算成 ROS map 系世界坐标。

坐标换算(ROS map_server 约定)
-----------------------------
yaml 里的 origin 是地图**左下角**像素的世界位姿(x, y, yaw)。
PGM 第 0 行是图像**顶部**, 对应世界坐标 y 最大的一侧。因此:

    世界 x = origin_x + (col + 0.5) * resolution
    世界 y = origin_y + (H - 1 - row + 0.5) * resolution

反算(给 GUI 用):

    col = (x - origin_x) / resolution - 0.5
    row = H - 1 - ((y - origin_y) / resolution - 0.5)

停靠点(导航目标)
----------------
障碍质心不能直接当导航目标:
  1) SLAM 里障碍物常呈**空心轮廓**(桌椅/书架只被看到外沿), 质心落在空腔里;
  2) 即使质心是实心, 也仍在障碍上 —— A* 会判 `goal in obstacle` 而拒绝规划;
  3) 膨胀后质心可能被一圈障碍环抱, 形成与房间主连通区分离的"孤岛"。
因此对每个锚点再算一个**净空足够**且**在主连通区**内的停靠点, 作为
真正的导航目标; 原质心保留为"书位"语义坐标, 用于 GUI 标注。

用法
----
    python3 scripts/obstacle_anchor.py                  # 只打印
    python3 scripts/obstacle_anchor.py --write          # 打印并写 maps/bookmarks.json
    python3 scripts/obstacle_anchor.py --min-area 12    # 调最小面积阈值(像素)
    python3 scripts/obstacle_anchor.py --map maps/straight
"""

import argparse
import json
import math
import os

import numpy as np
from scipy import ndimage

# 4 个锚点的默认书名(与位置一一对应, 顺序: 左上/右上/右下/左下)
DEFAULT_BOOKS = ['红星照耀中国', '活着', '三体', '平凡的世界']


# ============================================================
# 读取 PGM(P5 二进制) + YAML
# ============================================================

def load_pgm(path):
    """解析 P5 PGM, 返回 (image[H,W], width, height, maxval)"""
    with open(path, 'rb') as f:
        raw = f.read()

    tokens = []
    i = 0
    while len(tokens) < 4:
        while i < len(raw) and raw[i:i + 1].isspace():
            i += 1
        if raw[i:i + 1] == b'#':
            while i < len(raw) and raw[i:i + 1] != b'\n':
                i += 1
            continue
        j = i
        while j < len(raw) and not raw[j:j + 1].isspace():
            j += 1
        tokens.append(raw[i:j])
        i = j
    i += 1

    magic = tokens[0].decode()
    if magic != 'P5':
        raise ValueError(f'只支持 P5 二进制 PGM, 实际是 {magic}')

    w, h, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
    img = np.frombuffer(raw[i:i + w * h], dtype=np.uint8).reshape(h, w)
    return img, w, h, maxval


def load_yaml(path):
    """极简 YAML 读取: 只认 room.yaml 里用到的几个 key, 避免依赖 pyyaml"""
    cfg = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or ':' not in line:
                continue
            key, _, val = line.partition(':')
            key, val = key.strip(), val.strip()

            if key == 'image':
                cfg['image'] = val
            elif key == 'resolution':
                cfg['resolution'] = float(val)
            elif key == 'origin':
                nums = val.strip('[]').split(',')
                cfg['origin'] = [float(n) for n in nums]
            elif key == 'negate':
                cfg['negate'] = int(val)
            elif key == 'occupied_thresh':
                cfg['occupied_thresh'] = float(val)
            elif key == 'free_thresh':
                cfg['free_thresh'] = float(val)

    for required in ('image', 'resolution', 'origin'):
        if required not in cfg:
            raise ValueError(f'yaml 缺少字段 {required}: {path}')
    return cfg


# ============================================================
# 坐标换算
# ============================================================

def pixel_to_world(row, col, res, origin, height):
    x = origin[0] + (col + 0.5) * res
    y = origin[1] + (height - 1 - row + 0.5) * res
    return x, y


def world_to_pixel(x, y, res, origin, height):
    col = (x - origin[0]) / res - 0.5
    row = height - 1 - ((y - origin[1]) / res - 0.5)
    return row, col


# ============================================================
# 停靠点: 障碍质心不能直接当导航目标
# ============================================================

def find_standoff(clearance, row_c, col_c, res, height, width,
                  need_clear, allowed=None,
                  r_min=0.45, r_max=1.3):
    """在锚点周围环带里找一个"可停靠点"。

    挑选规则:
      * 与锚点距离 ∈ [r_min, r_max] m  (既不在障碍内部, 又不离书位太远)
      * 该格到最近障碍的净空 >= need_clear (保证在膨胀层之外, A* 才认它可走)
      * allowed[r,c] 为真 —— 即与"书位所在的那块自由区"连通
        (否则 A* 会判 no path: 例如被膨胀层环抱成一圈的"孤岛")
      * 满足者中取净空最大的一格 —— 净空大 = 周围开阔, 机器人有腾挪余地

    返回 (row, col, clear_m) 或 None。
    """
    rp_max = int(math.ceil(r_max / res))
    r0, c0 = int(round(row_c)), int(round(col_c))
    best = None
    for r in range(max(0, r0 - rp_max), min(height, r0 + rp_max + 1)):
        for c in range(max(0, c0 - rp_max), min(width, c0 + rp_max + 1)):
            d = math.hypot(r - row_c, c - col_c) * res
            if d < r_min or d > r_max:
                continue
            cl = float(clearance[r, c])
            if cl < need_clear:
                continue
            if allowed is not None and not allowed[r, c]:
                continue
            if best is None or cl > best[2]:
                best = (r, c, cl)
    return best


def dominant_free_label(free_lbl, row_c, col_c, radius_px):
    """取锚点周边 radius_px 内出现最多的空闲连通域编号。

    这就是"书位所在的那块自由区"(房间内部)。**不能**用全局最大块:
    房间外墙把自由空间切成"屋内/屋外"两块, 屋外缓冲空间往往更大,
    全局最大块反而是屋外 —— 据此挑停靠点会全部落空。
    """
    h, w = free_lbl.shape
    r0, c0 = int(round(row_c)), int(round(col_c))
    sub = free_lbl[max(0, r0 - radius_px):min(h, r0 + radius_px + 1),
                   max(0, c0 - radius_px):min(w, c0 + radius_px + 1)]
    vals, counts = np.unique(sub[sub > 0], return_counts=True)
    if len(vals) == 0:
        return 0
    return int(vals[int(np.argmax(counts))])


# ============================================================
# 主流程
# ============================================================

def find_anchors(map_base, min_area=8, inflate_r=0.28):
    """返回 (anchors, meta)。anchors 每项: dict(row, col, x, y, area)"""
    yaml_path = map_base + '.yaml'
    cfg = load_yaml(yaml_path)

    pgm_path = os.path.join(os.path.dirname(yaml_path), cfg['image'])
    img, w, h, maxval = load_pgm(pgm_path)

    res = cfg['resolution']
    origin = cfg['origin']
    negate = cfg.get('negate', 0)
    occ_thresh = cfg.get('occupied_thresh', 0.65)

    p = img.astype(np.float64) / float(maxval)
    if negate:
        p = 1.0 - p
    occupancy = 1.0 - p
    occ = occupancy >= occ_thresh

    # 与 global_planner 的膨胀口径对齐
    inflate_px = max(1, int(round(inflate_r / res)))
    need_clear = (inflate_px + 1) * res

    # 膨胀图(用于剔除孤岛)
    disk = np.zeros((2 * inflate_px + 1, 2 * inflate_px + 1))
    rr, cc = np.mgrid[-inflate_px:inflate_px + 1,
                      -inflate_px:inflate_px + 1]
    disk[rr * rr + cc * cc <= inflate_px * inflate_px] = 1
    occ_inflated = ndimage.binary_dilation(
        occ.astype(bool), structure=disk).astype(np.uint8)

    # 净空: 用来给每个锚点挑一个净空足够的"停靠点"
    clearance = ndimage.distance_transform_edt(~occ) * res

    # 空闲连通分量标记(膨胀图上), 逐锚点判定"书位所在的自由区"
    free_lbl, free_n = ndimage.label(
        occ_inflated == 0, structure=np.ones((3, 3), dtype=bool))
    # 探测半径: 够大才能盖住锚点周围、又不至于跨到隔壁的独立空间
    probe_px = max(4, int(round(1.2 / res)))

    # 障碍物连通域(8 邻域, 与 A* 一致)
    structure = np.ones((3, 3), dtype=bool)
    labels, n = ndimage.label(occ, structure=structure)

    # 外墙识别: 用包围盒跨度(墙不一定贴到边界)
    areas = {lb: int((labels == lb).sum()) for lb in range(1, n + 1)}
    slices = ndimage.find_objects(labels)
    wall_labels = set()
    for lb in range(1, n + 1):
        sy, sx = slices[lb - 1]
        if sy is None or sx is None:
            continue
        if (sx.stop - sx.start) > 0.5 * w and (sy.stop - sy.start) > 0.5 * h:
            wall_labels.add(lb)

    anchors = []
    for lb in range(1, n + 1):
        if lb in wall_labels:
            continue
        area = areas[lb]
        if area < min_area:
            continue
        rows, cols = np.nonzero(labels == lb)
        row_c, col_c = float(rows.mean()), float(cols.mean())
        x, y = pixel_to_world(row_c, col_c, res, origin, h)

        room_label = dominant_free_label(free_lbl, row_c, col_c, probe_px)
        allowed = (free_lbl == room_label) if room_label > 0 else None
        stop = find_standoff(clearance, row_c, col_c, res, h, w,
                             need_clear, allowed=allowed)
        if stop is not None:
            srow, scol, sclear = stop[0], stop[1], stop[2]
            gx, gy = pixel_to_world(srow, scol, res, origin, h)
        else:
            srow = scol = None
            gx = gy = None
            sclear = 0.0

        anchors.append({
            'label': int(lb),
            'row': round(row_c, 2),
            'col': round(col_c, 2),
            'x': round(x, 3),
            'y': round(y, 3),
            'area': area,
            'bbox': [int(rows.min()), int(cols.min()),
                     int(rows.max()), int(cols.max())],
            'goal_x': round(gx, 3) if gx is not None else None,
            'goal_y': round(gy, 3) if gy is not None else None,
            'goal_pixel': [round(scol, 2), round(srow, 2)]
            if scol is not None else None,
            'goal_clearance': round(sclear, 3),
            'free_region': room_label,
        })

    meta = {
        'map': map_base,
        'image': cfg['image'],
        'width': w,
        'height': h,
        'resolution': res,
        'origin': origin,
        'occupied_px': int(occ.sum()),
        'components': n,
        'wall_labels': sorted(wall_labels),
        'wall_area': sum(areas[lb] for lb in wall_labels),
        'inflate_radius': inflate_r,
        'inflate_px': inflate_px,
        'need_clearance': round(need_clear, 3),
    }
    return anchors, meta


def order_anchors(anchors):
    """按 (上/下, 左/右) 排序: 左上 → 右上 → 右下 → 左下。"""
    if not anchors:
        return []
    rows = np.array([a['row'] for a in anchors])
    mid = rows.mean()
    upper = sorted([a for a in anchors if a['row'] < mid],
                   key=lambda a: a['col'])
    lower = sorted([a for a in anchors if a['row'] >= mid],
                   key=lambda a: a['col'])
    ordered = []
    if upper:
        ordered.append(upper[0])
    if len(upper) > 1:
        ordered.append(upper[-1])
    if len(lower) > 1:
        ordered.append(lower[-1])
    if lower:
        ordered.append(lower[0])
    if len(ordered) != len(anchors):
        ordered = sorted(anchors, key=lambda a: (a['row'], a['col']))
    return ordered


def main():
    ap = argparse.ArgumentParser(description='从 SLAM 地图提取障碍物锚点')
    ap.add_argument('--map', default='maps/room',
                    help='地图基准路径(不含扩展名), 默认 maps/room')
    ap.add_argument('--write', action='store_true',
                    help='把结果写入 <map 同目录>/bookmarks.json')
    ap.add_argument('--min-area', type=int, default=8,
                    help='连通域最小面积(像素), 默认 8')
    ap.add_argument('--inflate', type=float, default=0.28,
                    help='障碍膨胀半径(m), 需与 global_planner 的 '
                         'inflation_radius 一致, 默认 0.28')
    args = ap.parse_args()

    map_base = args.map
    if not os.path.isabs(map_base):
        map_base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            map_base)

    anchors, meta = find_anchors(map_base, args.min_area, args.inflate)

    print('=' * 66)
    print(f"地图   : {meta['image']}  {meta['width']}x{meta['height']} "
          f"@ {meta['resolution']} m/px")
    print(f"origin : {meta['origin']}")
    print(f"占据像素: {meta['occupied_px']}   连通域: {meta['components']} "
          f"(外墙 {meta['wall_labels']} 共 {meta['wall_area']} px, 已排除)")
    print(f"膨胀口径: radius={meta['inflate_radius']}m "
          f"({meta['inflate_px']}px) -> 停靠点净空需 >= {meta['need_clearance']}m")
    print('=' * 66)
    print(f"检出内部障碍物 {len(anchors)} 个:")
    for a in anchors:
        print(f"  label={a['label']:3d}  area={a['area']:4d}px  "
              f"pixel(row={a['row']:7.2f}, col={a['col']:7.2f})  "
              f"-> 书位(x={a['x']:+.3f}, y={a['y']:+.3f})  "
              f"停靠点(x={a['goal_x']}, y={a['goal_y']}) "
              f"净空={a['goal_clearance']}m")

    ordered = order_anchors(anchors)
    print('-' * 66)
    print('按 左上/右上/右下/左下 排序并配对书名:')
    books = {}
    for name, a in zip(DEFAULT_BOOKS, ordered):
        books[name] = {
            'x': a['x'],
            'y': a['y'],
            'pixel': [round(a['col'], 2), round(a['row'], 2)],
            'area': a['area'],
            'goal_x': a['goal_x'],
            'goal_y': a['goal_y'],
            'goal_pixel': a['goal_pixel'],
            'goal_clearance': a['goal_clearance'],
        }
        print(f"  《{name}》  书位(x={a['x']:+.3f}, y={a['y']:+.3f})  "
              f"pixel(col={a['col']:.1f}, row={a['row']:.1f})  "
              f"-> 停靠点(x={a['goal_x']}, y={a['goal_y']})")

    if args.write:
        out = {
            'map': meta['map'],
            'image': meta['image'],
            'resolution': meta['resolution'],
            'origin': meta['origin'],
            'width': meta['width'],
            'height': meta['height'],
            'inflate_radius': meta['inflate_radius'],
            'books': books,
        }
        out_path = os.path.join(os.path.dirname(map_base), 'bookmarks.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print('-' * 66)
        print(f'已写入 {out_path}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())