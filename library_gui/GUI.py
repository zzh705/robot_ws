import sys
import os

VOICE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "voice"
)

if VOICE_DIR not in sys.path:
    sys.path.insert(0, VOICE_DIR)

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import *
from PySide6.QtCore import Signal, QUrl, QThread
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
        
        # 地图按钮
        map_btn = QPushButton("🗺️ 地图")
        map_btn.setFixedHeight(50)
        map_btn.setStyleSheet("""
            QPushButton{
                background: #EEF5EF;
                border: 2px solid #D6E5D8;
                border-radius: 16px;
                font-size: 20px;
                font-weight: 600;
                color: #2F5D50;
            }
            QPushButton:hover{
                background: #D6E5D8;
                border-color: #2F5D50;
            }
        """)
        map_btn.clicked.connect(self.open_map)
        
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
  
        
        btn_layout.addWidget(map_btn)
        btn_layout.addWidget(find_btn)
        vbox.addLayout(btn_layout)
        
        # ⭐ 减少底部弹性空间，让整体上移
        root.addWidget(box, alignment=Qt.AlignCenter)
        root.addStretch(1)  # 减少弹性空间
        
        # 存储搜索结果
        self.search_results = []
    
    def open_map(self):
        """打开地图功能"""
        show_dialog(self, "地图", "图书馆地图功能开发中...\n\n📍 图书馆位于：天津市宝坻区北京科技大学天津学院")
        # 这里可以添加打开地图的实际功能
    
    
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

    finished = Signal(str, str)
    error = Signal(str)

    def __init__(self, seconds=5):
        super().__init__()
        self.seconds = seconds

    def run(self):

        try:

            from voice_manager import VoiceManager

            manager = VoiceManager()

            text, answer = manager.voice_chat(
                seconds=self.seconds
            )

            self.finished.emit(text, answer)

        except Exception as e:

            self.error.emit(str(e))


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
        print("点击了喇叭：", url.toString())

        # 阻止 QTextBrowser 继续处理这个链接
        self.chat.setSource(QUrl())

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
        from robot_comm import send_go_to
        ok, robot_msg = send_go_to(location or "", book_name)
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
                    f"（{robot_msg}）")
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

        pages=[
        ("主页面",self.home_page),
        ("图书查询",self.search_page),
        ("借阅管理",self.borrow_page),
        ("个人中心",self.profile_page),
        ("机器人",self.robot_page)
        ]
        for _,p in pages:self.stack.addWidget(p)
        ai.clicked.connect(lambda:self.stack.setCurrentIndex(4))

        for i,(n,_) in enumerate(pages):
            b=QPushButton("■ "+n)
            b.clicked.connect(lambda checked=False,x=i:self.stack.setCurrentIndex(x))
            b.setStyleSheet("QPushButton{color:white;background:transparent;border:none;text-align:left;padding:10px;font-size:11px;font-weight:600;}QPushButton:hover{background:#4F7A6D;border-radius:12px;}")
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