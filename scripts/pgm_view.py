#!/usr/bin/env python3
"""pgm_view.py <map.pgm> [ASCII列数] — 直接看保存下来的地图文件（不用起 ROS/SLAM）

做三件事：
  1. 打印尺寸、分辨率、真实世界范围、占用/空闲/未知统计
  2. 打印 ASCII 预览（# 障碍、. 空闲、空格未知；上=+y）
  3. 在同目录生成同名 .png，方便用看图软件直接打开

nav2 约定：0=障碍(黑) 254=空闲(白) 205=未知(灰)
"""
import os
import sys


def read_pgm(path):
    """读 P5 二进制 PGM（跳过 # 注释），返回 (宽, 高, maxval, 像素bytes)。"""
    with open(path, 'rb') as fh:
        data = fh.read()
    # 解析 header
    pos = 0
    tokens = []
    while len(tokens) < 4:
        # 跳空白与注释
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b'#':
            while pos < len(data) and data[pos:pos + 1] != b'\n':
                pos += 1
            continue
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        tokens.append(data[start:pos])
    pos += 1  # header 后一个空白
    magic, w, h, maxval = tokens[0], int(tokens[1]), int(tokens[2]), int(tokens[3])
    if magic != b'P5':
        raise ValueError(f'只支持 P5 PGM，收到 {magic!r}')
    return w, h, maxval, data[pos:pos + w * h]


def yaml_resolution(pgm_path):
    yml = os.path.splitext(pgm_path)[0] + '.yaml'
    if not os.path.exists(yml):
        return None, None
    res, origin = None, None
    for line in open(yml):
        line = line.strip()
        if line.startswith('resolution:'):
            res = float(line.split(':', 1)[1].strip())
        elif line.startswith('origin:'):
            origin = line.split(':', 1)[1].strip().strip('[]')
    return res, origin


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 88

    w, h, _maxv, px = read_pgm(path)
    res, origin = yaml_resolution(path)

    print(f'文件: {path}')
    print(f'像素: {w} x {h}', end='')
    if res:
        print(f'   分辨率 {res} m/px   实际范围 {w * res:.2f} m x {h * res:.2f} m'
              f'   origin=[{origin}]')
    else:
        print('   （同目录没有 .yaml，无法换算米）')

    occ = sum(1 for b in px if b < 100)
    fre = sum(1 for b in px if b > 240)
    unk = len(px) - occ - fre
    print(f'栅格: 障碍 {occ}   空闲 {fre}   未知 {unk}   合计 {len(px)}')
    if res and occ:
        print(f'障碍覆盖面积 ≈ {occ * res * res:.2f} m²，已探索面积 ≈ {(occ + fre) * res * res:.2f} m²')

    # ASCII 预览（PGM 第 0 行是最上方，对应 +y）
    step = max(1, w // cols)
    print(f'-- ASCII 预览（每字符 {step} px ≈ {step * (res or 1):.2f} m，上=+y）--')
    for y0 in range(0, h, step):
        line = []
        for x0 in range(0, w, step):
            block = [px[y * w + x]
                     for y in range(y0, min(h, y0 + step))
                     for x in range(x0, min(w, x0 + step))]
            if any(b < 100 for b in block):
                line.append('#')
            elif all(b > 240 for b in block):
                line.append('.')
            else:
                line.append(' ')
        print(''.join(line))

    # 顺带生成 PNG
    png = os.path.splitext(path)[0] + '.png'
    try:
        from PIL import Image
        Image.open(path).save(png)
        print(f'已生成图片: {png}')
    except Exception as exc:  # noqa: BLE001
        print(f'PNG 生成跳过（{exc}）')
    return 0


if __name__ == '__main__':
    sys.exit(main())