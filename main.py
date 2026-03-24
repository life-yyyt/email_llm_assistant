# -*- coding: utf-8 -*-
"""
基于 Llama3.2 1B 的本地智能邮件分类与回复助手 — 程序入口。
Windows + Python 3.10，完全离线，可打包为 .exe。
"""

import os
import sys

# 将项目根目录加入 path，保证 config、core、utils、ui 可被导入
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from ui.main_window import MainWindow


def main():
    # 高 DPI 支持（可选）
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("本地智能邮件助手")
    # 可选：统一字体
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
