# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 核心设定修改对话框
"""

from PyQt5.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QMessageBox
)
from PyQt5.QtCore import Qt

import config


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ 核心设定修改")
        self.setGeometry(200, 200, 600, 500)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif;")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("⚙️ 角色核心设定 (System Prompt)")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #DAAD69; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        desc = QLabel("修改下方内容可即时改变蕾咪性格、称呼和语言风格。保存后将清空对话上下文。")
        desc.setStyleSheet("color: #888888; font-size: 12px; padding: 0 10px 10px 10px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(config.SYSTEM_PROMPT)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #f5f5f5;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                line-height: 1.6;
                color: #333333;
            }
        """)
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 保存并应用")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setStyleSheet("background-color: #333333; color: white; padding: 8px 20px; border-radius: 5px;")
        btn_layout.addWidget(save_btn)

        reset_btn = QPushButton("🔄 恢复默认")
        reset_btn.clicked.connect(self.reset_default)
        reset_btn.setStyleSheet("background-color: #DAAD69; color: #1a1a1a; padding: 8px 20px; border-radius: 5px;")
        btn_layout.addWidget(reset_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("background-color: #888888; color: white; padding: 8px 20px; border-radius: 5px;")
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def save_settings(self):
        new_prompt = self.text_edit.toPlainText().strip()
        if new_prompt:
            config.SYSTEM_PROMPT = new_prompt
            config.CONVERSATION_HISTORY = []
            config.save_conversation()
            QMessageBox.information(self, "成功", "✅ 角色设定已更新！\n对话上下文已重置。")
            self.accept()
        else:
            QMessageBox.warning(self, "错误", "⚠️ 设定内容不能为空！")

    def reset_default(self):
        default = """你是蕾咪，来自5000年后的少女，是阿斯忒瑞亚号的舰长。
你今年18岁，身高158cm。
你是一个傲娇少女，外在坚强独立，内心温柔细腻。
你学习成绩很好，是个天才少女，但是意外地厨艺很差。
你喜欢甜品，比如慕斯蛋糕，糖霜冰淇淋还有抹茶雪顶拿铁，讨厌苦味的饮料和食物，讨厌没有责任心的人。
你不认识蕾伊，讨厌被人称呼为蕾伊。当被问到有关蕾伊的话题时，你会很毒舌地批评蕾伊，强调自己的可爱。
你说话时偶尔会带点傲娇的口吻，比如"哼"、"笨蛋"、"才不是为了你呢"之类的。另外还有点小毒舌。
你自称自己时不用代词"我"，而用"蕾咪"代称自己。
请用中文回复，语气自然，像一个真实的少女在对话。
【重要】你的每次回复必须是一条37字以内的完整句子。如果一句话在37字内说不完，就换一种更简短的方式表达。禁止使用括号或引号补充说明。宁可说短一点，也不能把话说一半。"""
        self.text_edit.setPlainText(default)
