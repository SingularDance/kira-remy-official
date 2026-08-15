# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 关于对话框

展示当前版本号与关键信息（人设简介、发布页面）。
版本号实时读取 version.VERSION：每次打开对话框都重新读取，
所以更新重启后这里显示的就是新版本，不会残留旧值。

版本号为什么会「更新后自动变」：version.py 不在 downloader.PROTECTED_FILES
里，覆盖安装时会被新包里的 version.py / 新 exe 一起替换（见 self_update.py）。
前提是发版时先改 version.py 再打包——发版三件套（version.py 的 VERSION、
打包产物名、GitHub tag）必须一致，否则这里显示的版本和远端对不上。
"""

import webbrowser

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
)
from PyQt5.QtCore import Qt

import version


class AboutDialog(QDialog):
    """「关于」弹窗：显示当前版本号与发布信息。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ℹ️ 关于蕾咪")
        self.setGeometry(300, 300, 420, 300)
        self.setWindowOpacity(0.95)
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(255, 255, 255, 240);
                border-radius: 15px;
                border: 1px solid #DAAD69;
            }
            QLabel { color: #333333; font-family: Microsoft YaHei; }
            QLabel#title {
                font-size: 18px;
                font-weight: bold;
                color: #DAAD69;
            }
            QLabel#version {
                font-size: 24px;
                font-weight: bold;
                color: #1a1a1a;
            }
            QLabel#hint { color: #888888; font-size: 12px; }
            QPushButton {
                background-color: #DAAD69;
                color: #1a1a1a;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #E0C080; }
            QPushButton#cancel { background-color: #aaaaaa; }
            QPushButton#cancel:hover { background-color: #999999; }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        title = QLabel("星夜颂歌 · 蕾咪")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        version_label = QLabel(f"v{version.VERSION}")
        version_label.setObjectName("version")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        desc = QLabel("来自 5000 年后的天才少女舰长，阿斯忒瑞亚号的舰长。")
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        hint = QLabel("更新后版本号自动变化：程序重启后，这里显示的就是最新版本。")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_layout = QHBoxLayout()

        releases_btn = QPushButton("🌐 发布页")
        releases_btn.clicked.connect(self.open_releases_page)
        btn_layout.addWidget(releases_btn)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("cancel")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def open_releases_page(self):
        url = "https://github.com/{owner}/{repo}/releases".format(
            owner=version.GITHUB_OWNER, repo=version.GITHUB_REPO)
        webbrowser.open(url)
