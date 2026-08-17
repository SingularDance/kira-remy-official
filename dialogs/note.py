# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 笔记对话框
"""

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QMessageBox
)
from PyQt5.QtCore import Qt

import config


class NoteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📝 记一笔")
        self.setGeometry(300, 300, 400, 200)
        self.setWindowOpacity(0.95)
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(255, 255, 255, 240);
                border-radius: 15px;
                border: 1px solid #DAAD69;
            }
            QLabel { color: #333333; font-family: 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif; }
            QTextEdit {
                background-color: rgba(245, 245, 245, 230);
                border: 1px solid #333333;
                border-radius: 8px;
                color: #333333;
                font-size: 14px;
                padding: 8px;
            }
            QPushButton {
                background-color: #DAAD69;
                color: #1a1a1a;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E0C080;
            }
            QPushButton#cancel {
                background-color: #aaaaaa;
            }
            QPushButton#cancel:hover {
                background-color: #999999;
            }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        label = QLabel("✏️ 输入你的灵感/笔记：")
        label.setStyleSheet("font-size: 14px;")
        layout.addWidget(label)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("在这里输入内容...")
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 保存")
        save_btn.clicked.connect(self.save_note)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def save_note(self):
        text = self.text_edit.toPlainText().strip()
        if text:
            config.save_note(text)
            QMessageBox.information(self, "成功", "✅ 笔记已保存！")
            self.accept()
        else:
            QMessageBox.warning(self, "提示", "⚠️ 内容不能为空！")
