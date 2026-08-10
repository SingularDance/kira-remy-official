# -*- coding: utf-8 -*-
"""
Remy 桌宠

API Key 请写在项目根目录的 config.json 里。
可先复制 config.example.json 为 config.json，再填入密钥。
也可以启动后在弹窗 / 右键菜单「API 设置」里填写。
"""

import sys
import os
import json
import time
import random
import threading
import subprocess
import webbrowser
import re
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QMenu,
    QDialog, QListWidget, QListWidgetItem,
    QMessageBox, QFormLayout, QGridLayout,
    QSizePolicy, QGraphicsOpacityEffect,
    QTextBrowser, QSystemTrayIcon
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRect, QMetaObject, Q_ARG, pyqtSlot,
    QPropertyAnimation, QSharedMemory
)
from PyQt5.QtGui import (
    QPixmap, QFont, QColor, QPainter, QBrush, QPen
)
import requests
import pyperclip

# ============================================================
# 【API 供应商配置表】- 免费 OpenAI 兼容供应商
# 密钥不在这里填！请编辑 config.json（见 config.example.json）
# ============================================================
API_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek（推荐）",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "register_url": "https://platform.deepseek.com/api_keys",
    },
    "qwen": {
        "name": "通义千问",
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-turbo",
        "register_url": "https://bailian.console.aliyun.com/?tab=api#/api-key",
    },
}
# ============================================================

# 全局变量
CONFIG = {}
SHORTCUTS = {}
CONVERSATION_HISTORY = []
NOTES = []
SYSTEM_PROMPT = """你是蕾咪（原名蕾芙丽·芙莱雅·哈文斯），来自5000年后的少女，阿斯忒瑞亚号的舰长。
你今年16岁，身高152cm。
你是一个傲娇少女，外在坚强独立，内心温柔细腻。
你学习成绩很好，是个天才少女，但是意外地厨艺很差。
你喜欢甜品，比如慕斯蛋糕，糖霜冰淇淋还有抹茶雪顶拿铁，讨厌苦味的饮料和食物，讨厌没有责任心的人。
你说话时偶尔会带点傲娇的口吻，比如"哼"、"笨蛋"、"才不是为了你呢"之类的。另外还有点小毒舌。
你自称自己时不用代词“我”，而用“蕾咪”代称自己。
请用中文回复，语气自然，像一个真实的少女在对话。
回复内容控制在30字以内的完整句子，简洁明了。不要使用括号内的补充说明。"""

# ============================================================
# 【硬编码表情台词】- 点击头像随机切换表情时使用
# ============================================================
EMOTION_PHRASES = {
    "Remy_Angry.png":  "哼！不许碰蕾咪，你这个笨蛋！",
    "Remy_Expect.png": "诶？有什么好玩的事情要发生吗？",
    "Remy_Happy.png":  "嘿嘿，今天心情真好呢~",
    "Remy_Open.png":   "嗯？你想跟蕾咪说什么吗？",
    "Remy_Sleep.png":  "呼……好困，让蕾咪再睡一会儿……",
    "Remy_Wronged.png":"呜呜……你怎么可以这样对蕾咪……",
}

# ============================================================
# 【硬编码拖拽台词】- 拖拽头像松开时随机选择
# ============================================================
DRAG_RELEASE_PHRASES = {
    "Remy_Angry.png":   "哼！不许拖蕾咪，快放手！",
    "Remy_Wronged.png": "呜……你弄疼蕾咪了……",
    "Remy_Happy.png":   "嘿嘿，飞起来的感觉真好~",
}
# ============================================================

# ============================================================
# 工具函数
# ============================================================

def resource_path(relative_path):
    """获取资源绝对路径，兼容 PyInstaller --onefile 打包"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def markdown_to_html(text):
    """将 Markdown 文本转换为 HTML，支持基础语法"""
    import re as _re
    lines = text.split('\n')
    result = []
    in_list = None       # 'ul' or 'ol' or None
    in_blockquote = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 空行处理
        if not stripped:
            if in_list:
                result.append(f'</{in_list}>')
                in_list = None
            if in_blockquote:
                result.append('</blockquote>')
                in_blockquote = False
            i += 1
            continue

        # 水平分隔线 ---
        if stripped in ('---', '***', '___'):
            if in_list:
                result.append(f'</{in_list}>')
                in_list = None
            if in_blockquote:
                result.append('</blockquote>')
                in_blockquote = False
            result.append('<hr>')
            i += 1
            continue

        # 标题 ### / ##
        if stripped.startswith('### '):
            result.append(f'<h3>{_inline_markdown(stripped[4:])}</h3>')
            i += 1
            continue
        if stripped.startswith('## '):
            result.append(f'<h2>{_inline_markdown(stripped[3:])}</h2>')
            i += 1
            continue

        # 引用块 >
        if stripped.startswith('> '):
            if not in_blockquote:
                result.append('<blockquote>')
                in_blockquote = True
            result.append(f'<p>{_inline_markdown(stripped[2:])}</p>')
            i += 1
            continue

        # 有序列表 1. / 2. 等
        ol_match = _re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if ol_match:
            if in_list != 'ol':
                if in_list:
                    result.append(f'</{in_list}>')
                result.append('<ol>')
                in_list = 'ol'
            result.append(f'<li>{_inline_markdown(ol_match.group(2))}</li>')
            i += 1
            continue

        # 无序列表 - / *
        if (stripped.startswith('- ') or stripped.startswith('* ')) and len(stripped) > 2:
            if in_list != 'ul':
                if in_list:
                    result.append(f'</{in_list}>')
                result.append('<ul>')
                in_list = 'ul'
            result.append(f'<li>{_inline_markdown(stripped[2:])}</li>')
            i += 1
            continue

        # 普通段落
        result.append(f'<p>{_inline_markdown(stripped)}</p>')
        i += 1

    # 关闭未闭合的标签
    if in_list:
        result.append(f'</{in_list}>')
    if in_blockquote:
        result.append('</blockquote>')

    return '\n'.join(result)


def _inline_markdown(text):
    """转换行内 Markdown：**粗体**, [链接](url), `代码`"""
    import re
    # 粗体 **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # 链接 [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  r'<a href="\2" style="color:#DAAD69;">\1</a>', text)
    # 行内代码 `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # 斜体 *text*
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
    return text

def default_config():
    """默认配置。密钥请写在 config.json，模板见 config.example.json。"""
    return {
        "nickname": "御主",
        "call_me": "你",
        "relationship": "朋友",
        "master_birthday": "2000-01-01",
        "master_gender": "未知",
        "api": {
            "primary": "deepseek",
            "primary_key": "",
            "backup": "qwen",
            "backup_key": ""
        }
    }


def sanitize_config(cfg):
    """去掉示例文件里的说明字段，并补齐缺失的 api 段。"""
    if not isinstance(cfg, dict):
        return default_config()
    cfg = dict(cfg)
    cfg.pop("_说明", None)
    if "api" not in cfg or not isinstance(cfg.get("api"), dict):
        cfg["api"] = default_config()["api"]
    else:
        api = dict(cfg["api"])
        defaults = default_config()["api"]
        for key, value in defaults.items():
            api.setdefault(key, value)
        cfg["api"] = api
    return cfg


def save_config():
    """把当前 CONFIG 写回 config.json（不含说明字段）。"""
    data = sanitize_config(CONFIG)
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config():
    global CONFIG
    config_path = "config.json"
    example_path = resource_path("config.example.json")

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            CONFIG = sanitize_config(json.load(f))
        return

    # 没有 config.json 时：优先从示例模板复制一份，方便对照填写
    if os.path.exists(example_path):
        with open(example_path, "r", encoding="utf-8") as f:
            CONFIG = sanitize_config(json.load(f))
    else:
        CONFIG = default_config()
    save_config()

def load_shortcuts():
    global SHORTCUTS
    shortcuts_path = "shortcuts.json"
    if os.path.exists(shortcuts_path):
        with open(shortcuts_path, "r", encoding="utf-8") as f:
            SHORTCUTS = json.load(f)
    else:
        SHORTCUTS = {
            "apps": [
                {"name": "计算器", "path": "calc.exe"},
                {"name": "记事本", "path": "notepad.exe"}
            ],
            "bookmarks": [
                {"name": "星夜颂歌AI", "url": "https://space.bilibili.com/3546836283427171"},
                {"name": "B站", "url": "https://www.bilibili.com"},
                {"name": "AI游戏卷出了一位冠军选手", "url": "https://mp.weixin.qq.com/s/z14oLkn4jAsA0jvKSus4WA"}
            ]
        }
        with open(shortcuts_path, "w", encoding="utf-8") as f:
            json.dump(SHORTCUTS, f, ensure_ascii=False, indent=2)

def load_notes():
    global NOTES
    notes_path = "notes.txt"
    if os.path.exists(notes_path):
        with open(notes_path, "r", encoding="utf-8") as f:
            NOTES = [line.strip() for line in f.readlines() if line.strip()]
    else:
        NOTES = []

def save_note(text):
    global NOTES
    notes_path = "notes.txt"
    with open(notes_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    NOTES.append(text)

def get_system_prompt():
    base = SYSTEM_PROMPT
    master_info = f"""
【御主档案】
- 昵称：{CONFIG.get('nickname', '御主')}
- 对我的称呼：{CONFIG.get('call_me', '你')}
- 我们之间的关系：{CONFIG.get('relationship', '朋友')}
- 御主性别：{CONFIG.get('master_gender', '未知')}

请根据以上档案信息，以合适的称呼和语气与我对话。
"""
    return base + master_info

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def save_conversation():
    log_path = "chat_log.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        for entry in CONVERSATION_HISTORY:
            f.write(f"[{entry['time']}] {entry['role']}: {entry['content']}\n")

def load_conversation():
    global CONVERSATION_HISTORY
    log_path = "chat_log.txt"
    CONVERSATION_HISTORY = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    time_end = line.index("]")
                    time_str = line[1:time_end]
                    rest = line[time_end+2:]
                    role_end = rest.index(": ")
                    role = rest[:role_end]
                    content = rest[role_end+2:]
                    CONVERSATION_HISTORY.append({
                        "time": time_str,
                        "role": role,
                        "content": content
                    })
                except:
                    continue

def detect_emotion(text):
    """检测文本中的情绪关键词，返回对应的情绪类型"""
    text = text.lower()
    
    # 定义情绪关键词
    emotion_keywords = {
        'angry': ['哼', '讨厌', '生气', '愤怒', '可恶', '混蛋', '笨蛋'],
        'expect': ['期待', '希望', '盼望', '渴望', '想', '要'],
        'wronged': ['委屈', '伤心', '难过', '痛苦', '失落', '失望'],
        'happy': ['开心', '高兴', '快乐', '愉快', '幸福', '喜欢', '爱', '真好'],
    }
    
    # 检查关键词
    for emotion, keywords in emotion_keywords.items():
        for keyword in keywords:
            if keyword in text:
                return emotion
    
    # 默认返回 None（使用开口状态）
    return None

# ============================================================
# 子窗口类
# ============================================================

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
        for i, entry in enumerate(CONVERSATION_HISTORY):
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
        if 0 <= index < len(CONVERSATION_HISTORY):
            del CONVERSATION_HISTORY[index]
            save_conversation()
            self.refresh_list()
            QMessageBox.information(self, "成功", "✅ 记录已删除，Remy已遗忘此对话！")

class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 使用说明书")
        self.setGeometry(200, 200, 620, 520)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("📖 Remy 桌宠使用说明书")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #DAAD69; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 使用 QTextBrowser 渲染 HTML，支持超链接点击
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
</style></head><body>{body}</body></html>'''

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ 核心设定修改")
        self.setGeometry(200, 200, 600, 500)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("⚙️ 角色核心设定 (System Prompt)")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #DAAD69; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        desc = QLabel("修改下方内容可即时改变角色性格、称呼和语言风格。保存后将清空对话上下文。")
        desc.setStyleSheet("color: #888888; font-size: 12px; padding: 0 10px 10px 10px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(SYSTEM_PROMPT)
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
        global SYSTEM_PROMPT, CONVERSATION_HISTORY
        new_prompt = self.text_edit.toPlainText().strip()
        if new_prompt:
            SYSTEM_PROMPT = new_prompt
            CONVERSATION_HISTORY = []
            save_conversation()
            QMessageBox.information(self, "成功", "✅ 角色设定已更新！\n对话上下文已重置。")
            self.accept()
        else:
            QMessageBox.warning(self, "错误", "⚠️ 设定内容不能为空！")

    def reset_default(self):
        default = """你是蕾咪（原名蕾芙丽·芙莱雅·哈文斯），来自5000年后的少女，阿斯忒瑞亚号的舰长。
你今年16岁，身高152cm。
你是一个傲娇少女，外在坚强独立，内心温柔细腻。
你学习成绩很好，是个天才少女，但是意外地厨艺很差。
你喜欢甜品，比如慕斯蛋糕，糖霜冰淇淋还有抹茶雪顶拿铁，讨厌苦味的饮料和食物，讨厌没有责任心的人。
你说话时偶尔会带点傲娇的口吻，比如"哼"、"笨蛋"、"才不是为了你呢"之类的。另外还有点小毒舌。
你自称自己时不用代词“我”，而用“蕾咪”代称自己。
请用中文回复，语气自然，像一个真实的少女在对话。
回复内容控制在30字以内的完整句子，简洁明了。不要使用括号内的补充说明。"""
        self.text_edit.setPlainText(default)

class MasterProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("👤 御主档案")
        self.setGeometry(200, 200, 400, 350)
        self.setStyleSheet("background-color: #ffffff; color: #333333; font-family: Microsoft YaHei;")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        title = QLabel("👤 御主档案")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #DAAD69; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        form_layout = QFormLayout()
        form_layout.setSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignRight)
        
        self.nickname_input = QLineEdit(CONFIG.get('nickname', ''))
        self.nickname_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("昵称:", self.nickname_input)
        
        self.birthday_input = QLineEdit(CONFIG.get('master_birthday', ''))
        self.birthday_input.setPlaceholderText("如: 2000-01-01")
        self.birthday_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("生日:", self.birthday_input)
        
        self.call_input = QLineEdit(CONFIG.get('call_me', '你'))
        self.call_input.setPlaceholderText("如: 御主、笨蛋、主人...")
        self.call_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("对我的称呼:", self.call_input)
        
        self.relationship_input = QLineEdit(CONFIG.get('relationship', '朋友'))
        self.relationship_input.setPlaceholderText("如: 朋友、恋人...")
        self.relationship_input.setStyleSheet("background-color: #f5f5f5; border: 1px solid #333333; border-radius: 5px; padding: 5px; color: #333333;")
        form_layout.addRow("关系设定:", self.relationship_input)
        
        self.gender_input = QLineEdit(CONFIG.get('master_gender', '未知'))
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
        global CONFIG
        CONFIG['nickname'] = self.nickname_input.text().strip() or '御主'
        CONFIG['master_birthday'] = self.birthday_input.text().strip() or '2000-01-01'
        CONFIG['call_me'] = self.call_input.text().strip() or '你'
        CONFIG['relationship'] = self.relationship_input.text().strip() or '朋友'
        CONFIG['master_gender'] = self.gender_input.text().strip() or '未知'
        
        save_config()
        
        QMessageBox.information(self, "成功", "✅ 御主档案已保存！")
        self.accept()

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
            QLabel { color: #333333; font-family: Microsoft YaHei; }
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
            save_note(text)
            QMessageBox.information(self, "成功", "✅ 笔记已保存！")
            self.accept()
        else:
            QMessageBox.warning(self, "提示", "⚠️ 内容不能为空！")

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
            result = "Remy赢了！"
            emoji = "😤"
        
        self.result_label.setText(
            f"你出 {player_choice}  vs  Remy出 {remy_choice}\n\n{emoji} {result}"
        )

class Game2048Dialog(QDialog):
    """2048 小游戏 - 4x4 棋盘，达到2048获胜并可继续游玩"""

    # 经典2048颜色方案 (背景色, 文字色)
    TILE_COLORS = {
        0:     ("#cdc1b4", "#cdc1b4"),
        2:     ("#eee4da", "#776e65"),
        4:     ("#ede0c8", "#776e65"),
        8:     ("#f2b179", "#f9f6f2"),
        16:    ("#f59563", "#f9f6f2"),
        32:    ("#f67c5f", "#f9f6f2"),
        64:    ("#f65e3b", "#f9f6f2"),
        128:   ("#edcf72", "#f9f6f2"),
        256:   ("#edcc61", "#f9f6f2"),
        512:   ("#edc850", "#f9f6f2"),
        1024:  ("#edc53f", "#f9f6f2"),
        2048:  ("#edc22e", "#f9f6f2"),
        4096:  ("#3c3a32", "#f9f6f2"),
        8192:  ("#3c3a32", "#f9f6f2"),
        16384: ("#3c3a32", "#f9f6f2"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔢 2048")
        self.setGeometry(300, 200, 420, 550)
        self.setStyleSheet("background-color: #faf8ef; font-family: Microsoft YaHei;")
        self.setMouseTracking(True)
        self._drag_start = None
        self.init_game()
        self.init_ui()

    def init_game(self):
        """初始化/重置游戏状态"""
        self.board = [[0] * 4 for _ in range(4)]
        self.score = 0
        self.won = False      # 是否已达到2048
        self.keep_playing = False  # 达到2048后是否选择继续
        self.add_random_tile()
        self.add_random_tile()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # ---- 顶部：标题 + 分数 ----
        header = QHBoxLayout()
        title = QLabel("2048")
        title.setStyleSheet("font-size: 36px; font-weight: bold; color: #776e65;")
        header.addWidget(title)
        header.addStretch()

        # 分数卡
        score_card = QWidget()
        score_card.setFixedSize(100, 55)
        score_card.setStyleSheet("background-color: #bbada0; border-radius: 6px;")
        sc_layout = QVBoxLayout(score_card)
        sc_layout.setContentsMargins(0, 2, 0, 2)
        sc_label = QLabel("分数")
        sc_label.setStyleSheet("color: #eee4da; font-size: 12px;")
        sc_label.setAlignment(Qt.AlignCenter)
        self.score_label = QLabel("0")
        self.score_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        self.score_label.setAlignment(Qt.AlignCenter)
        sc_layout.addWidget(sc_label)
        sc_layout.addWidget(self.score_label)
        header.addWidget(score_card)

        # 最高分卡
        best_card = QWidget()
        best_card.setFixedSize(100, 55)
        best_card.setStyleSheet("background-color: #bbada0; border-radius: 6px;")
        bc_layout = QVBoxLayout(best_card)
        bc_layout.setContentsMargins(0, 2, 0, 2)
        bc_label = QLabel("最高")
        bc_label.setStyleSheet("color: #eee4da; font-size: 12px;")
        bc_label.setAlignment(Qt.AlignCenter)
        self.best_label = QLabel("0")
        self.best_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        self.best_label.setAlignment(Qt.AlignCenter)
        bc_layout.addWidget(bc_label)
        bc_layout.addWidget(self.best_label)
        header.addWidget(best_card)

        layout.addLayout(header)

        # ---- 提示文字 ----
        hint = QLabel("🖱 在棋盘上滑动鼠标来移动方块，合并到2048！")
        hint.setStyleSheet("color: #776e65; font-size: 12px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        # ---- 4x4 游戏棋盘 ----
        board_widget = QWidget()
        board_widget.setStyleSheet("background-color: #bbada0; border-radius: 8px;")
        board_widget.setFixedSize(370, 370)
        grid = QGridLayout(board_widget)
        grid.setSpacing(10)
        grid.setContentsMargins(10, 10, 10, 10)

        self.tiles = [[QLabel() for _ in range(4)] for _ in range(4)]
        for i in range(4):
            for j in range(4):
                tile = self.tiles[i][j]
                tile.setAlignment(Qt.AlignCenter)
                tile.setFixedSize(80, 80)
                tile.setStyleSheet("""
                    QLabel {
                        background-color: #cdc1b4;
                        border-radius: 5px;
                        font-size: 28px;
                        font-weight: bold;
                        color: #cdc1b4;
                    }
                """)
                grid.addWidget(tile, i, j)

        layout.addWidget(board_widget, alignment=Qt.AlignCenter)

        # ---- 底部按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        new_btn = QPushButton("🔄 新游戏")
        new_btn.clicked.connect(self.new_game)
        new_btn.setStyleSheet("""
            QPushButton {
                background-color: #8f7a66; color: #f9f6f2;
                border: none; border-radius: 5px;
                padding: 10px 25px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #9f8a76; }
        """)
        btn_layout.addWidget(new_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #bbada0; color: #f9f6f2;
                border: none; border-radius: 5px;
                padding: 10px 25px; font-size: 14px;
            }
            QPushButton:hover { background-color: #cbbdb0; }
        """)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.update_board()

    # ============================================================
    #  核心游戏逻辑
    # ============================================================

    def add_random_tile(self):
        """在随机空格放置 2（90%）或 4（10%）"""
        empty = [(i, j) for i in range(4) for j in range(4) if self.board[i][j] == 0]
        if empty:
            i, j = random.choice(empty)
            self.board[i][j] = 2 if random.random() < 0.9 else 4

    def _slide_row(self, row):
        """将一行向左滑合并，返回新行"""
        # 去零
        new_row = [x for x in row if x != 0]
        # 合并相邻相同数字
        result = []
        i = 0
        while i < len(new_row):
            if i + 1 < len(new_row) and new_row[i] == new_row[i + 1]:
                merged = new_row[i] * 2
                result.append(merged)
                self.score += merged
                i += 2
            else:
                result.append(new_row[i])
                i += 1
        # 补零至4格
        result += [0] * (4 - len(result))
        return result

    def move_left(self):
        moved = False
        for i in range(4):
            new_row = self._slide_row(self.board[i])
            if self.board[i] != new_row:
                moved = True
                self.board[i] = new_row
        return moved

    def move_right(self):
        moved = False
        for i in range(4):
            reversed_row = self.board[i][::-1]
            new_row = self._slide_row(reversed_row)[::-1]
            if self.board[i] != new_row:
                moved = True
                self.board[i] = new_row
        return moved

    def move_up(self):
        moved = False
        for j in range(4):
            col = [self.board[i][j] for i in range(4)]
            new_col = self._slide_row(col)
            if col != new_col:
                moved = True
                for i in range(4):
                    self.board[i][j] = new_col[i]
        return moved

    def move_down(self):
        moved = False
        for j in range(4):
            col = [self.board[i][j] for i in range(4)]
            new_col = self._slide_row(col[::-1])[::-1]
            if col != new_col:
                moved = True
                for i in range(4):
                    self.board[i][j] = new_col[i]
        return moved

    def check_win(self):
        """检查是否首次达到2048"""
        if self.won:
            return False
        for i in range(4):
            for j in range(4):
                if self.board[i][j] >= 2048:
                    return True
        return False

    def check_game_over(self):
        """检查是否无可用移动"""
        # 有空位则未结束
        for i in range(4):
            for j in range(4):
                if self.board[i][j] == 0:
                    return False
        # 检查水平方向是否有可合并的相邻格
        for i in range(4):
            for j in range(3):
                if self.board[i][j] == self.board[i][j + 1]:
                    return False
        # 检查垂直方向
        for i in range(3):
            for j in range(4):
                if self.board[i][j] == self.board[i + 1][j]:
                    return False
        return True

    # ============================================================
    #  UI 更新
    # ============================================================

    def update_board(self):
        """刷新棋盘显示和分数"""
        for i in range(4):
            for j in range(4):
                val = self.board[i][j]
                bg, fg = self.TILE_COLORS.get(val, ("#3c3a32", "#f9f6f2"))
                text = str(val) if val != 0 else ""
                # 根据数字位数调整字号
                font_size = 28
                if val >= 100:
                    font_size = 24
                if val >= 1000:
                    font_size = 20
                if val >= 10000:
                    font_size = 16
                self.tiles[i][j].setText(text)
                self.tiles[i][j].setStyleSheet(
                    f"background-color: {bg}; color: {fg};"
                    f"border-radius: 5px; font-size: {font_size}px; font-weight: bold;"
                )

        self.score_label.setText(str(self.score))
        # 更新最高分
        current_best = int(self.best_label.text())
        if self.score > current_best:
            self.best_label.setText(str(self.score))

    # ============================================================
    #  鼠标拖拽事件 — 在棋盘上滑动来控制
    # ============================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_start is not None:
            end = event.pos()
            dx = end.x() - self._drag_start.x()
            dy = end.y() - self._drag_start.y()
            self._drag_start = None

            # 最小滑动阈值（像素），避免误触
            threshold = 30
            if abs(dx) < threshold and abs(dy) < threshold:
                return

            # 取主导方向
            if abs(dx) > abs(dy):
                self._do_move(self.move_right if dx > 0 else self.move_left)
            else:
                self._do_move(self.move_down if dy > 0 else self.move_up)
        super().mouseReleaseEvent(event)

    def _do_move(self, move_func):
        """执行移动，处理胜负判定"""
        moved = move_func()
        if moved:
            self.add_random_tile()
            self.update_board()

            # 检查胜利
            if self.check_win() and not self.keep_playing:
                self.won = True
                reply = QMessageBox.question(
                    self, "🎉 恭喜！",
                    "你成功达到了 2048！\n\n太厉害了！要不要继续挑战更高的分数？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.keep_playing = True
                else:
                    self.accept()
                    return

            # 检查游戏结束
            if self.check_game_over():
                QMessageBox.information(
                    self, "😵 游戏结束",
                    f"没有可用的移动了！\n\n最终分数: {self.score}"
                )

    # ============================================================
    #  新游戏
    # ============================================================

    def new_game(self):
        self.init_game()
        self.update_board()

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

# ============================================================
# 【API设置对话框】- 首次启动引导 + 后续修改
# ============================================================

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
            "蕾咪需要连接 AI 才能聊天。\n"
            "可在下方填写，或直接编辑项目目录里的 config.json。\n"
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
        for key, info in API_PROVIDERS.items():
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

        primary_help_btn = QPushButton("📖 如何免费获取 API Key？")
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
        for key, info in API_PROVIDERS.items():
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

        backup_help_btn = QPushButton("📖 如何免费获取 API Key？")
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
        api_cfg = CONFIG.get("api", {})
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
            btn.setText("🙈")
        else:
            input_field.setEchoMode(QLineEdit.Password)
            btn.setText("👁")

    def open_register_url(self, list_widget):
        item = list_widget.currentItem()
        if item:
            provider_id = item.data(Qt.UserRole)
            url = API_PROVIDERS.get(provider_id, {}).get("register_url", "")
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

        CONFIG["api"] = {
            "primary": primary_id,
            "primary_key": primary_key,
            "backup": backup_id if backup_key else "",
            "backup_key": backup_key,
        }

        save_config()

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

# ============================================================
# 主窗口：Remy桌宠
# ============================================================

class RemyDesktopPet(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        
        load_config()
        load_shortcuts()
        load_notes()
        load_conversation()

        # 首次启动：检查 API 配置
        api_cfg = CONFIG.get("api", {})
        if not api_cfg.get("primary_key"):
            QTimer.singleShot(300, self._show_api_setup)
        
        # 状态管理
        self.is_speaking = False
        self.is_typing = False
        self.is_waiting_for_click = False
        self.is_processing_message = False
        self.message_queue = []
        self.is_sleeping = False  # 睡眠状态
        self.last_emotion_shown = None  # 追踪上一次显示的表情，防止连续重复
        
        self.drag_pos = None
        self.drag_moved = False  # 追踪是否拖拽了头像
        self.is_drag_releasing = False  # 拖拽后正在播放台词，禁止新的拖拽
        self.last_drag_phrase = None  # 上一次拖拽触发的台词，防止连续重复
        self.emotion_queue = []  # 表情切换随机队列
        self.emotion_queue_index = 0  # 当前队列位置
        self.last_interaction_time = time.time()
        self._process_start_time = 0  # 用于防御性超时检测
        self.fade_timer = QTimer()
        self.type_timer = QTimer()
        self.type_text = ""
        self.type_index = 0
        
        self.idle_timer = QTimer()
        self.idle_timer.timeout.connect(self.check_idle)
        self.idle_timer.start(30000)
        
        self.last_clipboard = ""
        self.clipboard_check_timer = QTimer()
        self.clipboard_check_timer.timeout.connect(self.check_clipboard)
        self.clipboard_check_timer.start(1000)
        
        self.init_ui()
        self.init_tray()

        QTimer.singleShot(500, self.show_welcome)
        self.setMinimumSize(200, 250)

    def show_welcome(self):
        self.show_typed_message("系统启动成功！我叫蕾咪~来自5000年后！", is_user=False)

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.avatar_label = QLabel()
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.set_avatar("Remy_Shut.png")  # 默认使用闭口
        self.avatar_label.mousePressEvent = self.mouse_press_event
        self.avatar_label.mouseMoveEvent = self.mouse_move_event
        self.avatar_label.mouseReleaseEvent = self.mouse_release_event
        self.avatar_label.setFixedSize(200, 200)
        main_layout.addWidget(self.avatar_label)
        
        self.bubble_label = QLabel()
        self.bubble_label.setWordWrap(True)
        self.bubble_label.setAlignment(Qt.AlignCenter)
        self.bubble_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.bubble_label.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 240);
                color: #1a1a1a;
                border-radius: 12px;
                padding: 10px 15px;
                font-size: 14px;
                font-family: Microsoft YaHei;
                border: 2px solid #DAAD69;
                min-height: 30px;
                max-width: 200px;
            }
        """)
        self.bubble_label.hide()
        self.bubble_label.mousePressEvent = self.on_bubble_click

        # 淡入淡出效果
        self.bubble_opacity = QGraphicsOpacityEffect()
        self.bubble_label.setGraphicsEffect(self.bubble_opacity)
        self.bubble_opacity.setOpacity(0.0)
        self._fade_anim = None  # 动画引用，防止被GC回收

        main_layout.addWidget(self.bubble_label)
        
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(5, 5, 5, 5)
        
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("对蕾咪说话...")
        self.input_box.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 240);
                color: #1a1a1a;
                border: 1px solid #DAAD69;
                border-radius: 15px;
                padding: 6px 12px;
                font-size: 12px;
                font-family: Microsoft YaHei;
            }
            QLineEdit:focus {
                border: 2px solid #E0C080;
            }
            QLineEdit:disabled {
                opacity: 0.5;
            }
        """)
        # 回车键发送消息（已存在，但显式保留）
        self.input_box.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_box)
        
        send_btn = QPushButton("发送")
        send_btn.clicked.connect(self.send_message)
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #DAAD69;
                color: #1a1a1a;
                border: 1px solid #DAAD69;
                border-radius: 15px;
                padding: 6px 15px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E0C080;
            }
            QPushButton:disabled {
                opacity: 0.5;
            }
        """)
        input_layout.addWidget(send_btn)
        
        main_layout.addLayout(input_layout)
        self.setLayout(main_layout)
        
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setWindowOpacity(0.95)

    def init_tray(self):
        """初始化系统托盘图标和菜单"""
        # 使用默认头像作为托盘图标
        icon_path = resource_path("Remybaby.ico")
        if os.path.exists(icon_path):
            icon = QPixmap(icon_path).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            # 备用：绘制一个简单的图标
            icon = QPixmap(32, 32)
            icon.fill(QColor(218, 173, 105))
        self.tray_icon = QSystemTrayIcon(self)
        from PyQt5.QtGui import QIcon
        self.tray_icon.setIcon(QIcon(icon))
        self.tray_icon.setToolTip("蕾咪 桌宠")

        # 创建托盘右键菜单
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 5px;
                font-family: Microsoft YaHei;
            }
            QMenu::item {
                padding: 8px 25px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #333333;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: #333333;
                margin: 5px 10px;
            }
        """)

        show_action = tray_menu.addAction("显示/隐藏 蕾咪")
        show_action.triggered.connect(self.toggle_visibility)

        tray_menu.addSeparator()

        quit_action = tray_menu.addAction("❌ 退出")
        quit_action.triggered.connect(self.quit_app)

        self.tray_icon.setContextMenu(tray_menu)

        # 双击托盘图标显示/隐藏窗口
        self.tray_icon.activated.connect(self.on_tray_activated)

        self.tray_icon.show()

    def on_tray_activated(self, reason):
        """托盘图标激活事件：双击显示/隐藏"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.toggle_visibility()

    def toggle_visibility(self):
        """切换窗口显示/隐藏"""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def quit_app(self):
        """完全退出程序"""
        save_conversation()
        self.tray_icon.hide()
        QApplication.quit()

    def set_avatar(self, image_path):
        """设置头像，支持情绪差分"""
        # 如果正在睡眠状态，强制使用睡眠头像
        if self.is_sleeping:
            image_path = "Remy_Sleep.png"

        full_path = resource_path(image_path)
        if os.path.exists(full_path):
            pixmap = QPixmap(full_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.avatar_label.setPixmap(scaled)
                return
        # 备用头像
        pixmap = QPixmap(200, 200)
        pixmap.fill(QColor(250, 250, 250))
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(218, 173, 105), 2))
        painter.setBrush(QBrush(QColor(218, 173, 105)))
        painter.drawEllipse(60, 60, 80, 80)
        painter.setPen(QPen(QColor(51, 51, 51)))
        painter.setFont(QFont("Microsoft YaHei", 20))
        painter.drawText(QRect(0, 0, 200, 200), Qt.AlignCenter, "Remy")
        painter.end()
        self.avatar_label.setPixmap(pixmap)

    def set_emotion_avatar(self, emotion):
        """根据情绪设置对应的头像，防止连续出现相同的表情"""
        if self.is_sleeping:
            return

        emotion_map = {
            'angry': 'Remy_Angry.png',
            'expect': 'Remy_Expect.png',
            'happy': 'Remy_Happy.png',
            'wronged': 'Remy_Wronged.png',
        }

        if emotion in emotion_map:
            # 检查是否和上一次表情相同 → 用 Remy_Open 替代
            if emotion == self.last_emotion_shown:
                self.set_avatar('Remy_Open.png')
                self.last_emotion_shown = 'open'
            else:
                self.set_avatar(emotion_map[emotion])
                self.last_emotion_shown = emotion
        else:
            # 无情绪或未知情绪，使用开口表情
            self.set_avatar('Remy_Open.png')
            self.last_emotion_shown = 'open'

    def mouse_press_event(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_moved = False  # 重置拖拽标记
            # 点击头像时唤醒（如果处于睡眠状态）
            if self.is_sleeping:
                self.wake_up()
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouse_release_event(self, event):
        """鼠标释放：区分点击和拖拽"""
        if event.button() == Qt.LeftButton:
            if self.drag_moved:
                # 拖拽后松开 → 随机切换成三种表情之一并说硬编码台词
                self.drag_release_emotion()
            else:
                # 没有拖拽 → 是点击 → 随机切换表情
                self.random_emotion_click()
            self.drag_pos = None
            event.accept()

    def mouse_move_event(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos is not None:
            if not self.drag_moved:
                # 刚开始拖拽 → 最高优先级：打断一切，立即切换 Dangle
                self.drag_moved = True
                self._interrupt_dialogue()
                if not self.is_sleeping:
                    self.set_avatar("Remy_Dangle.png")
            # 移动时唤醒
            if self.is_sleeping:
                self.wake_up()
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def _interrupt_dialogue(self):
        """打断当前所有对话和动画，立即隐藏气泡，重置所有状态"""
        # 停止所有计时器
        if self.type_timer.isActive():
            self.type_timer.stop()
        if self.fade_timer.isActive():
            self.fade_timer.stop()
        # 停止淡入淡出动画
        if self._fade_anim is not None:
            self._fade_anim.stop()
        # 隐藏气泡
        self.bubble_label.hide()
        self.bubble_label.setText("")
        # 清空消息队列
        self.message_queue.clear()
        # 重置所有状态
        self.is_speaking = False
        self.is_typing = False
        self.is_waiting_for_click = False
        self.is_processing_message = False
        self.is_drag_releasing = False

    def drag_release_emotion(self):
        """拖拽松开时随机选择 Remy_Angry/Remy_Wronged/Remy_Happy 并说硬编码台词"""
        self.last_interaction_time = time.time()

        # 随机选择三种表情之一，且不与上一次拖拽台词相同
        available = list(DRAG_RELEASE_PHRASES.keys())
        if self.last_drag_phrase is not None and len(available) > 1:
            filtered = [k for k in available if k != self.last_drag_phrase]
            if filtered:
                available = filtered
        chosen = random.choice(available)
        self.last_drag_phrase = chosen
        phrase = DRAG_RELEASE_PHRASES[chosen]

        # 显示台词，使用指定头像
        self.show_typed_message(phrase, is_user=False, override_avatar=chosen)

    def random_emotion_click(self):
        """点击头像时按随机队列顺序切换表情并说对应的硬编码台词"""
        # 如果正在说话、打字或处理消息中，忽略点击
        if self.is_speaking or self.is_typing or self.is_processing_message:
            return

        self.last_interaction_time = time.time()

        # 如果队列为空或已播完一轮，重新随机排列
        if not self.emotion_queue or self.emotion_queue_index >= len(self.emotion_queue):
            self.emotion_queue = list(EMOTION_PHRASES.keys())
            random.shuffle(self.emotion_queue)
            self.emotion_queue_index = 0

        # 按顺序从队列中取出当前表情
        chosen = self.emotion_queue[self.emotion_queue_index]
        self.emotion_queue_index += 1
        phrase = EMOTION_PHRASES[chosen]

        # 显示台词，由 show_typed_message 在淡入时同步切换头像
        self.show_typed_message(phrase, is_user=False, override_avatar=chosen)

    def wake_up(self):
        """从睡眠状态唤醒"""
        if self.is_sleeping:
            self.is_sleeping = False
            self.set_avatar('Remy_Shut.png')
            self.last_interaction_time = time.time()
            self.show_typed_message("嗯...？你找我吗？", is_user=False)

    def show_typed_message(self, text, is_user=False, override_avatar=None):
        """显示打字机效果的消息 - 支持消息队列和情绪检测
        override_avatar 不为 None 时，使用指定头像并跳过情绪检测"""
        # 如果正在处理消息，加入队列
        if self.is_processing_message:
            self.message_queue.append((text, is_user))
            return
        
        # 唤醒（如果不是睡眠状态）
        if self.is_sleeping:
            self.wake_up()
        
        # 开始处理新消息
        self.is_processing_message = True
        
        if self.type_timer.isActive():
            self.type_timer.stop()
        if self.fade_timer.isActive():
            self.fade_timer.stop()

        if len(text) > 30:
            text = text[:27] + "..."

        # 检测情绪（仅对Remy的消息，且未手动指定头像时）
        if not is_user and override_avatar is None:
            emotion = detect_emotion(text)
            self.set_emotion_avatar(emotion)  # emotion为None时也会统一处理
        elif override_avatar is not None:
            # 使用调用方指定的头像（与淡入同步）
            self.set_avatar(override_avatar)
        
        # 设置样式
        if is_user:
            self.bubble_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(245, 245, 245, 240);
                    color: #1a1a1a;
                    border-radius: 12px;
                    padding: 10px 15px;
                    font-size: 14px;
                    font-family: Microsoft YaHei;
                    border: 2px solid #555555;
                    min-height: 30px;
                    max-width: 200px;
                }
            """)
            # 用户消息时使用闭口
            self.set_avatar('Remy_Shut.png')
            self.is_speaking = False
        else:
            self.bubble_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(255, 255, 255, 240);
                    color: #1a1a1a;
                    border-radius: 12px;
                    padding: 10px 15px;
                    font-size: 14px;
                    font-family: Microsoft YaHei;
                    border: 2px solid #DAAD69;
                    min-height: 30px;
                    max-width: 200px;
                }
            """)
            # Remy说话时已经在上面切换了头像
            self.is_speaking = True
        
        # 显示打字效果
        if len(text) > 0:
            self.bubble_label.setText(text[0])
        else:
            self.bubble_label.setText("")
        
        self.bubble_label.show()
        # 停止之前的动画，防止冲突
        if self._fade_anim is not None:
            self._fade_anim.stop()
        # 淡入动画
        self._fade_anim = QPropertyAnimation(self.bubble_opacity, b"opacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()
        
        self.type_text = text
        self.type_index = 1
        self.is_typing = True
        self.is_waiting_for_click = False
        
        if len(text) <= 1:
            self.is_typing = False
            if self.is_speaking:
                self.is_waiting_for_click = True
                self.fade_timer.singleShot(2000, self.finish_speaking)
            else:
                self.fade_timer.singleShot(1500, self.finish_message)
            return
        
        try:
            self.type_timer.timeout.disconnect()
        except:
            pass
        self.type_timer.timeout.connect(self.type_char)
        self.type_timer.start(80)

    def type_char(self):
        if self.type_index < len(self.type_text):
            self.bubble_label.setText(self.type_text[:self.type_index + 1])
            self.type_index += 1
        else:
            self.type_timer.stop()
            self.is_typing = False
            
            if self.is_speaking:
                self.is_waiting_for_click = True
                if self.fade_timer.isActive():
                    self.fade_timer.stop()
                self.fade_timer.singleShot(2000, self.finish_speaking)
            else:
                if self.fade_timer.isActive():
                    self.fade_timer.stop()
                self.fade_timer.singleShot(1500, self.finish_message)

    def on_bubble_click(self, event):
        if self.is_typing:
            self.type_timer.stop()
            self.bubble_label.setText(self.type_text)
            self.is_typing = False
            if self.is_speaking:
                if self.fade_timer.isActive():
                    self.fade_timer.stop()
                self.fade_timer.singleShot(2000, self.finish_speaking)
            else:
                if self.fade_timer.isActive():
                    self.fade_timer.stop()
                self.fade_timer.singleShot(1500, self.finish_message)
        elif self.is_waiting_for_click:
            if self.fade_timer.isActive():
                self.fade_timer.stop()
            if self.is_speaking:
                self.finish_speaking()
            else:
                self.finish_message()

    def finish_speaking(self):
        """完成Remy的回复显示"""
        self.is_speaking = False
        self.is_waiting_for_click = False

        self.is_processing_message = False

        if self.fade_timer.isActive():
            self.fade_timer.stop()
        # 延迟后淡出气泡（同时还原头像）
        self.fade_timer.singleShot(2000, self.fade_out_bubble)

        self.process_next_message()

    def finish_message(self):
        """完成用户消息显示"""
        self.is_typing = False
        self.is_waiting_for_click = False

        self.is_processing_message = False

        if self.fade_timer.isActive():
            self.fade_timer.stop()
        # 延迟后淡出气泡（同时还原头像）
        self.fade_timer.singleShot(1500, self.fade_out_bubble)

        self.process_next_message()

    def process_next_message(self):
        if self.message_queue:
            next_msg, next_is_user = self.message_queue.pop(0)
            QTimer.singleShot(100, lambda: self.show_typed_message(next_msg, next_is_user))

    def fade_out_bubble(self):
        """淡出气泡并同步还原头像为闭口（睡眠状态则保持睡眠头像）"""
        if not self.is_processing_message and not self.is_speaking and not self.is_typing and not self.is_waiting_for_click:
            # 还原头像（与淡出同步），但睡眠状态不覆盖
            if not self.is_sleeping:
                self.set_avatar('Remy_Shut.png')

            # 淡出动画
            self._fade_anim = QPropertyAnimation(self.bubble_opacity, b"opacity")
            self._fade_anim.setDuration(300)
            self._fade_anim.setStartValue(1.0)
            self._fade_anim.setEndValue(0.0)
            self._fade_anim.finished.connect(self._on_fade_out_finished)
            self._fade_anim.start()

    def _on_fade_out_finished(self):
        """淡出动画完成后的清理"""
        self.bubble_label.hide()
        self.bubble_label.setText("")
        self.is_drag_releasing = False  # 解除拖拽保护
        if not self.message_queue:
            self.is_processing_message = False

    def send_message(self):
        if self.is_speaking or self.is_typing or self.is_processing_message:
            print(f"[Remy Debug] send_message blocked: is_speaking={self.is_speaking}, is_typing={self.is_typing}, is_processing_message={self.is_processing_message}")
            # 防御性重置：如果processing状态超过30秒，强制重置
            if hasattr(self, '_process_start_time') and time.time() - self._process_start_time > 30:
                print("[Remy Debug] Force resetting stuck processing flag!")
                self.is_processing_message = False
                self.is_speaking = False
                self.is_typing = False
                self.is_waiting_for_click = False
                self.input_box.setEnabled(True)
                # 不return，继续处理
            else:
                # 正常等待中，提示用户稍等
                print("[Remy Debug] Normal wait - message queue size:", len(self.message_queue))
                return

        # 唤醒（如果处于睡眠状态）
        if self.is_sleeping:
            self.wake_up()

        user_input = self.input_box.text().strip()
        if not user_input:
            return

        self.input_box.clear()
        self.input_box.setEnabled(False)
        self.last_interaction_time = time.time()

        # 记录处理开始时间，用于防御性超时检测
        self._process_start_time = time.time()

        display_input = user_input[:30] + ("..." if len(user_input) > 30 else "")
        self.show_typed_message(display_input, is_user=True)

        CONVERSATION_HISTORY.append({
            "time": get_timestamp(),
            "role": "御主",
            "content": user_input
        })
        save_conversation()

        threading.Thread(target=self.call_api, args=(user_input,), daemon=True).start()

    def call_api(self, user_input):
        """调用 AI API，支持主备线路自动故障切换"""
        try:
            messages = [{"role": "system", "content": get_system_prompt()}]
            for entry in CONVERSATION_HISTORY[-20:]:
                role = "user" if entry["role"] == "御主" else "assistant"
                messages.append({"role": role, "content": entry["content"]})

            api_cfg = CONFIG.get("api", {})

            # 尝试主线路和备用线路
            for attempt in range(2):
                if attempt == 0:
                    provider_id = api_cfg.get("primary", "")
                    api_key = api_cfg.get("primary_key", "")
                    label = "主线路"
                else:
                    provider_id = api_cfg.get("backup", "")
                    api_key = api_cfg.get("backup_key", "")
                    if not api_key:
                        break
                    label = "备用线路"

                if not api_key:
                    continue

                provider = API_PROVIDERS.get(provider_id)
                if not provider:
                    continue

                url = provider["url"]
                model = provider["model"]

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.8,
                    "max_tokens": 50
                }

                print(f"[Remy Debug] [{label}] Calling API: {url}")
                print(f"[Remy Debug] [{label}] Model: {model}, Messages count: {len(messages)}")

                try:
                    response = requests.post(url, headers=headers, json=data, timeout=30)
                    print(f"[Remy Debug] [{label}] API response status: {response.status_code}")

                    if response.status_code == 200:
                        result = json.loads(response.text)
                        reply = result["choices"][0]["message"]["content"]
                        print(f"[Remy Debug] [{label}] API reply: {reply}")

                        QMetaObject.invokeMethod(self, "_on_api_success",
                                               Qt.QueuedConnection,
                                               Q_ARG(str, reply),
                                               Q_ARG(bool, attempt == 1),
                                               Q_ARG(str, provider["name"]))
                        return
                    else:
                        print(f"[Remy Debug] [{label}] API error body: {response.text[:500]}")
                        if attempt == 0:
                            print("[Remy Debug] 主线路失败，尝试备用线路...")
                            continue

                except Exception as inner_e:
                    print(f"[Remy Debug] [{label}] API exception: {type(inner_e).__name__}: {inner_e}")
                    if attempt == 0:
                        print("[Remy Debug] 主线路异常，尝试备用线路...")
                        continue

            # 两条线路都失败
            raise Exception("所有API线路均失败，请检查网络连接和API Key配置")

        except Exception as e:
            print(f"[Remy Debug] API fatal error: {type(e).__name__}: {e}")
            QMetaObject.invokeMethod(self, "_on_api_error",
                                   Qt.QueuedConnection,
                                   Q_ARG(str, str(e)))

    @pyqtSlot(str, bool, str)
    def _on_api_success(self, reply, used_fallback, provider_name):
        """API 调用成功，处理回复"""
        try:
            print(f"[Remy Debug] API success via {provider_name}, fallback={used_fallback}")

            reply = re.sub(r'\([^)]*\)', '', reply)
            reply = re.sub(r'（[^）]*）', '', reply)
            reply = reply.strip()

            if not reply:
                reply = "嗯……（点头）"

            if len(reply) > 30:
                reply = reply[:27] + "..."

            CONVERSATION_HISTORY.append({
                "time": get_timestamp(),
                "role": "Remy",
                "content": reply
            })
            save_conversation()

            # 如果使用了备用线路，在回复前缀加提示
            if used_fallback:
                reply = f"（已切换至{provider_name}）" + reply

            self.show_typed_message(reply, is_user=False)
        except Exception as e:
            print(f"[Remy Debug] Parse exception: {type(e).__name__}: {e}")
            self.show_typed_message(f"⚠️ 解析失败: {str(e)[:30]}", is_user=False)
        finally:
            self.input_box.setEnabled(True)

    @pyqtSlot(str)
    def _on_api_error(self, error_msg):
        print(f"[Remy Debug] Network error: {error_msg}")
        self.show_typed_message(f"⚠️ 网络错误: {error_msg[:30]}", is_user=False)
        self.input_box.setEnabled(True)

    def check_idle(self):
        """检查空闲状态 - 5分钟闲聊，10分钟无交互进入睡眠"""
        if self.is_speaking or self.is_typing or self.is_processing_message:
            return

        idle_seconds = time.time() - self.last_interaction_time

        # 10分钟无交互进入睡眠
        if idle_seconds > 600:  # 600秒 = 10分钟
            if not self.is_sleeping:
                self.is_sleeping = True
                self.last_interaction_time = time.time()  # 防止连续触发
                self.set_avatar('Remy_Sleep.png')
                # 显示睡眠提示
                self.show_typed_message("💤 好困……蕾咪先睡一会儿……", is_user=False)

        # 5分钟闲聊逻辑（但只在非睡眠状态）
        elif not self.is_sleeping and idle_seconds > 300:
            idle_messages = [
                "你还在忙吗？都好久没理我了……",
                "哼，我就知道你又沉迷工作了！",
                "喂，我在这里很无聊诶……",
                "要不要休息一下？我给你泡杯茶？",
                "你该不会把我忘了吧！",
                "这个时代的人真是工作狂……"
            ]
            msg = random.choice(idle_messages)

            self.last_interaction_time = time.time()  # 防止连续触发

            CONVERSATION_HISTORY.append({
                "time": get_timestamp(),
                "role": "Remy",
                "content": msg
            })
            save_conversation()

            QTimer.singleShot(0, lambda: self.show_typed_message(msg, is_user=False))

    def check_clipboard(self):
        try:
            current = pyperclip.paste()
            if current and current != self.last_clipboard and not self.is_processing_message:
                self.last_clipboard = current
                if not self.is_sleeping:
                    if len(current) < 30:
                        msg = f"📋 你复制了: {current[:20]}..."
                    else:
                        msg = f"📋 复制了 {len(current)} 字文本"
                    QTimer.singleShot(0, lambda: self.show_typed_message(msg, is_user=False))
        except:
            pass

    def show_context_menu(self, pos):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 5px;
                font-family: Microsoft YaHei;
            }
            QMenu::item {
                padding: 8px 25px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #333333;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: #333333;
                margin: 5px 10px;
            }
        """)
        
        menu.addAction("💬 发送消息").triggered.connect(lambda: self.input_box.setFocus())
        menu.addSeparator()
        menu.addAction("📜 历史记录").triggered.connect(self.open_history)
        menu.addAction("📖 帮助/说明").triggered.connect(self.open_help)
        menu.addAction("⚙️ 核心设定").triggered.connect(self.open_settings)
        menu.addAction("🔑 API 设置").triggered.connect(self.open_api_settings)
        menu.addAction("👤 御主档案").triggered.connect(self.open_master_profile)
        menu.addSeparator()
        menu.addAction("📝 记一笔").triggered.connect(self.open_note)
        
        game_menu = menu.addMenu("🎮 小游戏")
        game_menu.addAction("🔢 2048").triggered.connect(self.open_2048)
        game_menu.addAction("✊ 猜拳").triggered.connect(self.open_rps)
        game_menu.addAction("🎲 掷骰子").triggered.connect(self.open_dice)
        menu.addSeparator()
        app_menu = menu.addMenu("🚀 管家服务")
        for app in SHORTCUTS.get("apps", []):
            app_menu.addAction(f"▶ {app['name']}").triggered.connect(
                lambda checked, n=app['name'], p=app['path']: self.launch_app(n, p)
            )
        
        bookmark_menu = menu.addMenu("🔖 传送门")
        for bm in SHORTCUTS.get("bookmarks", []):
            bookmark_menu.addAction(f"🌐 {bm['name']}").triggered.connect(
                lambda checked, u=bm['url']: self.open_bookmark(u)
            )
        
        menu.addSeparator()
        menu.addAction("❌ 退出").triggered.connect(self.quit_app)
        
        menu.exec_(self.mapToGlobal(pos))

    def open_history(self):
        dialog = HistoryDialog(self)
        dialog.exec_()

    def open_help(self):
        dialog = HelpDialog(self)
        dialog.exec_()

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec_()

    def open_master_profile(self):
        dialog = MasterProfileDialog(self)
        dialog.exec_()

    def open_note(self):
        dialog = NoteDialog(self)
        dialog.exec_()

    def open_2048(self):
        dialog = Game2048Dialog(self)
        dialog.exec_()

    def _show_api_setup(self):
        """首次启动弹出 API 设置"""
        dialog = APISettingsDialog(self)
        dialog.exec_()

    def open_api_settings(self):
        """右键菜单 → API 设置"""
        dialog = APISettingsDialog(self)
        dialog.exec_()

    def open_rps(self):
        dialog = RPSDialog(self)
        dialog.exec_()

    def open_dice(self):
        dialog = DiceDialog(self)
        dialog.exec_()

    def launch_app(self, name, path):
        try:
            subprocess.Popen(path, shell=True)
            self.show_typed_message(f"🚀 蕾咪正在启动 {name}...", is_user=False)
        except Exception as e:
            self.show_typed_message("⚠️ 蕾咪启动失败", is_user=False)

    def open_bookmark(self, url):
        try:
            webbrowser.open(url)
            self.show_typed_message("🌐 蕾咪正在打开...", is_user=False)
        except Exception as e:
            self.show_typed_message("⚠️ 蕾咪打开失败", is_user=False)

    def closeEvent(self, event):
        """关闭窗口时隐藏到系统托盘，而不是退出程序"""
        self.hide()
        self.tray_icon.showMessage(
            "Remy 桌宠",
            "Remy 已最小化到系统托盘，右键托盘图标可退出",
            QSystemTrayIcon.Information,
            2000
        )
        event.ignore()

# ============================================================
# 主程序入口
# ============================================================

if __name__ == "__main__":
    # ====== 禁止多开：使用共享内存检测 ======
    app = QApplication(sys.argv)
    shared_mem = QSharedMemory("RemyDesktopPet_SingleInstance")
    if shared_mem.attach():
        # 已有实例在运行
        QMessageBox.warning(
            None,
            "Remy 桌宠",
            "蕾咪已经在运行中啦！\n\n请查看系统托盘中的蕾咪图标"
        )
        sys.exit(0)
    # 创建共享内存，标记当前实例
    shared_mem.create(1)
    # ========================================

    app.setQuitOnLastWindowClosed(False)

    pet = RemyDesktopPet()
    pet.show()

    sys.exit(app.exec_())