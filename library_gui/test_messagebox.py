import sys

from PySide6.QtWidgets import QApplication, QMessageBox


app = QApplication(sys.argv)

box = QMessageBox()
box.setWindowTitle("弹窗测试")
box.setText("如果你能看到这个窗口，说明 Qt 弹窗正常。")
box.setInformativeText("这是独立测试，不涉及 GUI、MySQL 和机器人通信。")
box.setStandardButtons(QMessageBox.Ok)

box.show()
box.raise_()
box.activateWindow()

sys.exit(app.exec())