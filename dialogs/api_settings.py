# -*- coding: utf-8 -*-
"""
Remy 桌宠 - API 设置对话框

首次启动引导 + 后续修改，支持主/备线路配置。
"""

import webbrowser

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QWidget, QMessageBox, QFormLayout
)
from PyQt5.QtCore import Qt

import config


class APISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔑 API 设置")
        self.setGeometry(200, 200, 550, 480)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.init_ui()
        self.load_current_config()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        title = QLabel("🔑 API 配置")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "蕾咪需要连接 AI 才能聊天哦。请在主线路中配置您的API Key。\n"
            "可在此页面中填写，或直接编辑项目目录里的 config.json。\n"
            "模板见 config.example.json（复制后改名为 config.json）。"
        )
        desc.setStyleSheet("color: #666666; font-size: 13px; padding: 0 10px;")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc)

        # === 主线路 ===
        primary_group = QWidget()
        primary_group.setStyleSheet("""
            QWidget {
                background-color: #fafaf5;
                border: 1px solid #DAAD69;
                border-radius: 10px;
            }
        """)
        pg_layout = QVBoxLayout(primary_group)
        pg_layout.setSpacing(8)

        pg_title = QLabel("🥇 主线路（优先使用）")
        pg_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #333333; border: none;")
        pg_layout.addWidget(pg_title)

        pg_form = QFormLayout()
        pg_form.setSpacing(8)

        self.primary_provider = QListWidget()
        self.primary_provider.setFixedHeight(80)
        self.primary_provider.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 3px;
                font-size: 13px;
            }
            QListWidget::item { padding: 4px 8px; }
            QListWidget::item:selected {
                background-color: #DAAD69;
                color: #1a1a1a;
            }
        """)
        for key, info in config.API_PROVIDERS.items():
            item = QListWidgetItem(f"{info['name']} — 模型: {info['model']}")
            item.setData(Qt.UserRole, key)
            self.primary_provider.addItem(item)
        self.primary_provider.setCurrentRow(0)
        pg_form.addRow("供应商:", self.primary_provider)

        key_layout = QHBoxLayout()
        self.primary_key_input = QLineEdit()
        self.primary_key_input.setPlaceholderText("粘贴你的 API Key...")
        self.primary_key_input.setEchoMode(QLineEdit.Password)
        self.primary_key_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                color: #333333;
            }
            QLineEdit:focus { border: 1px solid #DAAD69; }
        """)
        key_layout.addWidget(self.primary_key_input)

        show_btn = QPushButton("👁")
        show_btn.setFixedWidth(35)
        show_btn.setStyleSheet("""
            QPushButton {
                background-color: #eeeeee;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 4px;
            }
            QPushButton:hover { background-color: #dddddd; }
        """)
        show_btn.clicked.connect(lambda: self.toggle_key_visibility(self.primary_key_input, show_btn))
        key_layout.addWidget(show_btn)
        pg_form.addRow("API Key:", key_layout)

        primary_help_btn = QPushButton("📖 如何获取 API Key？")
        primary_help_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #DAAD69;
                border: none;
                padding: 3px;
                font-size: 12px;
                text-decoration: underline;
            }
            QPushButton:hover { color: #E0C080; }
        """)
        primary_help_btn.clicked.connect(lambda: self.open_register_url(self.primary_provider))
        pg_form.addRow("", primary_help_btn)

        pg_layout.addLayout(pg_form)
        layout.addWidget(primary_group)

        # === 备用线路 ===
        backup_group = QWidget()
        backup_group.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
                border: 1px solid #cccccc;
                border-radius: 10px;
            }
        """)
        bg_layout = QVBoxLayout(backup_group)
        bg_layout.setSpacing(8)

        bg_title = QLabel("🥈 备用线路（主线路失败时自动切换）")
        bg_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #555555; border: none;")
        bg_layout.addWidget(bg_title)

        bg_form = QFormLayout()
        bg_form.setSpacing(8)

        self.backup_provider = QListWidget()
        self.backup_provider.setFixedHeight(80)
        self.backup_provider.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 3px;
                font-size: 13px;
            }
            QListWidget::item { padding: 4px 8px; }
            QListWidget::item:selected {
                background-color: #bbbbbb;
                color: #1a1a1a;
            }
        """)
        for key, info in config.API_PROVIDERS.items():
            item = QListWidgetItem(f"{info['name']} — 模型: {info['model']}")
            item.setData(Qt.UserRole, key)
            self.backup_provider.addItem(item)
        self.backup_provider.setCurrentRow(1)
        bg_form.addRow("供应商:", self.backup_provider)

        bk_layout = QHBoxLayout()
        self.backup_key_input = QLineEdit()
        self.backup_key_input.setPlaceholderText("粘贴你的 API Key（可选）...")
        self.backup_key_input.setEchoMode(QLineEdit.Password)
        self.backup_key_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                color: #333333;
            }
            QLineEdit:focus { border: 1px solid #bbbbbb; }
        """)
        bk_layout.addWidget(self.backup_key_input)

        show_btn2 = QPushButton("👁")
        show_btn2.setFixedWidth(35)
        show_btn2.setStyleSheet("""
            QPushButton {
                background-color: #eeeeee;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 4px;
            }
            QPushButton:hover { background-color: #dddddd; }
        """)
        show_btn2.clicked.connect(lambda: self.toggle_key_visibility(self.backup_key_input, show_btn2))
        bk_layout.addWidget(show_btn2)
        bg_form.addRow("API Key:", bk_layout)

        backup_help_btn = QPushButton("📖 如何获取 API Key？")
        backup_help_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                padding: 3px;
                font-size: 12px;
                text-decoration: underline;
            }
            QPushButton:hover { color: #999999; }
        """)
        backup_help_btn.clicked.connect(lambda: self.open_register_url(self.backup_provider))
        bg_form.addRow("", backup_help_btn)

        bg_layout.addLayout(bg_form)
        layout.addWidget(backup_group)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        save_btn = QPushButton("💾 保存并启动")
        save_btn.clicked.connect(self.save_and_accept)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #DAAD69;
                color: #1a1a1a;
                border: none;
                border-radius: 8px;
                padding: 10px 30px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #E0C080; }
        """)
        btn_layout.addWidget(save_btn)

        skip_btn = QPushButton("跳过（稍后设置）")
        skip_btn.clicked.connect(self.confirm_skip)
        skip_btn.setStyleSheet("""
            QPushButton {
                background-color: #cccccc;
                color: #666666;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #bbbbbb; }
        """)
        btn_layout.addWidget(skip_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def load_current_config(self):
        api_cfg = config.CONFIG.get("api", {})
        if api_cfg.get("primary"):
            idx = self._find_provider_index(self.primary_provider, api_cfg["primary"])
            if idx >= 0:
                self.primary_provider.setCurrentRow(idx)
            self.primary_key_input.setText(api_cfg.get("primary_key", ""))
        if api_cfg.get("backup"):
            idx = self._find_provider_index(self.backup_provider, api_cfg["backup"])
            if idx >= 0:
                self.backup_provider.setCurrentRow(idx)
            self.backup_key_input.setText(api_cfg.get("backup_key", ""))

    def _find_provider_index(self, list_widget, provider_id):
        for i in range(list_widget.count()):
            if list_widget.item(i).data(Qt.UserRole) == provider_id:
                return i
        return -1

    def toggle_key_visibility(self, input_field, btn):
        if input_field.echoMode() == QLineEdit.Password:
            input_field.setEchoMode(QLineEdit.Normal)
            btn.setText("😣")
        else:
            input_field.setEchoMode(QLineEdit.Password)
            btn.setText("👁")

    def open_register_url(self, list_widget):
        item = list_widget.currentItem()
        if item:
            provider_id = item.data(Qt.UserRole)
            url = config.API_PROVIDERS.get(provider_id, {}).get("register_url", "")
            if url:
                webbrowser.open(url)

    def save_and_accept(self):
        primary_item = self.primary_provider.currentItem()
        backup_item = self.backup_provider.currentItem()
        primary_id = primary_item.data(Qt.UserRole) if primary_item else ""
        backup_id = backup_item.data(Qt.UserRole) if backup_item else ""
        primary_key = self.primary_key_input.text().strip()
        backup_key = self.backup_key_input.text().strip()

        if not primary_key:
            QMessageBox.warning(self, "提示", "⚠️ 请至少填写主线路的 API Key！\n\n如果暂时不想配置，请点「跳过」。")
            return

        config.CONFIG["api"] = {
            "primary": primary_id,
            "primary_key": primary_key,
            "backup": backup_id if backup_key else "",
            "backup_key": backup_key,
        }

        config.save_config()

        QMessageBox.information(
            self,
            "成功",
            "✅ API 配置已写入 config.json。\n蕾咪现在可以和你聊天啦~"
        )
        self.accept()

    def confirm_skip(self):
        """跳过按钮：弹出二次确认"""
        reply = QMessageBox.question(
            self,
            "确认跳过",
            "⚠️ 当前未配置 API Key，是否确认跳过？\n\n"
            "没有 API Key 蕾咪将无法和你聊天哦。\n\n"
            "💡 之后可以：\n"
            "· 右键蕾咪 →「🔑 API 设置」\n"
            "· 或编辑项目目录里的 config.json\n"
            "（可先复制 config.example.json）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.reject()
