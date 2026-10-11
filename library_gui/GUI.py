import sys
import os

import math
import threading
from html import escape as html_escape

VOICE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "voice"
)

if VOICE_DIR not in sys.path:
    sys.path.insert(0, VOICE_DIR)

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import (
    QFont, QPainter, QColor, QBrush, QPen, QLinearGradient, QTextCursor)
from PySide6.QtWidgets import *
from PySide6.QtCore import Signal, QUrl, QThread
from map_page import MapPage
import pymysql
from dbutils.pooled_db import PooledDB 
from 数据池 import db_pool
from datetime import datetime, timedelta

def show_dialog(parent, title, text, buttons=None):
    box = QDialog(parent)

    box.setWindowTitle(title)
    box.setWindowModality(Qt.ApplicationModal)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    box.setFixedSize(500, 250)

    layout = QVBoxLayout(box)

    label = QLabel(text)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet("font-size: 20px;")
    layout.addWidget(label)

    if buttons is None:
        button = QPushButton("知道了")
        button.setFixedHeight(45)
        button.setStyleSheet("font-size: 18px;")
        layout.addWidget(button)
        button.clicked.connect(box.accept)

    else:
        button_layout = QHBoxLayout()

        button_yes = QPushButton(buttons[0])
        button_no = QPushButton(buttons[1])

        button_yes.setFixedHeight(45)
        button_no.setFixedHeight(45)

        button_yes.setStyleSheet("font-size: 18px;")
        button_no.setStyleSheet("font-size: 18px;")

        button_layout.addWidget(button_yes)
        button_layout.addWidget(button_no)

        layout.addLayout(button_layout)

        button_yes.clicked.connect(lambda: box.done(1))
        button_no.clicked.connect(lambda: box.done(2))

    result = box.exec()

    if buttons is None:
        return True

    return result

GREEN="#306757"
from datetime import datetime,timedelta

BORROW_RECORDS = []

class SearchLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.callback = None

    def mousePressEvent(self, event):
        if self.callback:
            self.callback()
        super().mousePressEvent(event)

class BookCard(QFrame):
    def __init__(self,title):
        super().__init__()
        self.setFixedSize(160,220)
        self.setStyleSheet("background:white;border-radius:18px;")
        v=QVBoxLayout(self)
        cover=QLabel("封面")
        cover.setFixedHeight(140)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet("background:#EEF5EF;border-radius:12px;")
        name=QLabel(title)
        name.setAlignment(Qt.AlignCenter)
        v.addWidget(cover)
        v.addWidget(name)

#界面设计
class HomePage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)  # 移除边距
        root.setSpacing(12)  # 设置间距
        
        root.addStretch(1)
        
        # 标题
        title = QLabel("图书馆机器人")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            QLabel{
                font-size:30px;
                font-weight:800;
                color:#2F5D50;
                margin-top:12px;
                margin-bottom:8px;
            }
        """)
        root.addWidget(title)
        
        # 搜索框
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("🔍 搜索书籍名称")
        self.search.setFixedSize(600, 44)
        
        self.history = QListWidget()
        self.history.setFixedSize(600, 110)
        self.history.hide()
        self.history.setVisible(False)
        
        root.addWidget(self.search, alignment=Qt.AlignCenter)
        root.addWidget(self.history, alignment=Qt.AlignCenter)
        
        self.search.callback = lambda: self.history.show()
        self.search.returnPressed.connect(self.on_search)
        
        # 连接点击事件
        self.history.itemClicked.connect(self.on_result_clicked)
        
        # ⭐ 快捷功能框 - 向上移动（减少间距）
        box = QGroupBox("📌 快捷功能")
        box.setFixedSize(600, 112)  # 适配 800x480 屏
        box.setStyleSheet("""
            QGroupBox{
                font-size:18px;
                font-weight:700;
                border:2px solid #D6E5D8;
                border-radius:16px;
                margin-top:15px;
                padding-top:15px;
                background:white;
            }
        """)
        vbox = QVBoxLayout(box)
        vbox.setSpacing(15)
        vbox.setContentsMargins(50, 20, 50, 20)
        
        # 创建两个按钮的横向布局
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(40)
        
        # 语音交互按钮（原来的「地图」入口已移除；按钮按位替换、尺寸不变，
        # 所以快捷功能框的布局不受影响）
        voice_btn = QPushButton("🎤 语音助手")
        voice_btn.setFixedHeight(50)
        voice_btn.setStyleSheet("""
            QPushButton{
                background: #FDECEA;
                border: 2px solid #E74C3C;
                border-radius: 16px;
                font-size: 20px;
                font-weight: 600;
                color: #B03A2E;
            }
            QPushButton:hover{
                background: #F8D7D3;
                border-color: #B03A2E;
            }
        """)
        voice_btn.clicked.connect(self.open_voice)
        
        # 寻找图书按钮
        find_btn = QPushButton("🔍 寻找图书")
        find_btn.setFixedHeight(50)
        find_btn.setStyleSheet("""
            QPushButton{
                background: #2F5D50;
                border: 2px solid #2F5D50;
                border-radius: 16px;
                font-size: 20px;
                font-weight: 600;
                color: white;
            }
            QPushButton:hover{
               background: #D6E5D8;
               border-color: #2F5D50;
            }
        """)
  
        # ⭐ 寻找图书按钮 → 弹输入框, 拿书名后调 on_search
        find_btn.clicked.connect(self.open_find_book)
        
        btn_layout.addWidget(voice_btn)
        btn_layout.addWidget(find_btn)
        vbox.addLayout(btn_layout)
        
        # ⭐ 减少底部弹性空间，让整体上移
        root.addWidget(box, alignment=Qt.AlignCenter)
        root.addStretch(1)  # 减少弹性空间
        
        # 存储搜索结果
        self.search_results = []
    
    def open_voice(self):
        """打开语音交互页 —— 主页面预留的语音按钮入口。

        主页面原来的「地图」功能已按要求移除，按钮按位替换成语音入口；
        map_view.py 仍保留在项目目录里（未删除），需要时可再挂回来。
        """
        main_window = self.window()
        if hasattr(main_window, 'voice_page'):
            main_window.stack.setCurrentWidget(main_window.voice_page)
        elif hasattr(main_window, 'stack'):
            main_window.stack.setCurrentIndex(5)

    def open_find_book(self):
        """寻找图书按钮 —— 弹输入框拿书名, 然后走 on_search 流程."""
        text, ok = QInputDialog.getText(
            self, '寻找图书', '请输入书名:')
        if not ok or not text.strip():
            return
        self.search.setText(text.strip())
        self.history.show()
        self.on_search()
    
    
    def on_search(self):
        """搜索书籍 - 使用连接池"""
        keyword = self.search.text().strip()
        if not keyword:
            return
        
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            # 查询更多字段用于详情页，包括 id
            sql = "SELECT id, book_name, author, publisher, isbn, douban_score, description, location FROM books WHERE book_name LIKE %s OR author LIKE %s LIMIT 10"
            cursor.execute(sql, ('%' + keyword + '%', '%' + keyword + '%'))
            results = cursor.fetchall()
            
            self.history.clear()
            if results:
                self.search_results = []
                for row in results:
                    book_data = {
                        'id': row[0],                    # 添加书籍ID
                        'book_name': row[1] if row[1] else '未知',
                        'author': row[2] if row[2] else '未知',
                        'publisher': row[3] if row[3] else '未知',
                        'isbn': row[4] if row[4] else '无',
                        'douban_score': row[5] if row[5] else '暂无',
                        'description': row[6] if row[6] else '暂无简介',
                        'location': row[7] if row[7] else None
                    }
                    self.search_results.append(book_data)
                    self.history.addItem(f"{book_data['book_name']} - {book_data['author']}")
                self.history.show()
            else:
                self.search_results = []
                self.history.addItem("未找到匹配的书籍")
                self.history.show()
                
        except Exception as e:
            print(f"查询失败：{e}")
            self.history.addItem(f"查询失败：{e}")
            self.history.show()
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    def on_result_clicked(self, item):
        """点击搜索结果，打开详情页"""
        index = self.history.row(item)
        if hasattr(self, 'search_results') and index < len(self.search_results):
            book_data = self.search_results[index]
            
            # 获取主窗口和堆栈
            main_window = self.window()
            if hasattr(main_window, 'stack'):
                # 创建详情页
                detail_page = BookDetailPage(book_data)
                # 添加到堆栈
                main_window.stack.addWidget(detail_page)
                # 切换到详情页
                main_window.stack.setCurrentWidget(detail_page)
    
    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if not self.search.geometry().contains(pos) and \
           not self.history.geometry().contains(pos):
            self.history.hide()
        super().mousePressEvent(event)

class SearchPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)  # 移除边距
        v.setSpacing(0)  # 移除间距，用手动控制
        
        # ⭐ 顶部弹性空间 - 垂直居中
        v.addStretch(1)

        # 搜索框 - 保存为实例变量
        self.search = QLineEdit()
        self.search.setPlaceholderText("书名 / 作者 / ISBN")
        self.search.setFixedSize(600, 44)
        self.search.setStyleSheet("""
            QLineEdit {
                font-size: 18px;
                padding: 8px;
                border: 1px solid #D6E5D8;
                border-radius: 10px;
            }
        """)
        v.addWidget(self.search, alignment=Qt.AlignCenter)
        
        # 连接回车搜索事件
        self.search.returnPressed.connect(self.on_search)

        # ⭐ 减少搜索框和下面的间距
        v.addSpacing(8)

        # 主内容横向布局 - 使用 QWidget 包裹来实现居中
        h_widget = QWidget()
        h_widget.setFixedWidth(600)  # 固定宽度，让内容整体居中
        h = QHBoxLayout(h_widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)  # 减小间距

        # 左侧：猜你喜欢
        left = QGroupBox("猜你喜欢")
        left.setFixedSize(288, 168)  # 适配 800x480 屏
        left.setStyleSheet("""
            QGroupBox{
                font-size:20px;
                font-weight:700;
                border:1px solid #D6E5D8;
                border-radius:16px;
                margin-top:15px;
                padding-top:15px;
                background:white;
            }
        """)
        hl = QVBoxLayout(left)
        hl.setSpacing(2)  # 减小间距
        hl.setContentsMargins(10, 5, 10, 5)  # 减小内边距
        
        # 猜你喜欢列表
        recommend_items = ["Python", "深度学习", "算法导论", "数据库"]
        for b in recommend_items:
            label = QLabel(f"📚  {b}")
            label.setFixedHeight(30)
            label.setCursor(Qt.PointingHandCursor)
            label.setStyleSheet("""
                QLabel{
                    font-size:18px;
                    padding-left:20px;
                    border-radius:10px;
                    border-bottom:1px solid #E5E7EB;
                }
                QLabel:hover{
                    background:#EEF5EF;
                }
            """)
            label.mousePressEvent = lambda event, text=b: self.recommend_clicked(text)
            hl.addWidget(label)
        h.addWidget(left)

        # 右侧：热门搜索
        right = QGroupBox("热门搜索")
        right.setFixedSize(288, 168)  # 适配 800x480 屏
        right.setStyleSheet("""
            QGroupBox{
                font-size:20px;
                font-weight:700;
                border:1px solid #D6E5D8;
                border-radius:16px;
                margin-top:15px;
                padding-top:15px;
                background:white;
            }
        """)
        hr = QVBoxLayout(right)
        hr.setSpacing(2)  # 减小间距
        hr.setContentsMargins(10, 5, 10, 5)  # 减小内边距
        
        # 热门搜索列表
        hot_items = ["机器学习", "人工智能", "计算机网络", "操作系统"]
        for b in hot_items:
            label = QLabel(f"🔥  {b}")
            label.setFixedHeight(30)
            label.setCursor(Qt.PointingHandCursor)
            label.setStyleSheet("""
                QLabel{
                    font-size:18px;
                    padding-left:20px;
                    border-radius:10px;
                    border-bottom:1px solid #E5E7EB;
                }
                QLabel:hover{
                    background:#EEF5EF;
                }
            """)
            label.mousePressEvent = lambda event, text=b: self.recommend_clicked(text)
            hr.addWidget(label)
        h.addWidget(right)

        # 将横向布局添加到主布局（居中）
        v.addWidget(h_widget, alignment=Qt.AlignCenter)
        
        # ⭐ 减少间距
        v.addSpacing(8)
        
        # 搜索结果标题
        result_title = QLabel("📚 搜索结果")
        result_title.setStyleSheet("""
            QLabel{
                font-size: 15px;
                font-weight: 700;
                color: #2F5D50;
                padding: 5px 10px;
            }
        """)
        v.addWidget(result_title, alignment=Qt.AlignCenter)
        
        # 搜索结果列表
        self.result_list = QListWidget()
        self.result_list.setFixedSize(580, 130)
        self.result_list.setStyleSheet("""
            QListWidget{
                background: white;
                border: 1px solid #D6E5D8;
                border-radius: 10px;
                font-size: 16px;
            }
            QListWidget::item{
                padding: 10px 15px;
                border-bottom: 1px solid #E5E7EB;
            }
            QListWidget::item:hover{
                background: #EEF5EF;
            }
        """)
        v.addWidget(self.result_list, alignment=Qt.AlignCenter)
        self.result_list.itemClicked.connect(self.on_result_clicked)
        
        # ⭐ 底部弹性空间 - 垂直居中
        v.addStretch(1)
        
        # 存储搜索结果
        self.search_results = []
    
    def on_search(self):
        """搜索功能"""
        keyword = self.search.text().strip()
        if not keyword:
            return
        
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            sql = "SELECT id, book_name, author, publisher, isbn, douban_score, description FROM books WHERE book_name LIKE %s OR author LIKE %s LIMIT 20"
            cursor.execute(sql, ('%' + keyword + '%', '%' + keyword + '%'))
            results = cursor.fetchall()
            
            self.result_list.clear()
            if results:
                self.search_results = []
                print(f"\n📚 找到 {len(results)} 本与 '{keyword}' 相关的图书")
                for row in results:
                    book_data = {
                        'id': row[0],
                        'book_name': row[1] if row[1] else '未知',
                        'author': row[2] if row[2] else '未知',
                        'publisher': row[3] if row[3] else '未知',
                        'isbn': row[4] if row[4] else '无',
                        'douban_score': row[5] if row[5] else '暂无',
                        'description': row[6] if row[6] else '暂无简介'
                    }
                    self.search_results.append(book_data)
                    self.result_list.addItem(f"📖 {book_data['book_name']} - {book_data['author']}")
            else:
                self.search_results = []
                self.result_list.addItem("未找到匹配的书籍")
                print(f"❌ 未找到与 '{keyword}' 相关的图书")
                
        except Exception as e:
            print(f"查询失败：{e}")
            self.result_list.addItem(f"查询失败：{e}")
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def on_result_clicked(self, item):
        """点击搜索结果，打开详情页"""
        index = self.result_list.row(item)
        if hasattr(self, 'search_results') and index < len(self.search_results):
            book_data = self.search_results[index]
            main_window = self.window()
            if hasattr(main_window, 'stack'):
                detail_page = BookDetailPage(book_data)
                main_window.stack.addWidget(detail_page)
                main_window.stack.setCurrentWidget(detail_page)
    
    def recommend_clicked(self, text):
        """点击推荐项，自动搜索"""
        print(f"点击了推荐：{text}")
        self.search.setText(text)
        self.on_search()
    
    def on_search(self):
        """搜索功能"""
        keyword = self.search.text().strip()
        if not keyword:
            return
        
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            sql = "SELECT id, book_name, author, publisher, isbn, douban_score, description FROM books WHERE book_name LIKE %s OR author LIKE %s LIMIT 20"
            cursor.execute(sql, ('%' + keyword + '%', '%' + keyword + '%'))
            results = cursor.fetchall()
            
            self.result_list.clear()
            if results:
                self.search_results = []
                print(f"\n📚 找到 {len(results)} 本与 '{keyword}' 相关的图书")
                for row in results:
                    book_data = {
                        'id': row[0],                    # 添加书籍ID
                        'book_name': row[1] if row[1] else '未知',
                        'author': row[2] if row[2] else '未知',
                        'publisher': row[3] if row[3] else '未知',
                        'isbn': row[4] if row[4] else '无',
                        'douban_score': row[5] if row[5] else '暂无',
                        'description': row[6] if row[6] else '暂无简介'
                    }
                    self.search_results.append(book_data)
                    self.result_list.addItem(f"📖 {book_data['book_name']} - {book_data['author']}")
            else:
                self.search_results = []
                self.result_list.addItem("未找到匹配的书籍")
                print(f"❌ 未找到与 '{keyword}' 相关的图书")
                
        except Exception as e:
            print(f"查询失败：{e}")
            self.result_list.addItem(f"查询失败：{e}")
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def on_result_clicked(self, item):
        """点击搜索结果，打开详情页"""
        index = self.result_list.row(item)
        if hasattr(self, 'search_results') and index < len(self.search_results):
            book_data = self.search_results[index]
            main_window = self.window()
            if hasattr(main_window, 'stack'):
                detail_page = BookDetailPage(book_data)
                main_window.stack.addWidget(detail_page)
                main_window.stack.setCurrentWidget(detail_page)
    
    def recommend_clicked(self, text):
        """点击推荐项，自动搜索"""
        print(f"点击了推荐：{text}")  # 调试输出
        self.search.setText(text)
        self.on_search()

class BorrowPage(QWidget):
    def __init__(self):
        super().__init__()

        v = QVBoxLayout(self)
        v.addSpacing(10)

        # 标题
        title = QLabel("📚 借阅中心")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:22px;font-weight:700;color:#2F5D50;margin-bottom:10px;")
        v.addWidget(title)

        # 统计卡片
        top = QHBoxLayout()
        top.setSpacing(30)
        top.setAlignment(Qt.AlignCenter)

        self.borrow_label = QLabel("0 本书")
        self.overdue_label = QLabel("0 本书")  # ⭐ 改名为 overdue_label
        self.return_label = QLabel("0 本书")

        # ⭐ 修改这里：将"待归还"改为"逾期数"
        for text, label in [("已借阅", self.borrow_label), ("逾期数", self.overdue_label), ("已归还", self.return_label)]:
            card = QFrame()
            card.setFixedSize(170, 88)
            card.setStyleSheet("background:white;border:1px solid #D6E5D8;border-radius:18px;")
            layout = QVBoxLayout(card)
            title_label = QLabel(text)
            title_label.setAlignment(Qt.AlignCenter)
            title_label.setStyleSheet(f"font-weight:700;font-size:18px;color:{GREEN};")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-size:24px;font-weight:500;color:#333333;")
            layout.addWidget(title_label)
            layout.addWidget(label)
            top.addWidget(card)

        v.addLayout(top)
        v.addSpacing(8)

    

        # 表格：7列
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["用户ID", "借阅图书", "借阅时间", "应归还时间", "状态", "续借次数", "操作"])
        self.table.setMinimumSize(560, 170)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setStyleSheet("""
            QTableWidget{background:white;border:1px solid #D6E5D8;border-radius:12px;}
            QHeaderView::section{background:#EEF5EF;font-size:16px;font-weight:600;padding:8px;}
        """)
        v.addWidget(self.table, alignment=Qt.AlignCenter)
        v.addStretch()

        self.load_data()
        self.update_statistics()

    def load_data(self):
        """加载借阅记录"""
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()

            sql = """
            SELECT 
                br.user_id,
                br.book_name,
                br.borrow_date,
                br.due_date,
                br.is_returned,
                br.is_overdue,
                br.extension_count,
                br.id
            FROM borrow_records br
            ORDER BY br.id DESC
            """
            cursor.execute(sql)
            results = cursor.fetchall()

            self.table.setRowCount(len(results))

            for row, data in enumerate(results):
                self.table.setItem(row, 0, QTableWidgetItem(str(data[0])))
                self.table.setItem(row, 1, QTableWidgetItem(str(data[1])))
                
                # 处理日期时间格式
                borrow_date = data[2]
                due_date = data[3]
                
                if borrow_date:
                    if isinstance(borrow_date, datetime):
                        self.table.setItem(row, 2, QTableWidgetItem(borrow_date.strftime('%Y-%m-%d %H:%M')))
                    else:
                        self.table.setItem(row, 2, QTableWidgetItem(str(borrow_date)))
                else:
                    self.table.setItem(row, 2, QTableWidgetItem(''))
                    
                if due_date:
                    if isinstance(due_date, datetime):
                        self.table.setItem(row, 3, QTableWidgetItem(due_date.strftime('%Y-%m-%d %H:%M')))
                    else:
                        self.table.setItem(row, 3, QTableWidgetItem(str(due_date)))
                else:
                    self.table.setItem(row, 3, QTableWidgetItem(''))
                        
                # 状态显示
                is_returned = data[4]
                is_overdue = data[5]
                
                if is_returned == 1:
                    status_text = "✅ 已归还"
                elif is_overdue == 1:
                    status_text = "⚠️ 已逾期"
                else:
                    status_text = "📖 借阅中"
                self.table.setItem(row, 4, QTableWidgetItem(status_text))
                self.table.setItem(row, 5, QTableWidgetItem(str(data[6])))
                
                # ========== 操作按钮逻辑 ==========
                if is_returned == 0:  # 未归还
                    if is_overdue == 1:
                        # 逾期状态 - 红色可点击按钮
                        btn = QPushButton("⚠️ 逾期处理")
                        btn.setStyleSheet("""
                            QPushButton{
                                background: #DC3545;
                                color: white;
                                border: none;
                                border-radius: 8px;
                                padding: 6px;
                                font-weight: 600;
                            }
                            QPushButton:hover{
                                background: #C82333;
                            }
                        """)
                        btn.clicked.connect(lambda checked, rid=data[7], name=data[1]: self.handle_overdue(rid, name))
                        self.table.setCellWidget(row, 6, btn)
                    else:
                        # 未逾期 - 灰色不可点击
                        btn = QPushButton("📖 归还")
                        btn.setStyleSheet("""
                            QPushButton{
                                background: #2F5D50;
                                color: white;
                                border: none;
                                border-radius: 8px;
                                padding: 6px;
                                font-weight: 600;
                            }
                            QPushButton:hover{
                                background: #4F7A6D;
                            }
                        """)
                        btn.clicked.connect(lambda checked, rid=data[7], name=data[1]: self.return_book(rid, name))
                        self.table.setCellWidget(row, 6, btn)
                else:
                    # 已归还
                    label = QLabel("✅ 已归还")
                    label.setAlignment(Qt.AlignCenter)
                    label.setStyleSheet("color:#28A745;font-weight:600;")
                    self.table.setCellWidget(row, 6, label)

            cursor.close()
            conn.close()
        except Exception as e:
            print("加载失败:", e)
            import traceback
            traceback.print_exc()
    def update_statistics(self):
        """更新统计卡片数据"""
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()

            # 借阅中（未归还）
            cursor.execute("SELECT COUNT(*) FROM borrow_records WHERE is_returned = 0")
            borrowing = cursor.fetchone()[0]

            # 逾期（未归还且已逾期）
            cursor.execute("SELECT COUNT(*) FROM borrow_records WHERE is_returned = 0 AND is_overdue = 1")
            overdue = cursor.fetchone()[0]

            # 已归还
            cursor.execute("SELECT COUNT(*) FROM borrow_records WHERE is_returned = 1")
            returned = cursor.fetchone()[0]

            self.borrow_label.setText(f"{borrowing} 本书")
            self.overdue_label.setText(f"{overdue} 本书")
            self.return_label.setText(f"{returned} 本书")

            cursor.close()
            conn.close()

        except Exception as e:
            print("统计失败:", e)

    def refresh(self):
        """刷新表格和统计数据"""
        self.table.setRowCount(0)
        self.load_data()
        self.update_statistics()

    def return_book(self, record_id, book_name):
        """归还书籍 - 利用数据库触发器自动更新库存"""
        reply = show_dialog(
            self,
            "归还确认",
            f"确认要归还《{book_name}》吗？",
            buttons=("确认归还", "取消")
        )

        if reply == 1:
            conn = None
            cursor = None
            try:
                conn = db_pool.get_connection()
                cursor = conn.cursor()
                
                now = datetime.now()
                
                # 更新借阅记录（触发器会自动更新books表的库存）
                sql = """
                UPDATE borrow_records 
                SET is_returned = 1, actual_return_date = %s
                WHERE id = %s AND is_returned = 0
                """
                cursor.execute(sql, (now, record_id))
                conn.commit()
                
                if cursor.rowcount > 0:
                    show_dialog(self, "归还成功", f"《{book_name}》归还成功！")
                    self.refresh()
                else:
                    show_dialog(self, "归还失败", "未找到该借阅记录或书籍已归还")
                    
            except Exception as e:
                show_dialog(self, "归还失败", f"数据库错误：{str(e)}")
                print(f"归还失败：{e}")
                
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

    def handle_overdue(self, record_id, book_name):
        """处理逾期书籍"""
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            # 获取逾期天数
            cursor.execute("""
                SELECT DATEDIFF(NOW(), due_date) AS overdue_days
                FROM borrow_records 
                WHERE id = %s
            """, (record_id,))
            result = cursor.fetchone()
            overdue_days = result[0] if result else 0
            
        except Exception as e:
            print(f"获取逾期天数失败: {e}")
            overdue_days = 0
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        
        reply = show_dialog(
            self,
            "⚠️ 逾期处理",
            f"《{book_name}》已逾期 {overdue_days} 天！\n\n请选择操作：\n\n1. 归还书籍（自动计算逾期费）\n2. 续借书籍（需在逾期7天内）",
            buttons=("📖 归还并缴费", "🔄 续借")
        )

        if reply == 1:
            self.return_overdue_book(record_id, book_name, overdue_days)
        else:
            self.renew_overdue_book(record_id, book_name)

    def return_overdue_book(self, record_id, book_name, overdue_days):
        """归还逾期书籍"""
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            now = datetime.now()
            
            # 计算逾期费用（每天0.5元）
            fine = overdue_days * 0.5 if overdue_days > 0 else 0
            
            # 更新记录（触发器会自动更新books表）
            sql = """
            UPDATE borrow_records 
            SET is_returned = 1, actual_return_date = %s
            WHERE id = %s AND is_returned = 0
            """
            cursor.execute(sql, (now, record_id))
            conn.commit()
            
            if cursor.rowcount > 0:
                msg = f"《{book_name}》归还成功！"
                if fine > 0:
                    msg += f"\n\n逾期天数：{overdue_days} 天\n逾期费用：¥{fine:.2f}"
                show_dialog(self, "归还成功", msg)
                self.refresh()
            else:
                show_dialog(self, "归还失败", "未找到该借阅记录或书籍已归还")
                
        except Exception as e:
            show_dialog(self, "归还失败", f"数据库错误：{str(e)}")
            print(f"归还失败：{e}")
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def renew_overdue_book(self, record_id, book_name):
        """续借逾期书籍（仅限逾期7天内）"""
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            # 获取当前记录
            cursor.execute("""
                SELECT due_date, extension_count, DATEDIFF(NOW(), due_date) AS overdue_days
                FROM borrow_records 
                WHERE id = %s AND is_returned = 0
            """, (record_id,))
            result = cursor.fetchone()
            
            if not result:
                show_dialog(self, "续借失败", "未找到该借阅记录")
                return
            
            due_date = result[0]
            extension_count = result[1] if result[1] else 0
            overdue_days = result[2] if result[2] else 0
            
            # 检查是否可续借
            if overdue_days > 7:
                show_dialog(
                    self, 
                    "续借失败", 
                    f"该书已逾期 {overdue_days} 天，超过7天无法续借\n\n请前往图书馆归还并缴纳逾期费用。"
                )
                return
            
            # 检查续借次数（最多3次）
            if extension_count >= 3:
                show_dialog(self, "续借失败", "该书已续借3次，无法再次续借")
                return
            
            # 执行续借：延长30天
            new_due_date = due_date + timedelta(days=30) if isinstance(due_date, datetime) else datetime.now() + timedelta(days=30)
            
            sql = """
            UPDATE borrow_records 
            SET due_date = %s, extension_count = extension_count + 1
            WHERE id = %s
            """
            cursor.execute(sql, (new_due_date, record_id))
            conn.commit()
            
            show_dialog(
                self, 
                "续借成功", 
                f"《{book_name}》续借成功！\n\n新的应归还日期：{new_due_date.strftime('%Y-%m-%d %H:%M')}"
            )
            self.refresh()
                
        except Exception as e:
            show_dialog(self, "续借失败", f"数据库错误：{str(e)}")
            print(f"续借失败：{e}")
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

class ExpandLineEdit(QLineEdit):        #ai
    focused = Signal()

    def focusInEvent(self, event):
        self.focused.emit()
        super().focusInEvent(event)

class VoiceWorker(QThread):
    """后台跑「录音 → 识别 → 问答」全链路, 不阻塞界面。

    除结果外还回传两个信号给界面做交互反馈:
        level : 0.0~1.0 实时音量(驱动麦克风电平环)
        stage : recording / recognizing / thinking(驱动阶段指示)
    """

    finished = Signal(str, str)
    error = Signal(str)
    level = Signal(float)
    stage = Signal(str)

    def __init__(self, seconds=8, auto_stop=True, max_seconds=10.0,
                 stop_event=None):
        super().__init__()
        self.seconds = seconds
        self.auto_stop = auto_stop
        self.max_seconds = max_seconds
        self._stop_event = stop_event

    def request_stop(self):
        """界面「再点一下结束」时调用: 让录音循环尽快收尾。"""
        if self._stop_event is not None:
            self._stop_event.set()

    def run(self):

        try:

            from voice_manager import VoiceManager

            manager = VoiceManager()

            text, answer = manager.voice_chat(
                seconds=self.seconds,
                auto_stop=self.auto_stop,
                max_seconds=self.max_seconds,
                on_level=self.level.emit,
                on_stage=self.stage.emit,
                stop_check=(self._stop_event.is_set
                            if self._stop_event is not None else None),
            )

            self.finished.emit(text, answer)

        except Exception as e:

            self.error.emit(str(e))


class AskWorker(QThread):
    """纯文字提问(打字 / 快捷短语)的后台线程, 复用同一条问答链路。"""

    finished = Signal(str, str)
    error = Signal(str)

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):

        try:

            from book_chat import book_chat

            answer = book_chat(self.text)

            self.finished.emit(self.text, answer)

        except Exception as e:

            self.error.emit(str(e))


class TTSWorker(QThread):
    """把一段文本交给语音播报(后台线程, 不阻塞界面)。"""

    failed = Signal(str)
    done = Signal()

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):

        try:

            import tts

            ok, msg = tts.speak(self.text)

            if not ok:

                self.failed.emit(msg)

            else:

                self.done.emit()

        except Exception as e:

            self.failed.emit(str(e))


class RobotPage(QWidget):
    def __init__(self):
        super().__init__()

        main = QVBoxLayout(self)

        # 整体下移
        main.addStretch()

        # 外层容器
        container = QFrame()
        container.setFixedSize(590, 320)

        container.setStyleSheet("""
            QFrame{
                background:white;
                border:1px solid #D6E5D8;
                border-radius:20px;
            }
        """)

        h = QHBoxLayout(container)

        # =====================
        # 左侧历史记录
        # =====================
        left = QListWidget()
        left.setFixedWidth(190)

        left.addItems([
            "➕ 新建聊天",
            "Python推荐",
            "借阅咨询",
            "馆藏查询"
        ])

        left.setStyleSheet("""
            QListWidget{
                font-size:18px;
                border:none;
                background:#F8FAF8;
                border-radius:15px;
            }

            QListWidget::item{
                padding:15px;
            }
        """)

        h.addWidget(left)

        # =====================
        # 右侧聊天区域
        # =====================
        right = QVBoxLayout()

        title = QLabel("🤖 Library AI")
        title.setAlignment(Qt.AlignCenter)

        title.setStyleSheet("""
            font-size:32px;
            font-weight:700;
            color:#2F5D50;
        """)

        # 聊天记录
        self.chat = QTextBrowser()
        self.chat.anchorClicked.connect(self.play_tts)

        self.chat.setText("Library AI ")
        self.chat.setReadOnly(True)

        self.chat.setStyleSheet("""
            QTextEdit{
                font-size:18px;
                border:1px solid #D6E5D8;
                border-radius:15px;
                padding:15px;
                background:white;
            }
        """)

        # 输入框
        # =====================
        # 输入区域
        # =====================

        input_layout = QHBoxLayout()

        # 输入框
        self.input = QLineEdit()

        self.input.setPlaceholderText("💬 输入内容...")

        self.input.setFixedHeight(40)

        self.input.returnPressed.connect(self.send_message)

        self.input.setStyleSheet("""
            QLineEdit{
                font-size:18px;
                padding-left:20px;
                border:2px solid #D6E5D8;
                border-radius:27px;
                background:white;
            }

            QLineEdit:focus{
                border:2px solid #2F5D50;
            }
        """)


        # 语音按钮
        self.voice_btn = QPushButton("🎤")

        self.voice_btn.setFixedSize(42, 42)

        self.voice_btn.setToolTip("语音输入")

        self.voice_btn.setStyleSheet("""
            QPushButton{
                font-size:24px;
                border:2px solid #D6E5D8;
                border-radius:27px;
                background:white;
            }

            QPushButton:hover{
                background:#EEF5EF;
            }

            QPushButton:pressed{
                background:#D6E5D8;
            }
        """)

        self.voice_btn.clicked.connect(self.voice_message)


        input_layout.addWidget(self.input)
        input_layout.addWidget(self.voice_btn)

        self.input.setStyleSheet("""
            QLineEdit{
                font-size:18px;
                padding-left:20px;
                border:2px solid #D6E5D8;
                border-radius:27px;
                background:white;
            }

            QLineEdit:focus{
                border:2px solid #2F5D50;
            }
        """)

        right.addWidget(title)
        right.addSpacing(15)
        right.addWidget(self.chat)
        right.addSpacing(15)
        right.addLayout(input_layout)

        h.addLayout(right)

        main.addWidget(container, alignment=Qt.AlignCenter)
        main.addStretch()

    
    def send_message(self):
        """
        发送消息给图书馆智能助手
        GUI -> book_chat -> AI / 图书查询 / 借还功能
        """

        question = self.input.text().strip()

        if not question:
            return

        # 显示用户消息
        self.chat.append(
            f"\n👤 用户：{question}"
        )

        try:
            # 统一通过 book_chat 处理用户请求
            # book_chat 会自动判断：
            # 1. 普通问题 -> AI
            # 2. 找书问题 -> MySQL
            # 3. 借书 -> 借书功能（目前暂未接数据库）
            # 4. 还书 -> 还书功能（目前暂未接数据库）
            from book_chat import book_chat

            answer = book_chat(question)

            # 记住最后一条回答, 供"🔊 播放"按钮使用
            self._last_answer = answer

            # 显示助手回复
            # 显示助手回复 + 语音按钮
            self.chat.append(
                f"""
                <p>🤖 <b>Library AI：</b></p>
                <p>{answer}</p>
                <p><a href="tts_test">🔊 播放</a></p>
                """
            )

        except Exception as e:

            self.chat.append(
                f"\n❌ AI调用失败：{e}"
            )

        # 清空输入框
        self.input.clear()
    
    def play_tts(self, url):
        """点击"🔊 播放": 把最近一条回答交给 hobot_tts 播报。

        后台线程执行, 失败时把原因贴回聊天区 ——
        旧实现只是 setSource(QUrl()), 点了没有任何反应。
        """
        self.chat.setSource(QUrl())

        text = (getattr(self, '_last_answer', '') or '').strip()

        if not text:

            self.chat.append("\n❌ 还没有可播放的回答")
            return

        self.tts_worker = TTSWorker(text)

        self.tts_worker.failed.connect(
            lambda m: self.chat.append(f"\n❌ 语音播报失败：{m}")
        )

        self.tts_worker.start()

    def voice_message(self):

        self.voice_btn.setEnabled(False)

        self.chat.append(
            "\n🎤 正在录音，请说话..."
        )

        self.voice_worker = VoiceWorker(seconds=5)

        self.voice_worker.finished.connect(
            self.voice_finished
        )

        self.voice_worker.error.connect(
            self.voice_error
        )

        self.voice_worker.start()    

    def voice_finished(self, text, answer):

        if not text:

            self.chat.append(
                "\n❌ 没有识别到语音"
            )

            self.voice_btn.setEnabled(True)
            return

        # 显示用户说的话
        self.chat.append(
            f"\n👤 你：{text}"
        )

        # 显示 AI 回答
        self._last_answer = answer

        self.chat.append(
            f"""
            <p>🤖 <b>Library AI：</b></p>
            <p>{answer}</p>
            <p><a href="tts_test">🔊 播放</a></p>
            """
        )

        self.voice_btn.setEnabled(True)

    def voice_error(self, error):

        self.chat.append(
            f"\n❌ 语音 AI 调用失败：{error}"
        )

        self.voice_btn.setEnabled(True)




class MicButton(QWidget):
    """圆形麦克风按钮 —— 语音交互页的核心控件。

    三种状态:
        idle      深绿, 待机
        listening 红色 + 呼吸脉冲环 + 实时音量环
        busy      橙色, 正在识别 / 思考
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 132)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('点一下开始说话；再点一下提前结束')
        self._state = 'idle'
        self._pulse = 0.0
        self._level = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_state(self, state):
        if state != self._state:
            self._state = state
            if state != 'listening':
                self._pulse = 0.0
        self.update()

    def set_level(self, level):
        """0.0~1.0 的实时音量, 做一点下坠平滑, 看起来更像真的在听。"""
        level = 0.0 if level < 0 else (1.0 if level > 1 else level)
        self._level = max(level, self._level * 0.65)
        self.update()

    def _tick(self):
        self._phase += 0.16
        if self._state == 'listening':
            self._pulse = (math.sin(self._phase) + 1.0) / 2.0
        else:
            self._pulse *= 0.88
            self._level *= 0.85
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        center = QPointF(cx, cy)
        r = min(self.width(), self.height()) / 2.0 - 4

        # 呼吸脉冲环(仅聆听时)
        if self._state == 'listening':
            ring = r * (0.86 + 0.14 * self._pulse)
            p.setPen(QPen(QColor(231, 76, 60, 110), 4))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(center, ring, ring)

        # 实时音量环
        if self._level > 0.03:
            ring = r * (0.70 + 0.28 * min(1.0, self._level))
            p.setPen(QPen(QColor('#27AE60'), 3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(center, ring, ring)

        body_r = r * 0.66
        color = {
            'listening': QColor('#E74C3C'),
            'busy': QColor('#F39C12'),
        }.get(self._state, QColor('#2F5D50'))
        grad = QLinearGradient(cx, cy - body_r, cx, cy + body_r)
        grad.setColorAt(0.0, color.lighter(120))
        grad.setColorAt(1.0, color)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(center, body_r, body_r)

        # 简笔麦克风图标
        p.setPen(QPen(QColor(255, 255, 255, 235), 3))
        p.setBrush(Qt.NoBrush)
        mw = body_r * 0.30
        p.drawRoundedRect(
            QRectF(cx - mw / 2.0, cy - mw * 1.35, mw, mw * 2.0),
            mw / 2.0, mw / 2.0)
        p.drawArc(
            QRectF(cx - mw * 1.05, cy - mw * 1.05, mw * 2.1, mw * 2.3),
            int(200 * 16), int(140 * 16))
        p.drawLine(QPointF(cx, cy + mw * 1.25), QPointF(cx, cy + mw * 1.75))
        p.drawLine(QPointF(cx - mw * 0.62, cy + mw * 1.75),
                   QPointF(cx + mw * 0.62, cy + mw * 1.75))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class VoicePage(QWidget):
    """🎤 语音交互页

    交互设计:
      * 大圆麦克风: 点一下开始说话, 检测到说完自动停, 也能再点一下提前结束;
      * 说话时红色呼吸环 + 绿色实时音量环 —— 肉眼可见「麦克风在听」;
      * 阶段指示条: 录音 → 识别 → 思考 → 播报, 当前阶段高亮;
      * 对话区保留多轮上下文, 回答可自动播报 / 一键重播;
      * 快捷短语 + 打字提问: 没有麦克风也能用同一条问答链路。
    """

    STAGES = (
        ('recording', '🎙 录音'),
        ('recognizing', '📝 识别'),
        ('thinking', '🧠 思考'),
        ('speaking', '🔊 播报'),
    )
    MAX_RECORD_SECONDS = 10

    def __init__(self):
        super().__init__()
        self._worker = None
        self._ask_worker = None
        self._tts_worker = None
        self._stop_event = None
        self._last_answer = ''
        self._rec_seconds = 0.0
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(100)
        self._rec_timer.timeout.connect(self._tick_record)
        self._build_ui()
        self._set_stage(None)

    # --------------------------------------------------------------
    # 界面
    # --------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel('🎤 语音助手')
        title.setStyleSheet('font-size:20px;font-weight:800;color:#2F5D50;')
        head.addWidget(title)
        head.addStretch(1)
        self.status = QLabel('待机 · 点麦克风开始说话')
        head.addWidget(self.status)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)

        # ---------- 左列: 麦克风 + 阶段 ----------
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addStretch(1)

        self.mic = MicButton()
        self.mic.clicked.connect(self.on_mic_clicked)
        left.addWidget(self.mic, alignment=Qt.AlignHCenter)

        self.mic_hint = QLabel('点击说话')
        self.mic_hint.setAlignment(Qt.AlignCenter)
        self.mic_hint.setStyleSheet('color:#2F5D50;font-weight:700;')
        left.addWidget(self.mic_hint)

        step = QHBoxLayout()
        step.setSpacing(4)
        self.stage_labels = {}
        for key, name in self.STAGES:
            lb = QLabel(name)
            lb.setAlignment(Qt.AlignCenter)
            self.stage_labels[key] = lb
            step.addWidget(lb)
        left.addLayout(step)

        self.elapsed = QLabel(f'最长可说 {self.MAX_RECORD_SECONDS} 秒')
        self.elapsed.setAlignment(Qt.AlignCenter)
        self.elapsed.setStyleSheet('color:#6B7280;font-size:12px;')
        left.addWidget(self.elapsed)

        self.auto_speak = QCheckBox('回答后自动播报')
        self.auto_speak.setChecked(True)
        left.addWidget(self.auto_speak, alignment=Qt.AlignHCenter)

        # 小工具行放左侧窄列：右侧留给对话区，避免把整页最小宽度撑大
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.replay_btn = QPushButton('🔊 重播')
        self.replay_btn.clicked.connect(self.replay_answer)
        clear_btn = QPushButton('🧹 清空')
        clear_btn.clicked.connect(self.clear_chat)
        for b in (self.replay_btn, clear_btn):
            b.setFixedHeight(28)
            b.setStyleSheet(
                'QPushButton{background:white;border:1px solid #D6E5D8;'
                'border-radius:10px;padding:0 8px;}'
                'QPushButton:hover{background:#EEF5EF;}')
            tools.addWidget(b)
        left.addLayout(tools)

        left.addStretch(1)
        body.addLayout(left, 0)

        # ---------- 右列: 对话 ----------
        right = QVBoxLayout()
        right.setSpacing(6)

        self.chat = QTextBrowser()
        self.chat.setOpenLinks(False)
        self.chat.anchorClicked.connect(self._on_anchor)
        self.chat.setHtml(self._welcome_html())
        right.addWidget(self.chat, 1)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('也可以打字提问，例如：三体在哪')
        self.input.returnPressed.connect(self.on_send_text)
        row.addWidget(self.input, 1)
        send = QPushButton('发送')
        send.setFixedHeight(34)
        send.setStyleSheet(
            'background:#2F5D50;color:white;border-radius:10px;'
            'font-weight:700;padding:0 16px;')
        send.clicked.connect(self.on_send_text)
        row.addWidget(send)
        right.addLayout(row)

        quick = QHBoxLayout()
        quick.setSpacing(6)
        for phrase in ('三体在哪', 'Python 的书', '你好'):
            b = QPushButton(phrase)
            b.setFixedHeight(30)
            b.setStyleSheet(
                'QPushButton{background:#EEF5EF;border:1px solid #D6E5D8;'
                'border-radius:10px;color:#2F5D50;font-weight:600;'
                'padding:0 10px;}'
                'QPushButton:hover{background:#D6E5D8;}')
            b.clicked.connect(lambda _=False, t=phrase: self._ask_text(t))
            quick.addWidget(b)
        quick.addStretch(1)
        right.addLayout(quick)

        body.addLayout(right, 1)
        root.addLayout(body, 1)

    # --------------------------------------------------------------
    # 状态 / 阶段
    # --------------------------------------------------------------
    def _welcome_html(self):
        return (
            '<div style="color:#374151;font-size:13px;">'
            '<p>👋 我是图书馆机器人，可以问我：</p>'
            '<p>· 「三体在哪」 —— 查书并带路<br>'
            '· 「有没有 Python 的书」 —— 查馆藏<br>'
            '· 「你好」 —— 随便聊聊</p>'
            '<p style="color:#6B7280;">点左边大按钮说话，'
            '或直接在下面打字。</p>'
            '</div>')

    def _set_stage(self, active):
        colors = {
            'recording': ('#E74C3C', '#FDECEA'),
            'recognizing': ('#2980B9', '#EAF2FB'),
            'thinking': ('#F39C12', '#FEF5E7'),
            'speaking': ('#27AE60', '#EAF7F0'),
        }
        for key, _name in self.STAGES:
            lb = self.stage_labels[key]
            if key == active:
                fg, bg = colors[key]
                lb.setStyleSheet(
                    f'background:{bg};color:{fg};border:1px solid {fg};'
                    f'border-radius:9px;padding:2px 6px;font-size:11px;'
                    f'font-weight:800;')
            else:
                lb.setStyleSheet(
                    'color:#9CA3AF;border:1px solid #E5E7EB;'
                    'border-radius:9px;padding:2px 6px;font-size:11px;')

    def _set_status(self, text, kind='idle'):
        palette = {
            'idle': ('#EEF5EF', '#2F5D50', '#D6E5D8'),
            'live': ('#FDECEA', '#B03A2E', '#E74C3C'),
            'work': ('#FEF5E7', '#9C640C', '#F39C12'),
            'done': ('#EAF7F0', '#1E7A50', '#27AE60'),
            'err': ('#FDECEA', '#922B21', '#E74C3C'),
        }
        bg, fg, bd = palette.get(kind, palette['idle'])
        self.status.setText(text)
        self.status.setStyleSheet(
            f'background:{bg};color:{fg};border:1px solid {bd};'
            f'border-radius:12px;padding:3px 12px;font-weight:600;')

    # --------------------------------------------------------------
    # 麦克风
    # --------------------------------------------------------------
    def on_mic_clicked(self):
        if self._worker is not None and self._worker.isRunning():
            # 再点一下 = 提前结束
            self._worker.request_stop()
            self.mic_hint.setText('正在结束…')
            return
        self.start_listen()

    def start_listen(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if self._ask_worker is not None and self._ask_worker.isRunning():
            return

        self._stop_event = threading.Event()
        self._worker = VoiceWorker(
            seconds=self.MAX_RECORD_SECONDS,
            auto_stop=True,
            max_seconds=float(self.MAX_RECORD_SECONDS),
            stop_event=self._stop_event,
        )
        self._worker.level.connect(self.mic.set_level)
        self._worker.stage.connect(self._on_worker_stage)
        self._worker.finished.connect(self._on_voice_result)
        self._worker.error.connect(self._on_worker_error)

        self.mic.set_state('listening')
        self.mic_hint.setText('正在聆听…说完自动停，或再点一下结束')
        self._set_status('聆听中…', 'live')
        self._set_stage('recording')
        self._rec_seconds = 0.0
        self._rec_timer.start()
        self._append('<p style="color:#B03A2E;">🎙 <b>正在录音…</b></p>')
        self._worker.start()

    def _tick_record(self):
        self._rec_seconds += 0.1
        self.elapsed.setText(
            f'已录 {self._rec_seconds:.1f}s / 最长 {self.MAX_RECORD_SECONDS}s')

    def _on_worker_stage(self, stage):
        self._set_stage(stage)
        if stage == 'recording':
            return
        self._rec_timer.stop()
        self.mic.set_state('busy')
        if stage == 'recognizing':
            self.mic_hint.setText('识别中…')
            self._set_status('识别中…', 'work')
        elif stage == 'thinking':
            self.mic_hint.setText('思考中…')
            self._set_status('思考中…', 'work')

    def _on_voice_result(self, text, answer):
        self._rec_timer.stop()
        self.mic.set_state('idle')
        self.mic.set_level(0.0)
        self.elapsed.setText(f'最长可说 {self.MAX_RECORD_SECONDS} 秒')

        if not text:
            self.mic_hint.setText('没听清，点我再试一次')
            self._set_status('没听清 · 请再说一次', 'err')
            self._set_stage(None)
            self._append(
                '<p style="color:#922B21;">❌ 没有识别到语音，'
                '请靠近麦克风再说一次。</p>')
            self._scroll_end()
            return

        self.mic_hint.setText('点击说话')
        self._set_status('完成', 'done')
        self._append(
            f'<p style="color:#1F2937;">👤 <b>你：</b>'
            f'{html_escape(text)}</p>')
        self._show_answer(answer)

    def _on_worker_error(self, err):
        self._rec_timer.stop()
        self.mic.set_state('idle')
        self.mic_hint.setText('出错了，点我重试')
        self._set_status('出错', 'err')
        self._set_stage(None)
        self._append(
            f'<p style="color:#922B21;">❌ 语音链路出错：'
            f'{html_escape(err)}</p>')
        self._scroll_end()

    # --------------------------------------------------------------
    # 打字提问
    # --------------------------------------------------------------
    def on_send_text(self):
        self._ask_text(self.input.text().strip())

    def _ask_text(self, text):
        if not text:
            return
        running = (
            (self._worker is not None and self._worker.isRunning())
            or (self._ask_worker is not None and self._ask_worker.isRunning())
        )
        if running:
            return
        self.input.clear()
        self._append(
            f'<p style="color:#1F2937;">👤 <b>你：</b>'
            f'{html_escape(text)}</p>')
        self._set_status('思考中…', 'work')
        self.mic.set_state('busy')
        self._set_stage('thinking')
        self._ask_worker = AskWorker(text)
        self._ask_worker.finished.connect(self._on_ask_result)
        self._ask_worker.error.connect(self._on_worker_error)
        self._ask_worker.start()

    def _on_ask_result(self, _text, answer):
        self.mic.set_state('idle')
        self._set_status('完成', 'done')
        self._show_answer(answer)

    # --------------------------------------------------------------
    # 回答 & 播报
    # --------------------------------------------------------------
    def _show_answer(self, answer):
        self._last_answer = answer or ''
        self._append(
            f'<p style="color:#0F766E;">🤖 <b>Library AI：</b>'
            f'{html_escape(self._last_answer)}</p>'
            f'<p><a href="speak">🔊 播放这句话</a></p>')
        self._scroll_end()
        if self.auto_speak.isChecked() and self._last_answer:
            self.speak(self._last_answer)

    def replay_answer(self):
        if not self._last_answer:
            self._append('<p style="color:#6B7280;">还没有可播报的回答</p>')
            self._scroll_end()
            return
        self.speak(self._last_answer)

    def speak(self, text):
        self._set_stage('speaking')
        self._set_status('播报中…', 'work')
        self._tts_worker = TTSWorker(text)
        self._tts_worker.failed.connect(self._on_tts_failed)
        self._tts_worker.done.connect(self._on_tts_done)
        self._tts_worker.start()

    def _on_tts_done(self):
        self._set_stage(None)
        self._set_status('完成', 'done')

    def _on_tts_failed(self, msg):
        self._set_stage(None)
        self._append(
            f'<p style="color:#92400E;">⚠️ 语音播报不可用：'
            f'{html_escape(msg)}</p>')
        self._scroll_end()

    def _on_anchor(self, url):
        if url.toString() == 'speak':
            self.replay_answer()

    def clear_chat(self):
        self.chat.setHtml(self._welcome_html())
        self._last_answer = ''
        self._set_stage(None)
        self._set_status('待机 · 点麦克风开始说话', 'idle')

    # --------------------------------------------------------------
    # 小工具
    # --------------------------------------------------------------
    def _append(self, html_text):
        cursor = self.chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.chat.setTextCursor(cursor)
        self.chat.insertHtml(html_text)

    def _scroll_end(self):
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())


class BookDetailPage(QWidget):
    """书籍详情页"""
    def __init__(self, book_data=None):
        super().__init__()
        self.book_data = book_data
        self.init_ui()
    
    def init_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(18, 8, 18, 8)
        main.setSpacing(4)
        
        # 返回按钮
        back_btn = QPushButton("← 返回")
        back_btn.setFixedSize(100, 30)
        back_btn.setStyleSheet("""
            QPushButton{
                background: white;
                border: 1px solid #D6E5D8;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                color: #2F5D50;
            }
            QPushButton:hover{
                background: #EEF5EF;
            }
        """)
        back_btn.clicked.connect(self.go_back)
        main.addWidget(back_btn)
        
        main.addSpacing(10)
        
        # 标题
        title = QLabel("📖 书籍详情")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #2F5D50; margin-bottom: 6px;")
        main.addWidget(title)
        
        # 详情卡片
        card = QFrame()
        card.setStyleSheet("""
            QFrame{
                background: transparent;
                border: none;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(4)
        card_layout.setContentsMargins(20, 6, 20, 6)
        
        if self.book_data:
            # 书名
            book_name = QLabel(f"📕 《{self.book_data.get('book_name', '未知')}》")
            book_name.setStyleSheet("font-size: 16px; font-weight: 700; color: #1a1a1a; padding: 2px 0;")
            card_layout.addWidget(book_name)
            
            card_layout.addSpacing(5)
            
            # 作者
            author = QLabel(f"✍️ 作者：{self.book_data.get('author', '未知')}")
            author.setStyleSheet("font-size: 13px; color: #333; padding: 2px 0;")
            card_layout.addWidget(author)
            
            # 出版社
            publisher = QLabel(f"🏢 出版社：{self.book_data.get('publisher', '未知')}")
            publisher.setStyleSheet("font-size: 13px; color: #333; padding: 2px 0;")
            card_layout.addWidget(publisher)
            
            # ISBN
            isbn = QLabel(f"🔖 ISBN：{self.book_data.get('isbn', '未知')}")
            isbn.setStyleSheet("font-size: 13px; color: #333; padding: 2px 0;")
            card_layout.addWidget(isbn)
            
            # 豆瓣评分
            score = QLabel(f"⭐ 豆瓣评分：{self.book_data.get('douban_score', '暂无')}")
            score.setStyleSheet("font-size: 13px; color: #333; padding: 2px 0;")
            card_layout.addWidget(score)
            
            # 内容简介标题
            card_layout.addSpacing(10)
            desc_label = QLabel("📝 内容简介")
            desc_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #2F5D50; padding: 4px 0;")
            card_layout.addWidget(desc_label)
            
            # 内容简介
            description = self.book_data.get('description', '暂无简介')
            desc_text = QTextEdit()
            desc_text.setPlainText(description)
            desc_text.setReadOnly(True)
            desc_text.setFixedHeight(56)
            desc_text.setStyleSheet("""
                QTextEdit{
                    font-size: 16px;
                    border: none;
                    padding: 10px;
                    background: transparent;
                    color: #333;
                    line-height: 1.8;
                }
            """)
            card_layout.addWidget(desc_text)
            
            # ========== 按钮区：借阅 + 寻找图书 ==========
            card_layout.addSpacing(10)
            
            # 借阅按钮
            borrow_btn = QPushButton("📚 借阅此书")
            borrow_btn.setFixedSize(150, 30)
            borrow_btn.setStyleSheet("""
                QPushButton{
                    background: #2F5D50;
                    color: white;
                    border: none;
                    border-radius: 25px;
                    font-size: 16px;
                    font-weight: 600;
                }
                QPushButton:hover{
                    background: #4F7A6D;
                }
            """)
            borrow_btn.clicked.connect(self.borrow_book)
            
            # ⭐ 寻找图书按钮
            find_btn = QPushButton("🗺️ 寻找图书")
            find_btn.setFixedSize(150, 30)
            find_btn.setStyleSheet("""
                QPushButton{
                    background: #EEF5EF;
                    color: #2F5D50;
                    border: 2px solid #2F5D50;
                    border-radius: 25px;
                    font-size: 16px;
                    font-weight: 600;
                }
                QPushButton:hover{
                    background: #D6E5D8;
                }
            """)
            find_btn.clicked.connect(self.find_book_location)
            
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            btn_layout.addWidget(borrow_btn)
            btn_layout.addSpacing(12)
            btn_layout.addWidget(find_btn)
            btn_layout.addStretch()
            card_layout.addLayout(btn_layout)
        
        main.addWidget(card)
        main.addStretch()
    
    # ==================== 寻找图书（动态读取 MySQL 位置） ====================
    def find_book_location(self):
        """查位置 → 发给机器人 → 弹窗反馈"""
        book_name = self.book_data.get('book_name', '') if self.book_data else ''
        if not book_name:
            show_dialog(self, "查找失败", "未获取到书籍名称")
            return

        # ---------- 1. 查数据库拿位置 ----------
        location = None
        is_available = None

        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT location, is_available FROM books WHERE book_name = %s LIMIT 1",
                (book_name,),
            )
            result = cursor.fetchone()
            if result:
                location = result[0]
                is_available = result[1]
        except Exception as e:
            print(f"查询位置失败：{e}")
            show_dialog(self, "查询失败", f"数据库错误：{e}")
            return
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

        # ---------- 2. 把位置发给机器人 ----------
        # Moss 优化 (2026-09-23): 这里以前依赖数据库 location 字段拼 'A/B/C/D',
        # 实际书名×位置匹配几乎全是错的。统一走坐标派单:
        #  1) bookmarks.json 里取该书名的 goal_x/goal_y (主线)
        #  2) 没有锚点 → 用数据库 location 字符串当 “target name” 发送给机器人,
        #     由 goal_bridge 看到不在 A/B/C/D 表时拒收并提示
        from robot_comm import send_goto_xy, send_go_to
        bm = self._load_bookmarks()
        anchor = bm.get(book_name) if bm else None
        via = '坐标'
        if anchor and anchor.get('goal_x') is not None:
            ok, robot_msg = send_goto_xy(
                anchor['goal_x'], anchor['goal_y'],
                book_name=book_name)
        else:
            # 没有锚点时, 保留旧 fallback: 走 A/B/C/D 区号
            ok, robot_msg = send_go_to(location or "", book_name)
            via = '区号'
        print(f"派单方式: {via}; ok={ok}; message={robot_msg}", flush=True)
        print(f"机器人返回：ok={ok}, message={robot_msg}", flush=True)
        # ---------- 3. 弹窗反馈 ----------
        location_display = location if location else "暂未录入"
        status_text = ("✅ 当前可借阅" if is_available == 1
                       else "❌ 当前已借出" if is_available == 0
                       else "❓ 状态未知")

        if ok:
            body = (f"📍 目标位置：{location_display}\n\n"
                    f"{status_text}\n\n"
                    f"🤖 机器人已收到指令，请跟随指示灯前往。\n"
                    f"（派单方式: {via} | {robot_msg}）")
            title = "🤖 已通知机器人"
        else:
            body = (f"📍 目标位置：{location_display}\n\n"
                    f"{status_text}\n\n"
                    f"⚠️ 未能通知机器人：{robot_msg}\n"
                    f"请手动前往或联系管理员。")
            title = "⚠️ 机器人连接失败"

        box = QDialog(self)

        box.setWindowTitle(title)
        box.setWindowModality(Qt.ApplicationModal)
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        box.setFixedSize(500, 250)

        layout = QVBoxLayout(box)

        title_label = QLabel(f"《{book_name}》")
        title_label.setStyleSheet(
            "font-size: 24px; font-weight: bold;"
        )
        title_label.setWordWrap(True)

        body_label = QLabel(body)
        body_label.setStyleSheet(
            "font-size: 18px;"
        )
        body_label.setWordWrap(True)

        ok_button = QPushButton("知道了")
        ok_button.setFixedHeight(45)
        ok_button.setStyleSheet(
            "font-size: 18px;"
        )

        layout.addWidget(title_label)
        layout.addWidget(body_label)
        layout.addStretch()
        layout.addWidget(ok_button)

        ok_button.clicked.connect(box.accept)

        box.exec()
    
    # ==================== 借阅书籍 ====================
    def borrow_book(self):
        """借阅书籍 - 利用数据库触发器自动更新库存"""
        book_id = self.get_book_id_by_name(self.book_data.get('book_name'))
        
        if not book_id:
            show_dialog(self, "借阅失败", "未找到对应的书籍ID")
            return
        
        user_id = "20250001"  # 应从登录用户获取
        book_name = self.book_data.get('book_name', '')
        
        # 检查是否有可借的副本
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            # 检查库存
            cursor.execute("SELECT COUNT(*) FROM books WHERE book_name = %s AND is_available = 1", (book_name,))
            available_count = cursor.fetchone()[0]
            
            if available_count == 0:
                show_dialog(self, "借阅失败", f"《{book_name}》暂无可用副本")
                return
                
        except Exception as e:
            print(f"检查库存失败: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        
        # 确认对话框
        reply = show_dialog(
            self,
            "借阅确认",
            f"确认要借阅《{book_name}》吗？\n\n当前可用副本：{available_count} 本\n借阅期限为30天，请按时归还图书。",
            buttons=("确认借阅", "取消")
        )

        if reply != 1:
            return
        
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            # 获取一个可用的书籍ID
            cursor.execute("SELECT id FROM books WHERE book_name = %s AND is_available = 1 LIMIT 1", (book_name,))
            result = cursor.fetchone()
            
            if not result:
                show_dialog(self, "借阅失败", "该书籍已被借完")
                return
            
            book_id = result[0]
            borrow_date = datetime.now()
            due_date = borrow_date + timedelta(days=30)
            
            # 插入借阅记录（触发器会自动更新books表的库存）
            sql = """
            INSERT INTO borrow_records 
            (user_id, book_id, book_name, borrow_date, due_date, is_returned) 
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (user_id, book_id, book_name, borrow_date, due_date, 0))
            conn.commit()
            
            show_dialog(self, "借阅成功", f"成功借阅《{book_name}》！\n应还日期：{due_date.strftime('%Y-%m-%d %H:%M')}")
            
            # 刷新借阅中心
            main_window = self.window()
            if hasattr(main_window, 'borrow_page'):
                main_window.borrow_page.refresh()
                
        except Exception as e:
            print(f"借阅失败: {e}")
            show_dialog(self, "借阅失败", str(e))
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # ==================== 工具方法 ====================
    @staticmethod
    def _load_bookmarks():
        """读 maps/bookmarks.json, 返回 dict[书名] -> 锚点(无文件返回 None)."""
        import json, os
        try:
            bm_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..', 'maps', 'bookmarks.json')
            with open(bm_path, 'r', encoding='utf-8') as f:
                bm = json.load(f)
            return bm.get('books', {})
        except Exception:
            return None

    def get_book_id_by_name(self, book_name):
        """根据书名查找书籍ID"""
        if not book_name:
            return None
        
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            sql = "SELECT id FROM books WHERE book_name = %s LIMIT 1"
            cursor.execute(sql, (book_name,))
            result = cursor.fetchone()
            
            if result:
                return result[0]
            return None
            
        except Exception as e:
            print(f"查询书籍ID失败：{e}")
            return None
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def go_back(self):
        """返回图书查询页面"""
        main_window = self.window()
        if hasattr(main_window, 'stack'):
            # 移除当前详情页
            main_window.stack.removeWidget(self)
            # 切换到图书查询页面（索引1）
            main_window.stack.setCurrentIndex(1)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("图书馆机器人 V4")
        cw=QWidget();self.setCentralWidget(cw)
        root=QHBoxLayout(cw)

        nav=QFrame();nav.setFixedWidth(130)
        nav.setStyleSheet(f"background:{GREEN};border-radius:20px;")
        nv=QVBoxLayout(nav)

        ai=QPushButton("🤖\nLibrary AI\n智能助手在线")
        ai.setFixedHeight(110)
        ai.setStyleSheet("background:white;color:#111827;border-radius:16px;font-weight:700;")
        nv.addWidget(ai)

        self.stack=QStackedWidget()
        self.home_page = HomePage()
        self.search_page = SearchPage()
        self.borrow_page = BorrowPage()
        self.profile_page = ProfilePage()
        self.robot_page = RobotPage()
        self.voice_page = VoicePage()
        self.map_page = MapPage()

        pages=[
        ("主页面",self.home_page),
        ("图书查询",self.search_page),
        ("借阅管理",self.borrow_page),
        ("个人中心",self.profile_page),
        ("机器人",self.robot_page),
        ("语音助手",self.voice_page),
        ("地图",self.map_page)
        ]
        for _,p in pages:self.stack.addWidget(p)
        ai.clicked.connect(lambda:self.stack.setCurrentIndex(4))

        for i,(n,_) in enumerate(pages):
            b=QPushButton("■ "+n)
            b.clicked.connect(lambda checked=False,x=i:self.stack.setCurrentIndex(x))
            # padding 由 10px 收到 7px: 导航加到 7 项后, 原内边距会把
            # 主窗口最小高度顶到 440 (>480 屏可用的 436)
            b.setStyleSheet("QPushButton{color:white;background:transparent;border:none;text-align:left;padding:7px;font-size:11px;font-weight:600;}QPushButton:hover{background:#4F7A6D;border-radius:12px;}")
            nv.addWidget(b)
        nv.addStretch()

        root.addWidget(nav)
        root.addWidget(self.stack)

        self.setStyleSheet("""
        QWidget{background:#F5F8F6;color:#111827;font-family:'Microsoft YaHei UI';font-size:14px;}
        QLineEdit,QTextEdit,QListWidget,QTableWidget,QGroupBox{
        background:white;border:1px solid #D6E5D8;border-radius:14px;padding:6px;}
        QHeaderView::section{background:#F3F4F6;border:none;padding:8px;font-weight:600;}
        """)

        # ---- 窗口尺寸自适应 ----
        # 必须放在布局建好之后：提前 resize 会被布局的 sizeHint 覆盖，
        # 窗口被撑大（板载屏 800x480 上会被撑到 788x530）就会溢出屏幕。
        # 高度还要留出窗口管理器标题栏+边框（xfwm4 实测 29+5=34px），
        # 否则客户端尺寸没超，整个窗体仍会伸到屏幕外。
        screen = QApplication.primaryScreen().availableGeometry()
        win_w = min(1000, screen.width() - 20)
        win_h = min(700, screen.height() - 44)
        self.resize(win_w, win_h)
        self.move(
            screen.x() + max(0, (screen.width() - win_w) // 2),
            screen.y() + max(0, (screen.height() - win_h) // 2),
        )

class ProfilePage(QWidget):
    def __init__(self):
        super().__init__()

        main = QVBoxLayout(self)

        # 顶部留白
        main.addSpacing(10)

        # 标题
        title = QLabel("👤 个人中心")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            QLabel{
                font-size:22px;
                font-weight:700;
                color:#2F5D50;
            }
        """)
        main.addWidget(title)

        main.addSpacing(30)

        # ==========================
        # 用户信息卡片
        # ==========================
        card = QFrame()
        card.setFixedSize(580, 150)

        card.setStyleSheet("""
            QFrame{
                background:white;
                border:1px solid #D6E5D8;
                border-radius:20px;
            }
        """)

        h = QHBoxLayout(card)
        h.setContentsMargins(20, 16, 20, 16)

        # 头像
        avatar = QLabel("👤")
        avatar.setFixedSize(96,96)
        avatar.setAlignment(Qt.AlignCenter)

        avatar.setStyleSheet("""
            QLabel{
                background:#EEF5EF;
                border-radius:80px;
                font-size:60px;
            }
        """)

        # 信息
        info = QLabel("""
ID账号：20250001

姓名：张三

创建时间：2025-01-01

到期时间：2026-01-01

借阅书籍：12 本
""")

        info.setStyleSheet("""
            QLabel{
                font-size:14px;
                color:#333333;
                padding-left:20px;
            }
        """)

        h.addWidget(avatar)
        h.addWidget(info)

        main.addWidget(card, alignment=Qt.AlignCenter)

        main.addSpacing(30)

        # ==========================
        # 功能区
        # ==========================
        bottom = QHBoxLayout()
        bottom.setSpacing(30)
        bottom.setAlignment(Qt.AlignCenter)

        # 修改密码
        pwd_card = QPushButton(
            "🔒 修改密码\n\n修改登录密码"
        )

        pwd_card.setFixedSize(230,104)

        pwd_card.setStyleSheet("""
            QPushButton{
                background:white;
                border:1px solid #D6E5D8;
                border-radius:18px;
                font-size:20px;
                font-weight:600;
            }

            QPushButton:hover{
                background:#EEF5EF;
            }
        """)

        # 系统设置
        setting_card = QPushButton(
            "⚙️ 系统设置\n\n个性化设置"
        )

        setting_card.setFixedSize(230,104)

        setting_card.setStyleSheet("""
            QPushButton{
                background:white;
                border:1px solid #D6E5D8;
                border-radius:18px;
                font-size:20px;
                font-weight:600;
            }

            QPushButton:hover{
                background:#EEF5EF;
            }
        """)

        bottom.addWidget(pwd_card)
        bottom.addWidget(setting_card)

        main.addLayout(bottom)

        main.addStretch()

if __name__=="__main__":
    app=QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI",10))
    w=MainWindow();w.show()
    sys.exit(app.exec())