# -*- coding: utf-8 -*-
"""
Remy 桌宠 - API 设置对话框

首次启动引导 + 后续修改，支持主/备线路配置。
"""

import webbrowser

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QWidget, QMessageBox, QFormLayout, QCheckBox, QStackedWidget
)
from PyQt5.QtCore import Qt

import config


class APISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔑 API 设置")
        self.setGeometry(200, 200, 550, 760)
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

        pg_title = QLabel("蕾咪需要连接一个语言模型才能聊天哦！")
        pg_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #333333; border: none;")
        pg_layout.addWidget(pg_title)

        pg_desc = QLabel("任选一个供应商并填入对应API Key，即可开启蕾咪的AI对话功能！（推荐DeepSeek）")
        pg_desc.setStyleSheet("color: #666666; font-size: 12px; border: none;")
        pg_desc.setWordWrap(True)
        pg_layout.addWidget(pg_desc)

        pg_form = QFormLayout()
        pg_form.setSpacing(8)
        self._primary_form = pg_form

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
            if info.get("supports_vision"):
                continue
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

        self.thinking_enabled = QCheckBox("是否启用思考模式（仅支持的模型生效）")
        self.thinking_enabled.setStyleSheet("""
            QCheckBox {
                color: #555555;
                font-size: 13px;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        self.primary_provider.currentRowChanged.connect(
            self._update_thinking_option
        )
        pg_form.addRow("思考模式:", self.thinking_enabled)

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

        # === 视觉代理（识图） ===
        vision_group = QWidget()
        vision_group.setStyleSheet("""
            QWidget {
                background-color: #f5f7fa;
                border: 1px solid #8fb8d8;
                border-radius: 10px;
            }
        """)
        vg_layout = QVBoxLayout(vision_group)
        vg_layout.setSpacing(8)

        vg_title = QLabel("蕾咪需要连接一个视觉模型才能识图哦！")
        vg_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #4a6a8a; border: none;")
        vg_layout.addWidget(vg_title)

        vg_desc = QLabel("填入智谱的API Key，即可开启蕾咪的智能识图功能！（将图片拖拽至蕾咪身上即可触发识图）")
        vg_desc.setStyleSheet("color: #666666; font-size: 12px; border: none;")
        vg_desc.setWordWrap(True)
        vg_layout.addWidget(vg_desc)

        vg_form = QFormLayout()
        vg_form.setSpacing(8)

        self.vision_provider = QListWidget()
        self.vision_provider.setFixedHeight(60)
        self.vision_provider.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 3px;
                font-size: 13px;
            }
            QListWidget::item { padding: 4px 8px; }
            QListWidget::item:selected {
                background-color: #8fb8d8;
                color: #1a1a1a;
            }
        """)
        for key, info in config.API_PROVIDERS.items():
            if not info.get("supports_vision"):
                continue
            item = QListWidgetItem(f"{info['name']} — 模型: {info['model']}")
            item.setData(Qt.UserRole, key)
            self.vision_provider.addItem(item)
        self.vision_provider.setCurrentRow(0)
        vg_form.addRow("识图供应商:", self.vision_provider)

        vk_layout = QHBoxLayout()
        self.vision_key_input = QLineEdit()
        self.vision_key_input.setPlaceholderText("粘贴视觉模型的 API Key（可选）...")
        self.vision_key_input.setEchoMode(QLineEdit.Password)
        self.vision_key_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                color: #333333;
            }
            QLineEdit:focus { border: 1px solid #8fb8d8; }
        """)
        vk_layout.addWidget(self.vision_key_input)

        show_btn3 = QPushButton("👁")
        show_btn3.setFixedWidth(35)
        show_btn3.setStyleSheet("""
            QPushButton {
                background-color: #eeeeee;
                border: 1px solid #cccccc;
                border-radius: 6px;
                padding: 4px;
            }
            QPushButton:hover { background-color: #dddddd; }
        """)
        show_btn3.clicked.connect(lambda: self.toggle_key_visibility(self.vision_key_input, show_btn3))
        vk_layout.addWidget(show_btn3)
        vg_form.addRow("视觉 Key:", vk_layout)

        vision_help_btn = QPushButton("📖 如何获取识图 Key？（智谱 GLM-4V-Flash 免费）")
        vision_help_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #4a6a8a;
                border: none;
                padding: 3px;
                font-size: 12px;
                text-decoration: underline;
            }
            QPushButton:hover { color: #6a8aa8; }
        """)
        vision_help_btn.clicked.connect(lambda: self.open_register_url(self.vision_provider))
        vg_form.addRow("", vision_help_btn)

        vg_layout.addLayout(vg_form)
        layout.addWidget(vision_group)

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

        bg_title = QLabel("备用API Key")
        bg_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #555555; border: none;")
        bg_layout.addWidget(bg_title)

        bg_desc = QLabel("若语言模型和视觉模型的API Key失效会自动切换至备用API Key！")
        bg_desc.setStyleSheet("color: #666666; font-size: 12px; border: none;")
        bg_desc.setWordWrap(True)
        bg_layout.addWidget(bg_desc)

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
            if info.get("supports_vision"):
                continue
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
        if api_cfg.get("vision_provider"):
            idx = self._find_provider_index(self.vision_provider, api_cfg["vision_provider"])
            if idx >= 0:
                self.vision_provider.setCurrentRow(idx)
            self.vision_key_input.setText(api_cfg.get("vision_key", ""))
        self.thinking_enabled.setChecked(
            api_cfg.get("thinking_enabled") is True
        )
        self._update_thinking_option()

    def _update_thinking_option(self) -> None:
        item = self.primary_provider.currentItem()
        provider_id = item.data(Qt.UserRole) if item else ""
        provider = config.API_PROVIDERS.get(provider_id, {})
        supported = bool(provider.get("supports_thinking", False))
        self.thinking_enabled.setVisible(supported)
        label = self._primary_form.labelForField(self.thinking_enabled)
        if label is not None:
            label.setVisible(supported)

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
        vision_item = self.vision_provider.currentItem()
        primary_id = primary_item.data(Qt.UserRole) if primary_item else ""
        backup_id = backup_item.data(Qt.UserRole) if backup_item else ""
        vision_id = vision_item.data(Qt.UserRole) if vision_item else ""
        primary_key = self.primary_key_input.text().strip()
        backup_key = self.backup_key_input.text().strip()
        vision_key = self.vision_key_input.text().strip()

        if not primary_key:
            QMessageBox.warning(self, "提示", "⚠️ 请至少填写主线路的 API Key！\n\n如果暂时不想配置，请点「跳过」。")
            return

        config.CONFIG["api"] = {
            "primary": primary_id,
            "primary_key": primary_key,
            "backup": backup_id if backup_key else "",
            "backup_key": backup_key,
            "thinking_enabled": self.thinking_enabled.isChecked(),
            "vision_provider": vision_id,
            "vision_key": vision_key,
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


class APISetupWizard(QDialog):
    """首次启动的 3 步 API 配置向导：主线路 → 视觉代理 → 备用线路。

    每步可「下一步」（保存并继续）或「上一步」（返回上一步修改）。
    """

    STEPS = [
        ("primary", "蕾咪需要连接一个[语言模型]才能聊天哦！", "任选一个供应商并填入对应API Key，即可开启蕾咪的AI对话功能！（推荐DeepSeek）"),
        ("vision", "蕾咪需要连接一个[视觉模型]才能识图哦！", "填入智谱的API Key，即可开启蕾咪的智能识图功能！（将图片拖拽至蕾咪身上即可触发识图）"),
        ("backup", "备用API Key（可选）", "若语言模型和视觉模型的API Key失效会自动切换至备用API Key！"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔑 API 配置向导")
        self.setGeometry(200, 200, 560, 470)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self._step = 0
        self._init_ui()
        self._load_current()
        self._render_step()

    def _init_ui(self):
        self._provider_lists = {}
        self._key_inputs = {}
        self._thinking_check = None
        self._thinking_form = None

        layout = QVBoxLayout()
        layout.setSpacing(12)

        self.step_indicator = QLabel()
        self.step_indicator.setAlignment(Qt.AlignCenter)
        self.step_indicator.setStyleSheet("font-size: 13px; color: #888888;")
        layout.addWidget(self.step_indicator)

        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 19px; font-weight: bold; color: #DAAD69;")
        layout.addWidget(self.title_label)

        self.desc_label = QLabel()
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignCenter)
        self.desc_label.setStyleSheet("color: #666666; font-size: 13px;")
        layout.addWidget(self.desc_label)

        self.step_stack = QStackedWidget()
        layout.addWidget(self.step_stack)

        self._primary_page = self._build_page("primary")
        self._vision_page = self._build_page("vision")
        self._backup_page = self._build_page("backup")
        self.step_stack.addWidget(self._primary_page)
        self.step_stack.addWidget(self._vision_page)
        self.step_stack.addWidget(self._backup_page)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        self.back_btn = QPushButton("上一步")
        self.back_btn.clicked.connect(self._on_back)
        self.back_btn.setStyleSheet("""
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
        btn_layout.addWidget(self.back_btn)

        self.next_btn = QPushButton("下一步")
        self.next_btn.clicked.connect(self._on_next)
        self.next_btn.setStyleSheet("""
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
        btn_layout.addWidget(self.next_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _providers_for(self, step_key):
        """vision 步骤只列支持视觉的供应商，其余步骤只列文本模型。"""
        providers = []
        for key, info in config.API_PROVIDERS.items():
            if step_key == "vision":
                if not info.get("supports_vision"):
                    continue
            else:
                if info.get("supports_vision"):
                    continue
            providers.append((key, info))
        return providers

    def _build_page(self, step_key):
        page = QWidget()
        form = QFormLayout()
        form.setSpacing(8)

        provider_list = QListWidget()
        provider_list.setFixedHeight(70)
        provider_list.setStyleSheet("""
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
        for key, info in self._providers_for(step_key):
            item = QListWidgetItem(f"{info['name']} — 模型: {info['model']}")
            item.setData(Qt.UserRole, key)
            provider_list.addItem(item)
        if provider_list.count():
            provider_list.setCurrentRow(0)
        form.addRow("供应商:", provider_list)
        self._provider_lists[step_key] = provider_list

        key_input = QLineEdit()
        key_input.setPlaceholderText("粘贴你的 API Key...")
        key_input.setEchoMode(QLineEdit.Password)
        key_input.setStyleSheet("""
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
        key_layout = QHBoxLayout()
        key_layout.addWidget(key_input)
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
        show_btn.clicked.connect(
            lambda _checked, inp=key_input, b=show_btn: self._toggle_key(inp, b)
        )
        key_layout.addWidget(show_btn)
        form.addRow("API Key:", key_layout)
        self._key_inputs[step_key] = key_input

        help_btn = QPushButton("📖 如何获取 API Key？")
        help_btn.setStyleSheet("""
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
        help_btn.clicked.connect(
            lambda _checked, pl=provider_list: self._open_register(pl)
        )
        form.addRow("", help_btn)

        if step_key == "primary":
            self._thinking_form = form
            self._thinking_check = QCheckBox("是否启用思考模式（仅支持的模型生效）")
            form.addRow("思考模式:", self._thinking_check)
            provider_list.currentRowChanged.connect(self._update_thinking_option)

        page.setLayout(form)
        return page

    def _update_thinking_option(self):
        if self._thinking_check is None:
            return
        item = self._provider_lists["primary"].currentItem()
        provider_id = item.data(Qt.UserRole) if item else ""
        provider = config.API_PROVIDERS.get(provider_id, {})
        supported = bool(provider.get("supports_thinking", False))
        self._thinking_check.setVisible(supported)
        label = self._thinking_form.labelForField(self._thinking_check)
        if label is not None:
            label.setVisible(supported)

    def _load_current(self):
        api = config.CONFIG.get("api", {})
        self._select_provider(self._provider_lists["primary"], api.get("primary", ""))
        self._key_inputs["primary"].setText(api.get("primary_key", ""))
        if self._thinking_check is not None:
            self._thinking_check.setChecked(api.get("thinking_enabled") is True)
        self._select_provider(self._provider_lists["vision"], api.get("vision_provider", ""))
        self._key_inputs["vision"].setText(api.get("vision_key", ""))
        self._select_provider(self._provider_lists["backup"], api.get("backup", ""))
        self._key_inputs["backup"].setText(api.get("backup_key", ""))
        self._update_thinking_option()

    def _render_step(self):
        _step_key, title, desc = self.STEPS[self._step]
        self.step_indicator.setText(f"第 {self._step + 1}/{len(self.STEPS)} 步")
        self.title_label.setText(title)
        self.desc_label.setText(desc)
        self.step_stack.setCurrentIndex(self._step)
        self.back_btn.setVisible(self._step > 0)
        self.next_btn.setText("完成" if self._step == len(self.STEPS) - 1 else "下一步")

    def _save_current_step(self):
        step_key = self.STEPS[self._step][0]
        api = config.CONFIG.setdefault("api", {})
        provider_list = self._provider_lists[step_key]
        provider_id = (
            provider_list.currentItem().data(Qt.UserRole)
            if provider_list.currentItem() else ""
        )
        key = self._key_inputs[step_key].text().strip()

        if step_key == "primary":
            api["primary"] = provider_id
            api["primary_key"] = key
            if self._thinking_check is not None:
                api["thinking_enabled"] = self._thinking_check.isChecked()
        elif step_key == "vision":
            api["vision_provider"] = provider_id
            api["vision_key"] = key
        elif step_key == "backup":
            api["backup"] = provider_id if key else ""
            api["backup_key"] = key

        config.save_config()

    def _on_next(self):
        self._save_current_step()
        if self._step == len(self.STEPS) - 1:
            self.accept()
        else:
            self._step += 1
            self._render_step()

    def _on_back(self):
        self._save_current_step()
        if self._step > 0:
            self._step -= 1
            self._render_step()

    def _select_provider(self, list_widget, provider_id):
        for i in range(list_widget.count()):
            if list_widget.item(i).data(Qt.UserRole) == provider_id:
                list_widget.setCurrentRow(i)
                return

    def _open_register(self, list_widget):
        item = list_widget.currentItem()
        if item:
            provider_id = item.data(Qt.UserRole)
            url = config.API_PROVIDERS.get(provider_id, {}).get("register_url", "")
            if url:
                webbrowser.open(url)

    def _toggle_key(self, input_field, btn):
        if input_field.echoMode() == QLineEdit.Password:
            input_field.setEchoMode(QLineEdit.Normal)
            btn.setText("😣")
        else:
            input_field.setEchoMode(QLineEdit.Password)
            btn.setText("👁")
