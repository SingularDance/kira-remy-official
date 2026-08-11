# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 掷骰子小游戏（独立模块）

随机掷出 1-100 的数字。
"""

import random

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
)
from PyQt5.QtCore import Qt


class DiceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎲 掷骰子")
        self.setGeometry(300, 300, 300, 200)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("🎲 掷骰子 (1-100)")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.result_label = QLabel("点击下方按钮掷骰子")
        self.result_label.setStyleSheet("font-size: 24px; padding: 20px;")
        self.result_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.result_label)

        roll_btn = QPushButton("🎲 掷骰子")
        roll_btn.clicked.connect(self.roll)
        roll_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 30px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        layout.addWidget(roll_btn, alignment=Qt.AlignCenter)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("background-color: #888888; color: white; padding: 8px 20px; border-radius: 5px;")
        close_btn_layout = QHBoxLayout()
        close_btn_layout.addStretch()
        close_btn_layout.addWidget(close_btn)
        close_btn_layout.addStretch()
        layout.addLayout(close_btn_layout)

        self.setLayout(layout)

    def roll(self):
        num = random.randint(1, 100)
        self.result_label.setText(f"🎯 {num}")
