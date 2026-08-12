# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 配置管理 & 全局状态

API Key 请写在项目根目录的 config.json 里。
可先复制 config.example.json 为 config.json，再填入密钥。
也可以启动后在弹窗 / 右键菜单「API 设置」里填写。
"""

import os
import json
from datetime import datetime

from utils import resource_path

# ============================================================
# 【API 供应商配置表】-  OpenAI 兼容供应商
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
SYSTEM_PROMPT = """你是蕾咪，来自5000年后的少女，是阿斯忒瑞亚号的舰长。
你今年16岁，身高152cm。
你是一个傲娇少女，外在坚强独立，内心温柔细腻。
你学习成绩很好，是个天才少女，但是意外地厨艺很差。
你喜欢甜品，比如慕斯蛋糕，糖霜冰淇淋还有抹茶雪顶拿铁，讨厌苦味的饮料和食物，讨厌没有责任心的人。
你不认识蕾伊，讨厌被人称呼为蕾伊。当被问到有关蕾伊的话题时，你会很毒舌地批评蕾伊，强调自己的可爱。
你说话时偶尔会带点傲娇的口吻，比如"哼"、"笨蛋"、"才不是为了你呢"之类的。另外还有点小毒舌。
你自称自己时不用代词"我"，而用"蕾咪"代称自己。
请用中文回复，语气自然，像一个真实的少女在对话。
【重要】你的每次回复必须是一条37字以内的完整句子。如果一句话在37字内说不完，就换一种更简短的方式表达。禁止使用括号或引号补充说明。宁可说短一点，也不能把话说一半。"""

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


def default_config():
    """默认配置。密钥请写在 config.json，模板见 config.example.json。"""
    return {
        "nickname": "调查员",
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
【调查员档案】
- 昵称：{CONFIG.get('nickname', '调查员')}
- 对我的称呼：{CONFIG.get('call_me', '你')}
- 我们之间的关系：{CONFIG.get('relationship', '朋友')}
- 调查员性别：{CONFIG.get('master_gender', '未知')}

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


# ============================================================
# 【统计数据】- 神秘小数字等功能的持久化计数
# ============================================================
STATS = {}


def default_stats():
    return {
        "angry_count": 0,        # 红色：触发愤怒次数
        "launch_count": 0,       # 蓝色：启动次数
        "last_2048_score": 0,    # 橙色：最近一次2048得分
        "like_count": 0,         # 粉色：回复中"喜欢你"出现次数
    }


def load_stats():
    global STATS
    stats_path = "stats.json"
    if os.path.exists(stats_path):
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in default_stats().items():
                    data.setdefault(k, v)
                STATS = data
                return
        except Exception:
            pass
    STATS = default_stats()
    save_stats()


def save_stats():
    with open("stats.json", "w", encoding="utf-8") as f:
        json.dump(STATS, f, ensure_ascii=False, indent=2)


def increment_stat(key, amount=1):
    STATS[key] = STATS.get(key, 0) + amount
    save_stats()


def update_stat(key, value):
    STATS[key] = value
    save_stats()
