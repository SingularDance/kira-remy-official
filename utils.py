# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 纯工具函数

资源路径、文本处理、Markdown → HTML 渲染、情绪检测。
不依赖 config 等业务模块。
"""

import sys
import os
import re
import base64


# 识图支持的图片扩展名 → MIME 类型映射
IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


def is_image_file(path):
    """按扩展名判断是否为识图支持的图片文件。"""
    ext = os.path.splitext(path or "")[1].lower()
    return ext in IMAGE_MIME


def image_to_data_uri(path):
    """把本地图片读成 base64 data URI，供多模态识图接口使用。"""
    ext = os.path.splitext(path)[1].lower()
    mime = IMAGE_MIME.get(ext, "image/png")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"


def resource_path(relative_path):
    """**只读**资源的绝对路径（立绘 PNG、config.example.json 等）。

    兼容 PyInstaller 打包：--onefile 时资源解压在 sys._MEIPASS。

    要读写用户数据请用 `user_data_path()`——打包后这个目录是不可写的。
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        # 使用脚本所在目录作为基准路径，而非当前工作目录
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


# 打包后 .app 里的应用名，用来在 macOS 上定位用户数据目录
APP_NAME = "MACPetRemy"


# ------------------------------------------------------------
# 界面字体
#
# 原来到处写死 "Microsoft YaHei"。那个字体 **macOS 上没有**，
# Qt 找不到就回退到默认字体，启动时还会打一条
# 「Populating font family aliases took 110 ms」的警告——
# 每次启动白白多花 100 毫秒去枚举字体别名。
#
# 样式表里用字体栈（`UI_FONT_STACK`），Windows 仍然排第一，
# 所以 Windows 上的观感一个像素都不变；macOS 落到苹方。
# QFont 只接受单个字族，所以另给一个按平台选的 `UI_FONT_FAMILY`。
#
# 遗留：macOS 上启动时仍会打一条
# 「Populating font family aliases took ~100 ms」——
# 因为字体栈里排第一的 Microsoft YaHei 在 mac 上不存在，Qt 要找一遍。
# 渲染没问题（会正确落到苹方），只是白花约 100 毫秒。
# 试过 QFont.insertSubstitution，**没用**，警告照旧，所以那段代码去掉了。
# 真要根治得让这 18 处样式表按平台生成字体栈（即把普通字符串改成 f-string），
# 为 100 毫秒改 18 个地方、还容易改错，暂时不值得。
# ------------------------------------------------------------
# 字体名用单引号：CSS 两种引号都认，而这些样式表大多写在 Python 的
# "..." 字符串里，用双引号会直接把字符串截断成语法错误（踩过）
UI_FONT_STACK = "'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif"

if sys.platform == "darwin":
    UI_FONT_FAMILY = "PingFang SC"
elif sys.platform.startswith("win"):
    UI_FONT_FAMILY = "Microsoft YaHei"
else:
    UI_FONT_FAMILY = "Noto Sans CJK SC"


def user_data_dir():
    """用户数据（config.json / 聊天记录 / 便签 / 统计）该放哪。

    ## 为什么需要这个函数

    原来所有地方都直接写 `open("config.json", "w")`，用的是**当前工作目录**。
    在终端里 `python3 Remy.py` 时 CWD 是项目目录，能写，所以一直没问题。

    但**双击 .app 启动时 macOS 把 CWD 设成根目录 `/`**，
    于是 `open("config.json","w")` 变成往 `/config.json` 写，
    而系统根分区是只读的：

        OSError: [Errno 30] Read-only file system: 'config.json'

    程序在 `load_config()` 里就崩了，表现是双击图标闪一下就没。

    ## 三种情况分开处理

    - **源码运行**（开发）：仍然放项目目录。改掉的话每次调试都要去
      别处找 config.json，反而添乱
    - **Windows 打包后**：放 exe 旁边。**这是现有 Windows 用户的数据位置，
      不能动**——改了他们的 API Key、聊天记录、便签就全「丢」了
    - **macOS 打包后**：放 `~/Library/Application Support/`。
      .app 包内部不可写（而且签名后改动会破坏签名），这也是苹果的惯例
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            preferred = os.path.expanduser(
                f"~/Library/Application Support/{APP_NAME}")
        else:
            # Windows / Linux：可执行文件旁边，保持便携
            preferred = os.path.dirname(os.path.abspath(sys.executable))
    else:
        preferred = os.path.dirname(os.path.abspath(__file__))

    if _usable(preferred):
        return preferred

    # 首选位置写不了就退到用户目录。
    #
    # 会走到这里的情况：从只读介质启动（挂载的 DMG、只读网络盘），
    # 或者装在没有写权限的目录里。
    #
    # 这一步不是可有可无的——**双击启动时没有终端**，
    # 这里抛异常的话用户看到的就是「点了图标闪一下就没了」，
    # 没有任何线索。宁可换个地方存，也不要静默崩掉。
    fallback = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}") \
        if sys.platform == "darwin" \
        else os.path.join(os.path.expanduser("~"), f".{APP_NAME}")
    if _usable(fallback):
        return fallback

    raise RuntimeError(
        f"找不到可写的目录存放配置：{preferred} 和 {fallback} 都写不了。"
        "把程序放到「文稿」或「下载」这类目录再试。")


def _usable(path):
    """这个目录能不能建出来、能不能写。"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def user_data_path(name):
    """用户数据文件的绝对路径。**所有读写用户数据的地方都要走它。**"""
    return os.path.join(user_data_dir(), name)


def smart_truncate(text, max_chars=37):
    """把回复截成不超过 max_chars 个字符的自然短句。
    优先保留完整句子；否则在分句处截断并加省略号；最后兜底补省略号。
    """
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text

    # 第一优先：句末标点（。！？…~等）——完整句子，不加省略号
    sentence_end = "。！？…;!?~～"
    best = 0
    for i, ch in enumerate(text[:max_chars]):
        if ch in sentence_end:
            best = i + 1
    if best:
        return text[:best]

    # 第二优先：逗号等分句处——截断后补省略号
    clause_end = "，、,"
    best = 0
    for i, ch in enumerate(text[:max_chars]):
        if ch in clause_end:
            best = i + 1
    if best:
        prefix = text[:best].rstrip("，、, ")
        if len(prefix) + 2 > max_chars:
            prefix = prefix[:max_chars - 2]
        return prefix + "……"

    # 兜底：整句无任何停顿——去掉末两字补省略号，避免腰斩观感
    return text[:max_chars - 2] + "……"


def markdown_to_html(text):
    """将 Markdown 文本转换为 HTML，支持表格、图片等语法"""
    lines = text.split('\n')
    result = []
    in_list = None       # 'ul' or 'ol' or None
    in_blockquote = False
    in_table = False
    table_rows = []      # [(cells, is_header), ...]

    def close_blocks():
        nonlocal in_list, in_blockquote
        if in_list:
            result.append(f'</{in_list}>')
            in_list = None
        if in_blockquote:
            result.append('</blockquote>')
            in_blockquote = False

    def flush_table():
        nonlocal in_table, table_rows
        if table_rows:
            if not in_table:
                result.append('<table>')
                in_table = True
            for cells, is_header in table_rows:
                tag = 'th' if is_header else 'td'
                row = '<tr>' + ''.join(
                    f'<{tag}>{_inline_markdown(c)}</{tag}>' for c in cells
                ) + '</tr>'
                result.append(row)
            table_rows = []
        if in_table:
            result.append('</table>')
            in_table = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 空行处理
        if not stripped:
            flush_table()
            close_blocks()
            i += 1
            continue

        # 表格行检测（必须以 | 开头和结尾）
        if stripped.startswith('|') and stripped.endswith('|'):
            cells = [c.strip() for c in stripped[1:-1].split('|')]
            # 分隔行 |---|---|
            is_sep = all(re.match(r'^:?-{2,}:?$', c.strip()) for c in cells)
            if is_sep:
                # 上一行变为表头
                if table_rows:
                    cells_h, _ = table_rows[0]
                    table_rows[0] = (cells_h, True)
                i += 1
                continue

            close_blocks()
            table_rows.append((cells, False))
            i += 1
            continue

        # 非表格行 → 先关闭表格
        flush_table()

        # 水平分隔线 ---
        if stripped in ('---', '***', '___'):
            close_blocks()
            result.append('<hr>')
            i += 1
            continue

        # 标题 # / ## / ###
        if stripped.startswith('### '):
            result.append(f'<h3>{_inline_markdown(stripped[4:])}</h3>')
            i += 1
            continue
        if stripped.startswith('## '):
            result.append(f'<h2>{_inline_markdown(stripped[3:])}</h2>')
            i += 1
            continue
        if stripped.startswith('# '):
            result.append(f'<h1>{_inline_markdown(stripped[2:])}</h1>')
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

        # 围栏代码块 ```
        if stripped.startswith('```'):
            flush_table()
            close_blocks()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            # HTML 转义 + 保留缩进
            code_text = '\n'.join(code_lines)
            code_text = code_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            result.append(f'<pre><code>{code_text}</code></pre>')
            i += 1  # 跳过闭合 ```
            continue

        # 有序列表 1. / 2. 等
        ol_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
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
    flush_table()
    close_blocks()

    return '\n'.join(result)


def _inline_markdown(text):
    """转换行内 Markdown：![图片](path), **粗体**, [链接](url), `代码`"""
    import re as _re

    # 图片 ![alt](path) — 必须在链接之前处理，否则 [alt](url) 会先被转为 <a>
    def _replace_image(m):
        alt = m.group(1)
        path = m.group(2)
        # 跳过外部 URL
        if path.startswith(('http://', 'https://', 'data:')):
            return f'<img src="{path}" alt="{alt}" />'
        # 本地文件 → base64 嵌入 QTextBrowser
        try:
            full_path = resource_path(path)
            if os.path.exists(full_path):
                with open(full_path, 'rb') as f:
                    data = base64.b64encode(f.read()).decode()
                ext = os.path.splitext(path)[1].lower().lstrip('.')
                mime_map = {'png': 'png', 'jpg': 'jpeg', 'jpeg': 'jpeg',
                            'gif': 'gif', 'webp': 'webp', 'bmp': 'bmp', 'svg': 'svg+xml'}
                mime = mime_map.get(ext, 'png')
                return f'<img src="data:image/{mime};base64,{data}" alt="{alt}" />'
        except Exception:
            pass
        return f'<span style="color:#cc5555;">[图片缺失: {alt}]</span>'

    text = _re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _replace_image, text)

    # 粗体 **text**
    text = _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # 链接 [text](url)
    text = _re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  r'<a href="\2" style="color:#DAAD69;">\1</a>', text)
    # 行内代码 `code`
    text = _re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # 斜体 *text*
    text = _re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
    return text


def detect_emotion(text):
    """检测文本中的情绪关键词，返回对应的情绪类型"""
    text = text.lower()

    # 定义情绪关键词
    emotion_keywords = {
        'angry': ['生气', '愤怒', '可恶', '笨蛋'],
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
