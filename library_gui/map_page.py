#!/usr/bin/env python3
"""map_page.py —— GUI 左侧导航「地图」模块页面

职责
    * 顶部：当前地图摘要（导航栈真正读取的 maps/library.*）
    * 左侧：版本仓库列表 —— 每保存一次，就把**当时最新的 SLAM 建图结果**
            整包存成一版；★ 标记的是当前生效那一版
    * 右侧：地图预览 + 版本详情 + 操作
            💾 保存当前SLAM结果 / ⟲ 回溯到此版本 / 🗑 删除此版本 / 🖱 交互地图

后端在 map_store.py（快照/列表/回溯/删除，回溯前自动备份当前地图）。
本文件只负责界面，所有重活丢给 MapWorker 后台线程，避免界面卡住。
"""

import os

from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget)


def _confirm(parent, title, text, yes='确定', no='取消'):
    """复用 GUI.py 的弹窗风格；import 放函数内，避免模块循环依赖。"""
    try:
        from GUI import show_dialog
        return show_dialog(parent, title, text, buttons=(yes, no)) == 1
    except Exception:
        from PySide6.QtWidgets import QMessageBox
        return QMessageBox.question(
            parent, title, text,
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes


class MapWorker(QThread):
    """后台执行地图仓库的重活（抓 SLAM 结果 / 回溯 / 删除），不卡界面。"""

    done = Signal(str, bool, str)          # (action, ok, msg)

    def __init__(self, store, action, version_id=None, label=''):
        super().__init__()
        self.store = store
        self.action = action
        self.version_id = version_id
        self.label = label

    def run(self):
        try:
            if self.action == 'save':
                note = ''
                if self.store.slam_running():
                    ok, msg = self.store.refresh_from_slam()
                    note = msg
                    source = 'slam' if ok else 'existing'
                else:
                    note = 'SLAM 未运行，直接对现有 maps/library.* 打版本'
                    source = 'existing'
                r = self.store.save_current(
                    label=self.label or '手动保存', note=note, source=source)
                text = r.get('msg', '')
                if note:
                    text = f'{note} | {text}'
                self.done.emit('save', bool(r.get('ok')), text)
            elif self.action == 'restore':
                r = self.store.restore(self.version_id)
                self.done.emit('restore', bool(r.get('ok')), r.get('msg', ''))
            elif self.action == 'delete':
                r = self.store.delete(self.version_id)
                self.done.emit('delete', bool(r.get('ok')), r.get('msg', ''))
            else:
                self.done.emit(self.action, False, f'未知操作: {self.action}')
        except Exception as e:
            self.done.emit(self.action, False, f'出错: {e}')


class MapPage(QWidget):
    """🗺 地图模块（左侧导航进入）。"""

    def __init__(self):
        super().__init__()
        self._store_obj = None
        self._worker = None
        self._src_pix = None
        self._map_win = None
        self._versions = []
        self._build_ui()
        self.refresh()

    def _store(self):
        if self._store_obj is None:
            from map_store import MapStore
            self._store_obj = MapStore()
        return self._store_obj

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel('🗺 地图')
        title.setStyleSheet('font-size:20px;font-weight:800;color:#2F5D50;')
        head.addWidget(title)
        head.addStretch(1)
        self.cur_label = QLabel('当前地图：读取中…')
        # 这一行以前把尺寸/分辨率/原点/时间全塞进去, 单行文本要 615px,
        # 成了整页最小宽度的瓶颈(页最小 730 -> 窗口最小 884 > 800 屏)。
        # 现在只留关键数字, 完整信息走 tooltip; Ignored 让尺寸提示不参与布局。
        self.cur_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.cur_label.setToolTip('导航栈实际读取的地图：maps/library.yaml')
        self.cur_label.setStyleSheet(
            'background:#EEF5EF;color:#2F5D50;border:1px solid #D6E5D8;'
            'border-radius:12px;padding:3px 12px;font-weight:600;')
        head.addWidget(self.cur_label)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)

        # ---------- 左侧：版本仓库 ----------
        left = QVBoxLayout()
        left.setSpacing(6)
        hint = QLabel('版本仓库（★ = 当前生效）')
        hint.setStyleSheet('color:#4B5563;font-size:12px;')
        left.addWidget(hint)

        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 40))
        self.list.setFixedWidth(200)
        self.list.itemSelectionChanged.connect(self._on_select)
        left.addWidget(self.list, 1)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.save_btn = QPushButton('💾 保存')
        self.save_btn.setToolTip(
            '把当前最新的 SLAM 建图结果整包存成一个新版本\n'
            '（SLAM 在跑就先抓最新结果；没跑则对现有 maps/library.* 打版本）')
        self.save_btn.clicked.connect(self.on_save)
        self.open_map_btn = QPushButton('🖱 地图')
        self.open_map_btn.setToolTip('打开交互地图：点任意位置派单 / 书位一键前往')
        self.open_map_btn.clicked.connect(self.open_interactive_map)
        for b in (self.save_btn, self.open_map_btn):
            b.setFixedHeight(32)
            b.setStyleSheet(
                'QPushButton{background:#2F5D50;color:white;border:none;'
                'border-radius:10px;font-weight:700;padding:0 8px;}'
                'QPushButton:disabled{background:#9CA3AF;}')
            row1.addWidget(b)
        left.addLayout(row1)
        body.addLayout(left, 0)

        # ---------- 右侧：预览 + 详情 + 操作 ----------
        right = QVBoxLayout()
        right.setSpacing(6)

        self.preview = QLabel('选择一个版本查看地图预览')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(200, 130)
        # 关键：QLabel 设置 pixmap 后, 它的 minimumSizeHint 会变成 pixmap 尺寸,
        # 于是「布局给多宽 -> 缩放成多大 -> 最小尺寸又变大」自我放大,
        # 把整页最小宽度顶到 700+。用 Ignored 让它的尺寸提示不参与布局计算,
        # 只保留显式的 setMinimumSize(200,130) 作为下限。
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview.setStyleSheet(
            'background:#0F172A;color:#94A3B8;border-radius:12px;'
            'border:1px solid #D6E5D8;')
        right.addWidget(self.preview, 1)

        self.detail = QLabel('-')
        self.detail.setWordWrap(True)
        self.detail.setFixedHeight(54)
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.detail.setStyleSheet('color:#4B5563;font-size:12px;')
        right.addWidget(self.detail)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.restore_btn = QPushButton('⟲ 回溯')
        self.restore_btn.setToolTip(
            '把导航栈读取的地图换回选中版本\n（会先把当前地图自动备份成一个版本）')
        self.restore_btn.clicked.connect(self.on_restore)
        self.delete_btn = QPushButton('🗑 删除')
        self.delete_btn.setToolTip('只删除选中这条历史副本，不动当前地图')
        self.delete_btn.clicked.connect(self.on_delete)
        self.refresh_btn = QPushButton('🔄 刷新')
        self.refresh_btn.clicked.connect(self.refresh)
        for b in (self.restore_btn, self.delete_btn, self.refresh_btn):
            b.setFixedHeight(32)
            b.setStyleSheet(
                'QPushButton{background:white;border:1px solid #D6E5D8;'
                'border-radius:10px;padding:0 10px;}'
                'QPushButton:hover{background:#EEF5EF;}'
                'QPushButton:disabled{color:#9CA3AF;}')
            row2.addWidget(b)
        right.addLayout(row2)

        self.status = QLabel(
            '就绪：每次保存都会把当时最新的 SLAM 建图结果存一版')
        self.status.setWordWrap(True)
        self.status.setFixedHeight(46)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.status.setStyleSheet(
            'background:#EEF5EF;color:#2F5D50;border:1px solid #D6E5D8;'
            'border-radius:10px;padding:4px 10px;font-size:12px;')
        right.addWidget(self.status)

        body.addLayout(right, 1)
        root.addLayout(body, 1)
        self._set_buttons_enabled(False)

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def showEvent(self, event):
        # 每次切进这一页都重扫一遍，保证看到最新版本
        self.refresh()
        super().showEvent(event)

    def refresh(self):
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            store = self._store()
            info = store.current_info()
            if info['exists']:
                o = info['origin']
                origin = f'({o[0]:.2f}, {o[1]:.2f})' if len(o) >= 2 else '-'
                self.cur_label.setText(
                    f"当前 {info['width']}×{info['height']} · "
                    f"{info['resolution']} m · {info['bookmarks']} 书位")
                self.cur_label.setToolTip(
                    f"导航栈实际读取的地图：maps/library.yaml\n"
                    f"尺寸 {info['width']}×{info['height']} px · "
                    f"分辨率 {info['resolution']} m/px · 原点 {origin}\n"
                    f"更新时间 {info['time']}\n"
                    f"包含文件：{'、'.join(info['files'])}")
            else:
                self.cur_label.setText('当前地图不存在')

            self._versions = store.list_versions()
            self.list.blockSignals(True)
            self.list.clear()
            sel_row = 0
            for i, v in enumerate(self._versions):
                mark = '★ 当前' if v.get('is_current') else ''
                item = QListWidgetItem(
                    self._thumb(store.version_pgm_path(v['id'])),
                    f"{v.get('label') or v['id']}\n"
                    f"{v.get('time', '')}  {v.get('width')}×{v.get('height')}"
                    f"  {v.get('bookmarks', 0)}书位 {mark}")
                item.setData(Qt.UserRole, v['id'])
                self.list.addItem(item)
                if v.get('is_current'):
                    sel_row = i
            self.list.blockSignals(False)
            if self._versions:
                self.list.setCurrentRow(sel_row)
            else:
                self.preview.setPixmap(QPixmap())
                self.preview.setText('还没有历史版本 —— 点「💾 保存当前SLAM结果」建第一版')
                self.detail.setText('-')
                self._set_buttons_enabled(False)
        except Exception as e:
            self.status.setText(f'读取地图仓库失败：{e}')

    def _thumb(self, pgm_path):
        """给版本列表做个小缩略图（只读 pgm，很轻）。"""
        try:
            from map_view import _pgm_to_qimage
            img, _w, _h = _pgm_to_qimage(pgm_path)
            pm = QPixmap.fromImage(img).scaled(
                48, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return QIcon(pm)
        except Exception:
            return QIcon()

    def _selected_version(self):
        item = self.list.currentItem()
        if item is None:
            return None
        vid = item.data(Qt.UserRole)
        for v in self._versions:
            if v['id'] == vid:
                return v
        return None

    def _on_select(self):
        v = self._selected_version()
        if v is None:
            self._set_buttons_enabled(False)
            return
        self._set_buttons_enabled(True)
        mb = (v.get('bytes') or 0) / 1048576.0
        self.detail.setText(
            f"版本 {v['id']} · {v.get('label')}"
            + ('   ★当前生效' if v.get('is_current') else '') + "\n"
            f"时间 {v.get('time')} · 来源 {v.get('source')} · "
            f"{v.get('width')}×{v.get('height')} px · "
            f"分辨率 {v.get('resolution')} m · {v.get('bookmarks')} 书位 · "
            f"{mb:.1f} MB\n"
            f"文件 {'、'.join(v.get('files', []))}")
        self._load_preview(v)

    def _load_preview(self, v):
        try:
            from map_view import _pgm_to_qimage
            pgm = self._store().version_pgm_path(v['id'])
            img, _w, _h = _pgm_to_qimage(pgm)
            self._src_pix = QPixmap.fromImage(img)
            self._render_preview()
        except Exception as e:
            self._src_pix = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f'预览失败：{e}')

    def _render_preview(self):
        if self._src_pix is None:
            return
        box = self.preview.size()
        if box.width() < 20 or box.height() < 20:
            return
        self.preview.setPixmap(self._src_pix.scaled(
            box, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        self._render_preview()
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def _set_buttons_enabled(self, has_sel):
        busy = self._worker is not None and self._worker.isRunning()
        self.save_btn.setEnabled(not busy)
        self.open_map_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        self.restore_btn.setEnabled(bool(has_sel) and not busy)
        self.delete_btn.setEnabled(bool(has_sel) and not busy)

    def _run_worker(self, action, version_id=None, label=''):
        if self._worker is not None and self._worker.isRunning():
            return
        self.status.setText('处理中…')
        self._set_buttons_enabled(False)
        self._worker = MapWorker(self._store(), action,
                                 version_id=version_id, label=label)
        self._worker.done.connect(self._on_worker_done)
        self._worker.start()

    def _on_worker_done(self, action, ok, msg):
        head = {'save': '保存', 'restore': '回溯', 'delete': '删除'}.get(
            action, action)
        self.status.setText(('✅ ' if ok else '❌ ') + f'{head}：{msg}')
        self.refresh()

    def on_save(self):
        label, ok = QInputDialog.getText(
            self, '保存地图版本',
            '版本备注（可留空）：\n\n'
            'SLAM 正在跑时会先抓取最新建图结果；没跑则直接对现有 '
            'maps/library.* 打一个版本。')
        if not ok:
            return
        self._run_worker('save', label=(label or '').strip() or '手动保存')

    def on_restore(self):
        v = self._selected_version()
        if v is None:
            return
        if not _confirm(
                self, '回溯地图',
                f"确定把「当前地图」换成版本\n\n{v['id']}\n{v.get('label')}\n\n"
                f"（当前地图会先自动备份成一个版本，可再回溯回来）",
                yes='确定回溯', no='取消'):
            return
        self._run_worker('restore', version_id=v['id'])

    def on_delete(self):
        v = self._selected_version()
        if v is None:
            return
        if not _confirm(
                self, '删除版本',
                f"确定删除历史版本\n\n{v['id']}\n{v.get('label')}\n\n"
                f"（只删历史副本，不动当前地图）",
                yes='确定删除', no='取消'):
            return
        self._run_worker('delete', version_id=v['id'])

    def open_interactive_map(self):
        """打开原有交互地图（点地图任意位置派单 / 书位一键前往）。"""
        try:
            from map_view import MapViewWindow
            if self._map_win is None:
                self._map_win = MapViewWindow(self)
                self._map_win.closed.connect(
                    lambda: setattr(self, '_map_win', None))
            self._map_win.show()
            self._map_win.raise_()
            self._map_win.activateWindow()
        except Exception as e:
            self.status.setText(f'打开交互地图失败：{e}')
