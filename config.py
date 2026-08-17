# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 配置管理 & 全局状态

API Key 请写在项目根目录的 config.json 里。
可先复制 config.example.json 为 config.json，再填入密钥。
也可以启动后在弹窗 / 右键菜单「API 设置」里填写。
"""

import os
import json
import re
from datetime import datetime

from utils import resource_path, user_data_path

# ============================================================
# 【API 供应商配置表】-  OpenAI 兼容供应商
# 密钥不在这里填！请编辑 config.json（见 config.example.json）
# ============================================================
API_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek（推荐）",
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-v4-flash",
        "register_url": "https://platform.deepseek.com/api_keys",
        "supports_thinking": True,
    },
    "qwen": {
        "name": "通义千问",
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-turbo",
        "register_url": "https://bailian.console.aliyun.com/?tab=api#/api-key",
        "supports_thinking": False,
    },
    "glm4v": {
        "name": "智谱 GLM-4V-Flash（识图）",
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4v-flash",
        "register_url": "https://open.bigmodel.cn/",
        "supports_thinking": False,
        "supports_vision": True,
    },
}
# ============================================================

# 全局变量
CONFIG = {}
SHORTCUTS = {}
CONVERSATION_HISTORY = []
NOTES = []
SYSTEM_PROMPT = """你是蕾咪，来自5000年后的少女，是阿斯忒瑞亚号的舰长。
你今年18岁，身高158cm。
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
# 【硬编码壁纸切换台词】- 切换壁纸时随机表情 + 队列播放
# ============================================================
WALLPAPER_PHRASES = {
    "Remy_Angry.png":   "喂！刚才那张壁纸蕾咪还没欣赏够呢！调回去调回去！",
    "Remy_Expect.png":  "哇~这张壁纸超好看的耶！可以私发给蕾咪一份嘛！？",
    "Remy_Happy.png":   "嘿嘿，这张壁纸蕾咪喜欢！很对蕾咪的品味哟！",
    "Remy_Open.png":    "哼哼~聪明的蕾咪已经帮你换好壁纸了哦。",
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
        "wallpaper_folder": "",
        # 更新检查。owner/repo 指向发布仓库（GitHub Releases），
        # 与代码托管的 Gitee 不是同一处；做成可配是为了便于指向测试仓库。
        "update": {
            "enabled": True,
            "owner": "SingularDance",
            "repo": "kira-remy-official",
            "skip_version": "",
            "last_check_date": "",
        },
        "api": {
            "primary": "deepseek",
            "primary_key": "",
            "backup": "qwen",
            "backup_key": "",
            "thinking_enabled": False,
            "vision_provider": "glm4v",
            "vision_key": "",
        }
    }


def sanitize_config(cfg):
    """去掉示例文件里的说明字段，并补齐缺失的 api 段。"""
    if not isinstance(cfg, dict):
        return default_config()
    cfg = dict(cfg)
    cfg.pop("_说明", None)
    cfg.setdefault("wallpaper_folder", "")

    # update 段：老用户的 config.json 里没有这个键，必须补齐，
    # 否则「跳过此版本」和「每天只查一次」没有地方持久化。
    # 逐键 setdefault 而不是整段替换，避免覆盖用户已有的设置。
    if not isinstance(cfg.get("update"), dict):
        cfg["update"] = default_config()["update"]
    else:
        update = dict(cfg["update"])
        for key, value in default_config()["update"].items():
            update.setdefault(key, value)
        if not isinstance(update.get("enabled"), bool):
            update["enabled"] = True
        cfg["update"] = update

    if "api" not in cfg or not isinstance(cfg.get("api"), dict):
        cfg["api"] = default_config()["api"]
    else:
        api = dict(cfg["api"])
        defaults = default_config()["api"]
        for key, value in defaults.items():
            api.setdefault(key, value)
        if not isinstance(api.get("thinking_enabled"), bool):
            api["thinking_enabled"] = defaults["thinking_enabled"]
        cfg["api"] = api
    return cfg


def save_config():
    """把当前 CONFIG 写回 config.json（不含说明字段）。"""
    data = sanitize_config(CONFIG)
    with open(user_data_path("config.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config():
    global CONFIG
    config_path = user_data_path("config.json")
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
    shortcuts_path = user_data_path("shortcuts.json")
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
                {"name": "B站", "url": "https://www.bilibili.com"}
            ]
        }
        with open(shortcuts_path, "w", encoding="utf-8") as f:
            json.dump(SHORTCUTS, f, ensure_ascii=False, indent=2)

def load_notes():
    global NOTES
    notes_path = user_data_path("notes.txt")
    if os.path.exists(notes_path):
        with open(notes_path, "r", encoding="utf-8") as f:
            NOTES = [line.strip() for line in f.readlines() if line.strip()]
    else:
        NOTES = []

def save_note(text):
    global NOTES
    notes_path = user_data_path("notes.txt")
    with open(notes_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    NOTES.append(text)

def get_system_prompt():
    base = SYSTEM_PROMPT
    relationship = CONFIG.get('relationship', '朋友')

    tone = ""
    if any(k in relationship for k in ("恋人", "女友", "男友", "情侣", "老婆", "老公", "女朋友", "男朋友")):
        tone = "你和调查员是恋人关系。保持傲娇的个性，但在恋人面前会更温柔、更黏人、会撒娇，语气里透着喜欢和在乎。\n"

    master_info = f"""
【调查员档案】
- 昵称：{CONFIG.get('nickname', '调查员')}
- 对我的称呼：{CONFIG.get('call_me', '你')}
- 我们之间的关系：{relationship}
- 调查员性别：{CONFIG.get('master_gender', '未知')}

请根据以上档案信息，以合适的称呼和语气与我对话。
"""
    return base + tone + master_info

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def save_conversation():
    log_path = user_data_path("chat_log.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        for entry in CONVERSATION_HISTORY:
            f.write(f"[{entry['time']}] {entry['role']}: {entry['content']}\n")

def load_conversation():
    global CONVERSATION_HISTORY
    log_path = user_data_path("chat_log.txt")
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
                except (IndexError, ValueError):
                    continue


# ============================================================
# 【统计数据】- 神秘小数字等功能的持久化计数
# ============================================================
STATS = {}


def affection_keywords(call_me, nickname):
    """粉色数字统计的关键词集合：喜欢/爱 + 称呼 + 昵称。

    「你」只是默认称呼，不再作为独立基础词——由「喜欢{call_me}」自然覆盖。
    空的称呼/昵称跳过（避免退化成裸「喜欢」「爱」误匹配）；set 去重防止两者相同。
    """
    keywords = set()
    for name in (call_me, nickname):
        if name:
            keywords.add(f"喜欢{name}")
            keywords.add(f"爱{name}")
    return keywords


def count_affection_hits(reply, call_me="你", nickname="调查员"):
    """统计回复中「喜欢/爱」表达的总次数（非重叠匹配，按出现次数累加）。"""
    if not reply:
        return 0
    keywords = affection_keywords(call_me, nickname)
    if not keywords:
        return 0
    # 最长优先，避免 "喜欢{称呼}" 与 "喜欢{昵称}" 等更短词重叠时重复计数
    pattern = "|".join(re.escape(k) for k in sorted(keywords, key=len, reverse=True))
    return len(re.findall(pattern, reply))


def default_stats():
    return {
        "angry_count": 0,        # 红色：触发愤怒次数
        "launch_count": 0,       # 蓝色：启动次数
        "last_2048_score": 0,    # 橙色：最近一次2048得分
        "like_count": 0,         # 粉色：回复中"喜欢/爱"的表达次数
    }


def load_stats():
    global STATS
    stats_path = user_data_path("stats.json")
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
    with open(user_data_path("stats.json"), "w", encoding="utf-8") as f:
        json.dump(STATS, f, ensure_ascii=False, indent=2)


def increment_stat(key, amount=1):
    STATS[key] = STATS.get(key, 0) + amount
    save_stats()


def update_stat(key, value):
    STATS[key] = value
    save_stats()
