# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 调查员档案对话框
"""

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QMessageBox, QFormLayout
)
from PyQt5.QtCore import Qt

import config


class MasterProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("👤 调查员档案")
        self.setGeometry(200, 200, 400, 350)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif;")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("👤 调查员档案")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #DAAD69; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        form_layout = QFormLayout()
        form_layout.setSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignRight)

        self.nickname_input = QLineEdit(config.CONFIG.get('nickname', ''))
        self.nickname_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("昵称:", self.nickname_input)

        self.birthday_input = QLineEdit(config.CONFIG.get('master_birthday', ''))
        self.birthday_input.setPlaceholderText("如: 2000-01-01")
        self.birthday_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("生日:", self.birthday_input)

        self.call_input = QLineEdit(config.CONFIG.get('call_me', '你'))
        self.call_input.setPlaceholderText("如: 调查员、主人...")
        self.call_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("对我的称呼:", self.call_input)

        self.relationship_input = QLineEdit(config.CONFIG.get('relationship', '朋友'))
        self.relationship_input.setPlaceholderText("如: 朋友、恋人...")
        self.relationship_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("关系设定:", self.relationship_input)

        self.gender_input = QLineEdit(config.CONFIG.get('master_gender', '未知'))
        self.gender_input.setPlaceholderText("如: 男/女/未知")
        self.gender_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("性别:", self.gender_input)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 保存")
        save_btn.clicked.connect(self.save_profile)
        save_btn.setStyleSheet("background-color: #333333; color: white; padding: 8px 20px; border-radius: 5px;")
        btn_layout.addWidget(save_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("background-color: #888888; color: white; padding: 8px 20px; border-radius: 5px;")
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def save_profile(self):
        config.CONFIG['nickname'] = self.nickname_input.text().strip() or '调查员'
        config.CONFIG['master_birthday'] = self.birthday_input.text().strip() or '2000-01-01'
        config.CONFIG['call_me'] = self.call_input.text().strip() or '你'
        config.CONFIG['relationship'] = self.relationship_input.text().strip() or '朋友'
        config.CONFIG['master_gender'] = self.gender_input.text().strip() or '未知'

        config.save_config()

        QMessageBox.information(self, "成功", "✅ 调查员档案已保存！")
        self.accept()
