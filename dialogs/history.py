# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 历史记录对话框
"""

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QWidget,
    QMessageBox, QSizePolicy
)
from PyQt5.QtCore import Qt

import config


class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📜 历史记录")
        self.setGeometry(200, 200, 500, 400)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.init_ui()
        self.refresh_list()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("📜 对话历史记录")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #DAAD69; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #f5f5f5;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px 5px;
                border-bottom: 1px solid #333333;
            }
            QListWidget::item:hover {
                background-color: #eeeeee;
            }
        """)
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.refresh_list)
        refresh_btn.setStyleSheet("background-color: #333333; color: white; padding: 5px 15px; border-radius: 5px;")
        btn_layout.addWidget(refresh_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("background-color: #DAAD69; color: #1a1a1a; padding: 5px 15px; border-radius: 5px;")
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def refresh_list(self):
        self.list_widget.clear()
        for i, entry in enumerate(config.CONVERSATION_HISTORY):
            item_text = f"[{entry['time']}] {entry['role']}: {entry['content']}"
            item = QListWidgetItem()
            item.setData(Qt.UserRole, i)

            widget = QWidget()
            widget_layout = QHBoxLayout()
            widget_layout.setContentsMargins(5, 2, 5, 2)

            label = QLabel(item_text)
            label.setStyleSheet("color: #333333;")
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

            del_btn = QPushButton("🗑️ 删除")
            del_btn.setStyleSheet("""
                QPushButton {
                    background-color: #DAAD69;
                    color: #1a1a1a;
                    border: none;
                    border-radius: 4px;
                    padding: 2px 10px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #E0C080;
                }
            """)
            del_btn.clicked.connect(lambda checked, idx=i: self.delete_entry(idx))

            widget_layout.addWidget(label)
            widget_layout.addWidget(del_btn)
            widget.setLayout(widget_layout)

            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def delete_entry(self, index):
        if 0 <= index < len(config.CONVERSATION_HISTORY):
            del config.CONVERSATION_HISTORY[index]
            config.save_conversation()
            self.refresh_list()
            QMessageBox.information(self, "成功", "✅ 记录已删除，Remy已遗忘此对话！")
