# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 猜拳小游戏（独立模块）

石头剪刀布，与蕾咪对战。
"""

import random

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
)
from PyQt5.QtCore import Qt


class RPSDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✊ 猜拳")
        self.setGeometry(300, 300, 350, 250)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("✊ 猜拳对决")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.result_label = QLabel("选择你的出拳！")
        self.result_label.setStyleSheet("font-size: 16px; padding: 10px;")
        self.result_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.result_label)

        btn_layout = QHBoxLayout()
        for name, emoji in [("石头", "✊"), ("剪刀", "✌️"), ("布", "✋")]:
            btn = QPushButton(f"{emoji} {name}")
            btn.clicked.connect(lambda checked, n=name: self.play(n))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #333333;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background-color: #555555;
                }
            """)
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("background-color: #888888; color: white; padding: 8px 20px; border-radius: 5px;")
        close_btn_layout = QHBoxLayout()
        close_btn_layout.addStretch()
        close_btn_layout.addWidget(close_btn)
        close_btn_layout.addStretch()
        layout.addLayout(close_btn_layout)

        self.setLayout(layout)

    def play(self, player_choice):
        choices = ["石头", "剪刀", "布"]
        remy_choice = random.choice(choices)

        if player_choice == remy_choice:
            result = "平局！"
            emoji = "🤝"
        elif (player_choice == "石头" and remy_choice == "剪刀") or \
             (player_choice == "剪刀" and remy_choice == "布") or \
             (player_choice == "布" and remy_choice == "石头"):
            result = "你赢了！"
            emoji = "🎉"
        else:
            result = "蕾咪赢了！"
            emoji = "😤"

        self.result_label.setText(
            f"你出 {player_choice}  vs  Remy出 {remy_choice}\n\n{emoji} {result}"
        )
