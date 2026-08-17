# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 帮助说明对话框
"""

import os

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextBrowser
)
from PyQt5.QtCore import Qt

from utils import markdown_to_html, resource_path


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 使用说明书")
        self.setGeometry(200, 200, 620, 520)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif;")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("📖 Remy 桌宠使用说明书")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet("""
            QTextBrowser {
                background-color: #fafaf5;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 14px;
                line-height: 1.8;
                color: #333333;
            }
        """)

        help_path = resource_path("help.md")
        if os.path.exists(help_path):
            with open(help_path, "r", encoding="utf-8") as f:
                content = f.read()
            html = markdown_to_html(content)
            browser.setHtml(self._wrap_html(html))
        else:
            browser.setHtml(
                '<p style="color:#cc5555;text-align:center;padding:30px;">'
                '⚠️ 未找到 help.md 文件</p>'
            )

        layout.addWidget(browser)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("background-color: #DAAD69; color: #1a1a1a; padding: 8px 20px; border-radius: 5px;")
        close_btn.setFixedWidth(100)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _wrap_html(self, body):
        """将 body HTML 包装为完整的 HTML 文档，应用样式"""
        return f'''<!DOCTYPE html>
<html><head><style>
    body {{
        font-family: "Microsoft YaHei", sans-serif;
        font-size: 14px;
        line-height: 1.9;
        color: #333333;
        padding: 8px 12px;
    }}
    h1 {{
        color: #DAAD69;
        font-size: 22px;
        font-weight: bold;
        border-bottom: 3px solid #DAAD69;
        padding-bottom: 8px;
        margin-top: 24px;
        margin-bottom: 14px;
    }}
    h2 {{
        color: #DAAD69;
        font-size: 18px;
        border-bottom: 2px solid #f0e0c0;
        padding-bottom: 6px;
        margin-top: 20px;
        margin-bottom: 10px;
    }}
    h3 {{
        color: #c09050;
        font-size: 15px;
        margin-top: 14px;
        margin-bottom: 6px;
    }}
    hr {{
        border: none;
        border-top: 1px dashed #ddd;
        margin: 16px 0;
    }}
    ul, ol {{
        margin: 4px 0;
        padding-left: 20px;
    }}
    li {{
        margin: 3px 0;
        color: #555555;
    }}
    blockquote {{
        border-left: 3px solid #DAAD69;
        margin: 10px 0;
        padding: 6px 14px;
        background-color: #fdfaf3;
        color: #777777;
        border-radius: 0 6px 6px 0;
    }}
    a {{
        color: #DAAD69;
        text-decoration: none;
    }}
    a:hover {{
        text-decoration: underline;
    }}
    p {{
        margin: 6px 0;
    }}
    b {{
        color: #555555;
    }}
    code {{
        background-color: #f0f0f0;
        padding: 1px 5px;
        border-radius: 3px;
        font-size: 13px;
    }}
    pre {{
        background-color: #f5f5f5;
        border: 1px solid #ddd;
        border-radius: 6px;
        padding: 12px 16px;
        overflow-x: auto;
        font-family: "Consolas", "Courier New", monospace;
        font-size: 13px;
        line-height: 1.6;
        margin: 10px 0;
        white-space: pre-wrap;
    }}
    pre code {{
        background: none;
        padding: 0;
        font-size: inherit;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        margin: 10px 0;
        font-size: 13px;
    }}
    th {{
        background-color: #DAAD69;
        color: #1a1a1a;
        padding: 8px 12px;
        border: 1px solid #c09050;
        text-align: left;
        font-weight: bold;
    }}
    td {{
        padding: 6px 12px;
        border: 1px solid #ddd;
        color: #333333;
    }}
    tr:nth-child(even) td {{
        background-color: #fafaf5;
    }}
    img {{
        max-width: 100%;
        height: auto;
        border-radius: 8px;
        margin: 8px 0;
    }}
</style></head><body>{body}</body></html>'''
