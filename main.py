"""MySQL 数据对比工具 —— 程序入口。

运行方式：
    pip install -r requirements.txt
    python main.py
"""
import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MySQL 数据对比工具")
    app.setOrganizationName("MySQLDiffTool")
    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
