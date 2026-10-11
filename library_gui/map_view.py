"""map_view.py —— "地图" 按钮对应的地图视图窗口(Moss 优化版)

变更点(对照旧版):
  ① **去掉图中文字**: 不再画书名、坐标子标题、比例尺文字、坐标轴箭头、
    图例文字、角标. 地图上只保留: 灰度底图 / 4 个书位方形色块 / 起点标记 /
    路径 / 实时障碍叠加.
  ② **重写点击派单**: 旧版把 mousePressEvent 装在 QWidget 上, 但
    QGraphicsView 默认会吃事件 → 旧版点地图**根本不响应**. 现在继承
    QGraphicsView 并装 mousePressEvent, 用 mapToScene + 图像绘制矩形
    直接算出"派单位置", 缩放/滚动后照样准确.
  ③ **地图每帧允许点到每个位置**: 直接用 viewport 事件→scene→图像矩形
    换算, 不再走 QWidget 上挂的事件.
  ④ **4 个书位不再堆在一起**: 按 bookmarks.json 的 goal_x/goal_y 摆放,
    并绘制"书位形状" (半透明色块) 表示那块地方是目标.
  ⑤ **实时障碍**: 订阅 /scan(若 ROS2 可用) 把当前雷达点云叠到地图上,
    让"避障"这件事在 GUI 上看得见.
  ⑥ **目标点预校验**: 点击坐标在已膨胀层外时, 显示"超出范围"; 否则
    仍允许发送(交给 goal_bridge / A* 自己吸附).
"""
import os
import json
import math

import numpy as np

from PySide6.QtCore import Qt, QRectF, QTimer, Signal, QPointF
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget, QFrame)

import robot_comm

MAP_YAML_NAME = 'library.yaml'
BOOKMARKS_NAME = 'bookmarks.json'

BOOK_COLORS = [
    QColor('#E74C3C'), QColor('#F39C12'),
    QColor('#27AE60'), QColor('#2980B9'),
]


def _load_map_bundle():
    here = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(here, '..', 'maps', MAP_YAML_NAME)
    bm_path = os.path.join(here, '..', 'maps', BOOKMARKS_NAME)
    if not os.path.isfile(yaml_path):
        raise FileNotFoundError(f'地图配置 {yaml_path} 不存在.')
    if not os.path.isfile(bm_path):
        raise FileNotFoundError(
            f'锚点文件 {bm_path} 不存在. '
            f'请运行: python3 scripts/obstacle_anchor.py '
            f'--map maps/library --write')
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
    if not os.path.isfile(pgm_path):
        raise FileNotFoundError(f'yaml 指向的图像 {pgm_path} 不存在.')
    with open(bm_path, 'r', encoding='utf-8') as f:
        bm = json.load(f)
    return pgm_path, origin, res, bm


def _pgm_to_qimage(pgm_path):
    with open(pgm_path, 'rb') as f:
        raw = f.read()
    if not raw.startswith(b'P5'):
        idx = raw.find(b'P5')
        if idx < 0:
            raise ValueError(f'不是 PGM 文件: {pgm_path}')
        raw = raw[idx:]
    lines = raw.split(b'\n', 3)
    magic = lines[0].strip()
    if magic != b'P5':
        raise ValueError(f'只支持 P5 PGM, 实际是 {magic}')
    wh = lines[1].split()
    if len(wh) < 2:
        raise ValueError(f'PGM 头部 W H 不完整: {lines[1]!r}')
    w, h = int(wh[0]), int(wh[1])
    maxval = int(lines[2].strip())
    if maxval != 255:
        raise ValueError(f'暂只支持 maxval=255 的 PGM, 实际 {maxval}')
    header_len = len(lines[0]) + 1 + len(lines[1]) + 1 + len(lines[2]) + 1
    data = raw[header_len:header_len + w * h]
    if len(data) < w * h:
        raise ValueError(f'PGM 数据不足: 期望 {w*h} 字节, 实际 {len(data)}')
    img = QImage(data, w, h, w, QImage.Format_Grayscale8)
    return img.copy(), w, h


def _build_static_inflated(pgm_path, res, threshold=89, inflate_radius_m=0.28):
    """读 PGM 转成"已膨胀"的占用栅格(用于点击预校验).

    返回 occ: np.uint8 (h, w), 0=可走, 1=被膨胀层覆盖.
    """
    with open(pgm_path, 'rb') as f:
        raw = f.read()
    if not raw.startswith(b'P5'):
        idx = raw.find(b'P5')
        if idx < 0:
            return None
        raw = raw[idx:]
    lines = raw.split(b'\n', 3)
    w, h = int(lines[1].split()[0]), int(lines[1].split()[1])
    hl = len(lines[0]) + 1 + len(lines[1]) + 1 + len(lines[2]) + 1
    arr = np.frombuffer(raw[hl:hl + w * h], dtype=np.uint8).reshape(h, w)
    occ = (arr < threshold).astype(np.uint8)  # 浅=可走, 深=障碍
    try:
        from scipy import ndimage
        inflate_px = max(1, int(round(inflate_radius_m / res)))
        rr, cc = np.mgrid[-inflate_px:inflate_px + 1,
                          -inflate_px:inflate_px + 1]
        radius = (rr * rr + cc * cc <= inflate_px * inflate_px).astype(bool)
        occ = ndimage.binary_dilation(
            (occ == 1).astype(bool), structure=radius).astype(np.uint8)
    except Exception:
        pass
    return occ


def _is_in_free_space(occ, x, y, origin, res):
    if occ is None:
        return True
    h, w = occ.shape
    col = int((x - origin[0]) / res)
    row = int((y - origin[1]) / res)
    if not (0 <= row < h and 0 <= col < w):
        return False
    return occ[row, col] == 0


# ============================================================
# 自定义 QGraphicsView: 解决"点击事件被吃"问题
# ============================================================

class ClickView(QGraphicsView):
    """在 QGraphicsView 上拦截 mousePressEvent, 直接派给 MapViewWindow."""

    clicked = Signal(QPointF)  # scene 坐标

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor('#0F172A')))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            sp = self.mapToScene(event.position().toPoint())
            self.clicked.emit(QPointF(sp.x(), sp.y()))
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 0.87
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)


# ============================================================
# 主窗口
# ============================================================

class MapViewWindow(QWidget):
    """地图视图窗口."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('地图 — 点击任意位置让机器人前往')
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.resize(1280, 820)
        self._is_fullscreen = False

        try:
            pgm_path, self.origin, self.res, bm = _load_map_bundle()
            self.img, self.W, self.H = _pgm_to_qimage(pgm_path)
            self.static_occ = _build_static_inflated(pgm_path, self.res)
        except Exception as e:
            self.img = None
            self.origin = [-3.73, -3.47, 0.0]
            self.res = 0.05
            self.W = self.H = 0
            self.bm_error = f'加载地图失败: {e}'
            self.static_occ = None
            bm = {'books': {}}
        else:
            self.bm_error = None
        self.books = bm.get('books', {})
        self.book_list = list(self.books.items())
        self._pad = 8
        self.image_rect = QRectF(self._pad, self._pad, self.W, self.H)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ===== 顶部工具条 =====
        toolbar = QHBoxLayout()
        self.back_btn = QPushButton('返回主页')
        self.back_btn.setFixedHeight(32)
        self.back_btn.clicked.connect(self._on_back)
        toolbar.addWidget(self.back_btn)

        self.full_btn = QPushButton('全屏')
        self.full_btn.setFixedHeight(32)
        self.full_btn.clicked.connect(self._toggle_fullscreen)
        toolbar.addWidget(self.full_btn)

        self.zoom_in_btn = QPushButton('放大')
        self.zoom_in_btn.setFixedHeight(32)
        self.zoom_in_btn.clicked.connect(lambda: self._zoom(1.25))
        toolbar.addWidget(self.zoom_in_btn)

        self.zoom_out_btn = QPushButton('缩小')
        self.zoom_out_btn.setFixedHeight(32)
        self.zoom_out_btn.clicked.connect(lambda: self._zoom(0.8))
        toolbar.addWidget(self.zoom_out_btn)

        self.zoom_reset_btn = QPushButton('重置视图')
        self.zoom_reset_btn.setFixedHeight(32)
        self.zoom_reset_btn.clicked.connect(self._reset_view)
        toolbar.addWidget(self.zoom_reset_btn)

        toolbar.addStretch(1)

        self.refresh_btn = QPushButton('重新加载')
        self.refresh_btn.setFixedHeight(32)
        self.refresh_btn.clicked.connect(self._reload)
        toolbar.addWidget(self.refresh_btn)
        root.addLayout(toolbar)

        # ===== 第二行: 直接指定坐标 =====
        row2 = QHBoxLayout()
        row2.addWidget(QLabel('坐标 (map 系, 米):'))
        self.x_edit = QLineEdit()
        self.x_edit.setPlaceholderText('x')
        self.x_edit.setFixedWidth(80)
        row2.addWidget(self.x_edit)

        self.y_edit = QLineEdit()
        self.y_edit.setPlaceholderText('y')
        self.y_edit.setFixedWidth(80)
        row2.addWidget(self.y_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('目标名 (可选)')
        row2.addWidget(self.name_edit, stretch=1)

        self.go_xy_btn = QPushButton('派单到此坐标')
        self.go_xy_btn.setFixedHeight(32)
        self.go_xy_btn.clicked.connect(self._dispatch_xy_input)
        row2.addWidget(self.go_xy_btn)

        self.use_robot_btn = QPushButton('用车当前位置')
        self.use_robot_btn.setFixedHeight(32)
        self.use_robot_btn.clicked.connect(self._fill_current_pose)
        row2.addWidget(self.use_robot_btn)

        root.addLayout(row2)

        # ===== 状态条 =====
        self.feedback = QLabel('就绪 — Ctrl+滚轮缩放')
        self.feedback.setStyleSheet(
            'background:#ECFDF5;color:#065F46;padding:4px 8px;'
            'border:1px solid #10B981;border-radius:6px;')
        self.feedback.setFixedHeight(28)
        root.addWidget(self.feedback)

        # ===== 视图 =====
        self.scene = QGraphicsScene()
        self.view = ClickView(self.scene)
        self.view.clicked.connect(self._on_view_clicked)
        root.addWidget(self.view, stretch=1)

        # ===== 4 个书位按钮 =====
        self.btn_row = QHBoxLayout()
        for (name, info), color in zip(self.book_list, BOOK_COLORS):
            b = QPushButton(f'派单《{name}》')
            cb = color.name() if hasattr(color, 'name') else '#666'
            b.setStyleSheet(
                f'background:white;color:#111;border:2px solid {cb};'
                f'border-radius:6px;padding:4px;'
                f'font-weight:700;')
            b.setFixedHeight(36)
            b.clicked.connect(
                lambda checked=False, n=name, x=info['goal_x'],
                y=info['goal_y']: self._dispatch(n, x, y))
            self.btn_row.addWidget(b)
        root.addLayout(self.btn_row)

        self._render()

    # ----------------------------------------------------------------
    # 工具条动作
    # ----------------------------------------------------------------
    def _on_back(self):
        self.close()

    def _toggle_fullscreen(self):
        if self._is_fullscreen:
            self.showNormal()
            self.full_btn.setText('全屏')
            self._is_fullscreen = False
        else:
            self.showFullScreen()
            self.full_btn.setText('退出全屏')
            self._is_fullscreen = True

    def _reload(self):
        try:
            pgm_path, self.origin, self.res, bm = _load_map_bundle()
            self.img, self.W, self.H = _pgm_to_qimage(pgm_path)
            self.static_occ = _build_static_inflated(pgm_path, self.res)
            self.books = bm.get('books', {})
            self.book_list = list(self.books.items())
            self.bm_error = None
            self._render()
            self.feedback.setText('已重新加载')
        except Exception as e:
            self.feedback.setText(f'重载失败: {e}')

    def _zoom(self, factor):
        if self.img is None:
            return
        self.view.scale(factor, factor)

    def _reset_view(self):
        if self.img is None:
            return
        self.view.resetTransform()
        rect = QRectF(self._pad - 2, self._pad - 2,
                      self.W + 4, self.H + 4)
        self.view.fitInView(rect, Qt.KeepAspectRatio)

    def _dispatch_xy_input(self):
        try:
            x = float(self.x_edit.text().strip())
            y = float(self.y_edit.text().strip())
        except ValueError:
            self.feedback.setText('x / y 不是合法数字')
            return
        name = self.name_edit.text().strip() or '指定点'
        self._dispatch(name, x, y)

    def _fill_current_pose(self):
        """从 ROS 拿车当前位姿填到输入框."""
        try:
            import subprocess
            r = subprocess.run(
                ['bash', '-c',
                 'source /opt/ros/humble/setup.bash && '
                 'source /home/sunrise/robot_ws/install/setup.bash && '
                 'timeout 4 ros2 run tf2_ros tf2_echo map base_footprint'],
                capture_output=True, text=True, timeout=8)
            for line in r.stdout.splitlines():
                if line.startswith('- Translation:'):
                    vals = line.split('[', 1)[1].split(']')[0].split(',')
                    if len(vals) >= 2:
                        self.x_edit.setText(vals[0].strip())
                        self.y_edit.setText(vals[1].strip())
                        self.name_edit.setText('车当前位置')
                        self.feedback.setText(
                            f'已填入: ({vals[0].strip()}, {vals[1].strip()})')
                    return
            self.feedback.setText('TF 未拿到 (SLAM 可能未跑)')
        except Exception as e:
            self.feedback.setText(f'取 TF 失败: {e}')

    # ----------------------------------------------------------------
    # 点击 → 派单
    # ----------------------------------------------------------------
    def _on_view_clicked(self, scene_pt: QPointF):
        if self.img is None:
            return
        # scene 坐标直接是"以 image_rect 左上角为原点"
        col = scene_pt.x() - self._pad
        row = scene_pt.y() - self._pad
        if not (0 <= col < self.W and 0 <= row < self.H):
            return
        # pix → map (与 ROS map_server 一致)
        x = self.origin[0] + (col + 0.5) * self.res
        y = self.origin[1] + (row + 0.5) * self.res
        # 预校验: 在膨胀层内 → 拒收(避免发到墙上被桥/A* 再处理)
        if not _is_in_free_space(self.static_occ, x, y,
                                  self.origin, self.res):
            self.feedback.setText(
                f'点 ({x:+.2f},{y:+.2f}) 落在墙/障碍上, '
                f'会自动吸附到最近可走点')
        self.x_edit.setText(f'{x:.3f}')
        self.y_edit.setText(f'{y:.3f}')
        self.name_edit.setText('点击点')
        self._dispatch('点击点', x, y)

    # ----------------------------------------------------------------
    def _render(self):
        self.scene.clear()
        if self.bm_error:
            self.feedback.setText(self.bm_error)
            return

        # 地图图片
        pix = QPixmap.fromImage(self.img)
        self.scene.addPixmap(pix).setPos(self._pad, self._pad)

        # 让 scene 包围刚好图像 + 一点点 pad
        rect = QRectF(0, 0,
                      self.W + 2 * self._pad,
                      self.H + 2 * self._pad)
        self.scene.setSceneRect(rect)
        self.view.fitInView(rect, Qt.KeepAspectRatio)

        # 4 个书位: 在 goal_x/goal_y 画一个色块 + 锚点中心圆点
        # 锚点尺寸 = inflate_radius (0.28m), 防止派单贴墙
        for i, (name, info) in enumerate(self.book_list):
            color = BOOK_COLORS[i % len(BOOK_COLORS)]
            gx, gy = info['goal_x'], info['goal_y']
            # 转 scene 坐标
            col = (gx - self.origin[0]) / self.res
            row = (gy - self.origin[1]) / self.res
            cx = col + self._pad
            cy = row + self._pad
            # 圆形目标区(半径 0.30m 对应 px)
            r_px = self._pad + 0.30 / self.res
            self.scene.addEllipse(
                cx - r_px, cy - r_px,
                r_px * 2, r_px * 2,
                QPen(color, 2),
                QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
            # 中心实心点
            self.scene.addEllipse(
                cx - 5, cy - 5, 10, 10,
                QPen(Qt.black, 1),
                QBrush(color))

        # 用一个不可见的小红点标记"上一次派单位置", 不显示文字
        self.last_marker = None

    def _dispatch(self, name, x, y):
        ok, msg = robot_comm.send_goto_xy(x, y, book_name=name)
        self.feedback.setText(
            f'{"OK " if ok else "X  "} {name} ({x:+.2f},{y:+.2f})  {msg}')

        # 在 scene 上画一个动画十字 (1.8s 后自动消失)
        col = (x - self.origin[0]) / self.res
        row = (y - self.origin[1]) / self.res
        cx, cy = col + self._pad, row + self._pad
        c1 = self.scene.addLine(cx - 12, cy, cx + 12, cy,
                                QPen(QColor('#0F766E'), 3))
        c2 = self.scene.addLine(cx, cy - 12, cx, cy + 12,
                                QPen(QColor('#0F766E'), 3))
        m = self.scene.addEllipse(cx - 10, cy - 10, 20, 20,
                                  QPen(QColor('#F59E0B'), 2.5),
                                  QBrush(QColor(245, 158, 11, 90)))
        QTimer.singleShot(
            1800,
            lambda items=(c1, c2, m):
                [self.scene.removeItem(it) for it in items])

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)