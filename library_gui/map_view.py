"""map_view.py —— GUI "地图" 按钮对应的地图视图窗口。

做的事
-------
  * 加载 maps/room.pgm (灰度图) + maps/room.yaml (origin + resolution)
  * 在 QGraphicsView 里渲染地图, 4 个书位以彩色圆点 + 书名标注
  * 鼠标点击地图 -> 像素 -> map 坐标 -> robot_comm.send_goto_xy 派给板端
  * 启动 / 完成派单都有 TTS 播报反馈(走 hobot_tts 走不通就退化为 log)

依赖: PySide6(已装)。robot_comm 是同目录模块, 由 GUI.py 加载时设置 sys.path。

约束
----
  * 屏幕是 800x480, 地图窗口尽量紧凑: 默认尺寸 720x540, 可拖动
  * 不依赖 ROS: GUI 直接读 yaml/pgm, 坐标校验留给板端 goal_bridge 节点
"""
import os
import json

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget)

import robot_comm


# 4 个书位的颜色(顺时针 上/右/下/左, 与 order_anchors 输出顺序对齐)
BOOK_COLORS = [
    QColor('#E74C3C'),  # 红星照耀中国 - 红
    QColor('#F39C12'),  # 活着 - 橙
    QColor('#27AE60'),  # 三体 - 绿
    QColor('#2980B9'),  # 平凡的世界 - 蓝
]


def _load_map_bundle():
    """读 maps/room.yaml 和 bookmarks.json, 返回 (pgm_path, origin, res,
    width, height, books_dict)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(here, '..', 'maps', 'room.yaml')
    bm_path = os.path.join(here, '..', 'maps', 'bookmarks.json')
    with open(yaml_path, 'r', encoding='utf-8') as f:
        cfg = {}
        for line in f:
            line = line.strip()
            if line.startswith('#') or ':' not in line:
                continue
            k, _, v = line.partition(':')
            cfg[k.strip()] = v.strip()
    origin = [float(x) for x in cfg['origin'].strip('[]').split(',')[:2]]
    res = float(cfg['resolution'])
    pgm_path = os.path.join(os.path.dirname(yaml_path), cfg['image'])

    with open(bm_path, 'r', encoding='utf-8') as f:
        bm = json.load(f)

    return pgm_path, origin, res, pgm_path and pgm_path.endswith('.pgm'), bm


def _pgm_to_qimage(pgm_path):
    """读 P5 二进制 PGM 转 QImage。失败返回 None."""
    with open(pgm_path, 'rb') as f:
        raw = f.read()
    # 解析头部
    parts = []
    i = 0
    while len(parts) < 3:
        while i < len(raw) and raw[i:i + 1].isspace():
            i += 1
        if raw[i:i + 1] == b'#':
            while i < len(raw) and raw[i:i + 1] != b'\n':
                i += 1
            continue
        j = i
        while j < len(raw) and not raw[j:j + 1].isspace():
            j += 1
        parts.append(raw[i:j].decode())
        i = j
    w = int(parts[1].split()[0])
    h = int(parts[1].split()[1])
    maxval = int(parts[2])
    i += 1
    data = raw[i:i + w * h]
    img = QImage(data, w, h, w, QImage.Format_Grayscale8)
    return img.copy(), w, h


class MapViewWindow(QWidget):
    """地图视图窗口。"""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('🗺️ 图书馆地图 - 点击任意位置让机器人前往')
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setFixedSize(740, 620)

        # ---- 加载数据 ----
        try:
            pgm_path, self.origin, self.res, _, bm = _load_map_bundle()
            self.img, self.W, self.H = _pgm_to_qimage(pgm_path)
        except Exception as e:
            self.img = None
            self.origin = [-3.47, -3.82, 0.0]
            self.res = 0.05
            self.W = self.H = 0
            self.bm_error = f'加载地图失败: {e}'
            bm = {'books': {}}
        else:
            self.bm_error = None
        self.books = bm.get('books', {})
        self.book_list = list(self.books.items())  # 保持顺序

        # ---- 布局 ----
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.hint = QLabel(
            '🖱️ 单击地图任意位置 → 机器人前往该点 (map 系)\n'
            '🔴 圆点 = 4 个书位, 点击旁边按钮可一键前往'
        )
        self.hint.setStyleSheet('font-size:13px;color:#2F5D50;')
        root.addWidget(self.hint)

        # ---- 视图 ----
        self.view = QGraphicsView()
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setBackgroundBrush(QBrush(QColor('#F5F8F6')))
        self.scene = QGraphicsScene()
        self.view.setScene(self.scene)
        root.addWidget(self.view, stretch=1)

        # ---- 反馈区 ----
        self.feedback = QLabel(' ')
        self.feedback.setStyleSheet(
            'font-size:13px;color:#34495E;padding:4px;'
            'background:#EEF5EF;border-radius:8px;')
        self.feedback.setFixedHeight(30)
        root.addWidget(self.feedback)

        # ---- 一键派单按钮 ----
        btn_row = QHBoxLayout()
        for (name, info), color in zip(self.book_list, BOOK_COLORS):
            b = QPushButton(f'前往《{name}》')
            b.setFixedHeight(40)
            b.setStyleSheet(
                f'QPushButton{{background:white;color:#111827;'
                f'border:2px solid {color.name()};border-radius:10px;'
                f'font-size:14px;font-weight:700;}}'
                f'QPushButton:hover{{background:{color.name()};'
                f'color:white;}}'
            )
            b.clicked.connect(
                lambda checked=False, n=name, x=info['goal_x'],
                y=info['goal_y']: self._dispatch(n, x, y))
            btn_row.addWidget(b)
        root.addLayout(btn_row)

        self._render()

    # ============================================================
    # 渲染
    # ============================================================
    def _render(self):
        self.scene.clear()
        if self.bm_error:
            self.feedback.setText(self.bm_error)
            return

        # 地图图像(留 8px 内边距)
        pad = 12
        pix = QPixmap.fromImage(self.img)
        self.scene.addPixmap(pix).setPos(pad, pad)

        # 让 view 缩放到合适大小
        rect = QRectF(
            0, 0,
            self.W + 2 * pad, self.H + 2 * pad)
        self.scene.setSceneRect(rect)
        self.view.fitInView(rect, Qt.KeepAspectRatio)

        # 4 个书位标注
        for i, (name, info) in enumerate(self.book_list):
            color = BOOK_COLORS[i % len(BOOK_COLORS)]
            gx, gy = info['goal_x'], info['goal_y']
            # 像素坐标
            col = (gx - self.origin[0]) / self.res - 0.5
            row = self.H - 1 - ((gy - self.origin[1]) / self.res - 0.5)
            cx = col + pad
            cy = row + pad
            # 圆点
            r = 7
            self.scene.addEllipse(
                cx - r, cy - r, 2 * r, 2 * r,
                QPen(Qt.black, 1), QBrush(color))
            # 书名(标签), 偏移避免重叠
            label = self.scene.addText(f'《{name}》', QFont('', 9))
            label.setDefaultTextColor(QColor('black'))
            label.setPos(cx + r + 2, cy - r - 2)

        # 画一条 y 轴标注 (展示方向)
        # 上=地图里 y 大的方向(图像顶部)
        axis = self.scene.addText(
            '↑ +y (PGM 顶部 = map 世界 +y 方向)\n'
            f'origin=({self.origin[0]:.2f}, {self.origin[1]:.2f}) '
            f'resolution={self.res}m/px',
            QFont('', 8))
        axis.setDefaultTextColor(QColor('#34495E'))
        axis.setPos(pad, self.H + pad + 2)

    # ============================================================
    # 点击 → 派单
    # ============================================================
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.img is None:
            super().mousePressEvent(event)
            return
        # 把屏幕坐标映射到 scene
        sp = self.view.mapToScene(event.position().toPoint())
        pad = 12
        col = sp.x() - pad
        row = sp.y() - pad
        if not (0 <= col < self.W and 0 <= row < self.H):
            return
        x = self.origin[0] + (col + 0.5) * self.res
        y = self.origin[1] + (self.H - 1 - row + 0.5) * self.res
        self._dispatch('点击点', x, y)

    def _dispatch(self, name, x, y):
        ok, msg = robot_comm.send_goto_xy(x, y, book_name=name)
        self.feedback.setText(
            f'{"✅" if ok else "❌"} {name}: ({x:+.2f}, {y:+.2f})  {msg}')
        # 在点击位置画个临时标记
        pad = 12
        col = (x - self.origin[0]) / self.res - 0.5
        row = self.H - 1 - ((y - self.origin[1]) / self.res - 0.5)
        cx, cy = col + pad, row + pad
        r = 5
        marker = self.scene.addEllipse(
            cx - r, cy - r, 2 * r, 2 * r,
            QPen(QColor('#2F5D50'), 2), QBrush(QColor('#F1C40F')))
        from PySide6.QtCore import QTimer
        # 1.5s 后移除(给用户一个视觉指示)
        QTimer.singleShot(1500, lambda m=marker: self.scene.removeItem(m))

    # ============================================================
    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)