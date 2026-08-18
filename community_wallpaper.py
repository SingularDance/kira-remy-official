# -*- coding: utf-8 -*-
"""社区壁纸站（http://8.153.169.59）的接口封装。

与 updater.py / music_monitor.py 同一套纪律：不 import Qt，URL 拼接与响应
解析都做成纯函数；响应是远端内容，按**不可信输入**处理——字段缺失、类型错、
整体不是 JSON 对象都可能出现，任何不合预期都降级为空，不抛异常，别让坏数据
把 UI 打崩。
"""

# 列表接口根地址。图片相对路径统一拼到这个 base 后面。
BASE_URL = "http://8.153.169.59"
API_IMAGES_PATH = "/api/images"

# 每页数量。接口上限 60，取一个首屏不卡又够看的数。
PAGE_SIZE = 20


def build_images_url(offset=0, limit=PAGE_SIZE, sort="composite"):
    """拼 GET /api/images 的完整地址。

    offset / limit / sort 都显式写入，不依赖服务端默认值，
    避免以后默认排序或分页一改就跟着变。
    """
    return (f"{BASE_URL}{API_IMAGES_PATH}"
            f"?offset={int(offset)}&limit={int(limit)}&sort={sort}")


def _absolute(path):
    """把相对路径拼成完整地址；已是绝对 URL 则原样返回。"""
    path = (path or "").strip()
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return BASE_URL + (path if path.startswith("/") else "/" + path)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_images_response(raw):
    """解析 GET /api/images 的 JSON 响应，返回归一化 item 列表。

    每项归一化为：
        {id, title, display_name, width, height, thumb_url, preview_url}
    其中 thumb_url / preview_url 已转成绝对地址。缺 id 或缺图片地址的条目
    直接跳过（这些条目既显示不了也设不了壁纸）。
    """
    if not isinstance(raw, dict):
        return []
    items = raw.get("items")
    if not isinstance(items, list):
        return []

    result = []
    for it in items:
        if not isinstance(it, dict):
            continue
        item_id = _safe_int(it.get("id"))
        if not item_id:
            continue
        thumb = _absolute(it.get("thumb_url"))
        preview = _absolute(it.get("preview_url"))
        if not thumb or not preview:
            continue
        result.append({
            "id": item_id,
            "title": str(it.get("title") or "").strip(),
            "display_name": str(it.get("display_name") or "").strip(),
            "width": _safe_int(it.get("width")),
            "height": _safe_int(it.get("height")),
            "thumb_url": thumb,
            "preview_url": preview,
        })
    return result
