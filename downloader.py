# -*- coding: utf-8 -*-
"""下载并校验安装包。

与 updater.py 的分工：updater 负责「有没有新版本」，本模块负责
「把包拿下来并确认它是完整的」。

四条硬约束：

1. **超时与检查更新是两套**。检查更新 5 秒即放弃（见 updater.FETCH_TIMEOUT），
   但安装包有 47MB，GitHub 在国内又慢，整体不能设死超时——本模块用的是
   「每次读取的超时」，只要还在持续收到数据就不放弃。

2. **先写 .part 再改名**。中途失败或被取消时，目标路径上不会留下一个
   看起来完整的坏包。改名是原子操作。

3. **解压前必须校验**。断掉的 zip 解压会写入半个文件，把安装目录搞坏，
   而用户此时已经关掉了旧程序——等于变砖。所以：核对字节数（如果知道），
   再跑 zipfile.testzip() 逐条校验 CRC。

4. **绝不覆盖用户数据**。config.json 里是 API Key，chat_log/notes 是用户内容。
   解压时显式跳过，宁可让新版少一个默认配置，也不能把用户的 Key 冲掉。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

# 每次读取的超时（秒）。不是整体超时——只要还在收数据就继续。
READ_TIMEOUT = 30

# 分块大小。64KB 是吞吐与进度回调频率的折中：太小回调过密拖慢 UI，
# 太大则进度条卡顿感明显。
CHUNK_SIZE = 64 * 1024

# 解压时绝不覆盖的文件。config.json 含 API Key，其余是用户内容。
# 与 .gitignore 里「本地密钥与隐私数据」那一组保持一致。
PROTECTED_FILES = frozenset({
    "config.json",
    "chat_log.txt",
    "notes.txt",
    "stats.json",
    "shortcuts.json",
    "music_history.jsonl",
})


@dataclass
class DownloadResult:
    ok: bool
    path: str = ""
    downloaded: int = 0
    error: str = ""
    cancelled: bool = False


@dataclass
class ExtractResult:
    ok: bool
    extracted: int = 0
    skipped: list = field(default_factory=list)   # 被保护而跳过的文件
    rejected: list = field(default_factory=list)  # 路径不安全被拒的条目
    error: str = ""


# ============================================================
# 下载
# ============================================================

def download_dir(platform: Optional[str] = None) -> str:
    """安装包下载到哪个目录。

    macOS 上 ``tempfile.gettempdir()`` 返回 ``/var/folders/…/T/`` 这种
    随机字符的临时目录，用户根本找不到下载的包。改用系统的「下载」目录
    （~/Downloads），Finder 里一眼就能看到。Windows / Linux 保持临时目录。

    platform 参数可注入，便于在 Windows 上直接单测 mac 分支（与
    updater.asset_template 同一套手法）。
    """
    plat = platform or sys.platform
    if plat == "darwin":
        return os.path.expanduser("~/Downloads")
    return tempfile.gettempdir()


def download(url: str,
             dest: str,
             expected_size: int = 0,
             progress: Optional[Callable[[int, int], None]] = None,
             should_cancel: Optional[Callable[[], bool]] = None,
             get: Optional[Callable] = None,
             read_timeout: int = READ_TIMEOUT) -> DownloadResult:
    """把 url 下载到 dest。返回结果对象，**不抛异常**。

    Args:
        expected_size: 期望字节数（来自 GitHub API 的 asset.size）。
            为 0 表示未知（302 兜底路径拿不到大小），此时跳过大小核对。
        progress: 回调 (已下载字节, 总字节)。总字节未知时传 0。
            **回调里不要做重活**，它在下载线程上执行。
        should_cancel: 每块检查一次，返回 True 则中止并清理临时文件。
        get: 注入用的请求函数，默认 requests.get。测试用。
    """
    if get is None:
        try:
            import requests
            get = requests.get
        except ImportError:  # pragma: no cover - 项目本身依赖 requests
            return DownloadResult(False, error="requests 不可用")

    part = dest + ".part"
    downloaded = 0

    try:
        resp = get(url, stream=True, timeout=read_timeout,
                   allow_redirects=True)
    except Exception as exc:
        return DownloadResult(False, error=f"连接失败：{exc}")

    status = getattr(resp, "status_code", 0)
    if status != 200:
        return DownloadResult(False, error=f"HTTP {status}")

    # Content-Length 只用于进度显示。真正的完整性判断靠 expected_size 与
    # zip 校验——GitHub 的下载走 CDN 跳转，头部不一定可靠。
    total = expected_size or _content_length(resp)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(part)) or ".", exist_ok=True)
        with open(part, "wb") as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if should_cancel is not None and should_cancel():
                    _remove_quietly(part)
                    return DownloadResult(False, downloaded=downloaded,
                                          cancelled=True, error="用户取消")
                if not chunk:          # keep-alive 空块，跳过
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    try:
                        progress(downloaded, total)
                    except Exception as exc:
                        # 进度回调是 UI 代码，它出问题不该让下载失败
                        logger.debug("进度回调异常，忽略：%s", exc)
    except Exception as exc:
        _remove_quietly(part)
        return DownloadResult(False, downloaded=downloaded,
                              error=f"写入失败：{exc}")

    if expected_size and downloaded != expected_size:
        _remove_quietly(part)
        return DownloadResult(
            False, downloaded=downloaded,
            error=f"大小不符：收到 {downloaded} 字节，应为 {expected_size}")

    try:
        # 改名是原子操作：到这一步 dest 才第一次出现，且必然是完整的
        os.replace(part, dest)
    except OSError as exc:
        _remove_quietly(part)
        return DownloadResult(False, downloaded=downloaded,
                              error=f"重命名失败：{exc}")

    return DownloadResult(True, path=dest, downloaded=downloaded)


def _content_length(resp) -> int:
    try:
        return max(0, int(resp.headers.get("Content-Length", 0)))
    except (AttributeError, TypeError, ValueError):
        return 0


def _remove_quietly(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.debug("清理临时文件失败：%s", exc)


# ============================================================
# 校验
# ============================================================

def verify_zip(path: str) -> tuple:
    """校验 zip 是否完整可用。返回 (是否通过, 说明)。

    两步都必要：is_zipfile 只看尾部的中央目录，通不过说明文件明显是坏的；
    testzip() 才会逐条解压校验 CRC，能抓出「目录在但内容截断」的情况——
    下载中断最常见的表现正是后者。
    """
    if not os.path.exists(path):
        return False, "文件不存在"
    if not zipfile.is_zipfile(path):
        return False, "不是合法的 zip（很可能下载不完整）"
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad is not None:
                return False, f"压缩包内容损坏，首个坏条目：{bad}"
            if not zf.namelist():
                return False, "压缩包是空的"
    except Exception as exc:
        return False, f"校验失败：{exc}"
    return True, "完整"


# ============================================================
# 解压
# ============================================================

def safe_extract(zip_path: str,
                 target_dir: str,
                 protected: Iterable[str] = PROTECTED_FILES,
                 strip_top_level: Optional[bool] = None) -> ExtractResult:
    """把 zip 解压到 target_dir，跳过受保护文件，拒绝不安全路径。

    **不用 ZipFile.extractall()**，原因有两个：

    1. 路径穿越（zip slip）。压缩包里的条目名可以是 `../../x` 或绝对路径，
       extractall 在旧版 Python 上会照写。安装包是从网络下载的，
       必须当作不可信输入处理。
    2. 需要逐条决定跳过与否（受保护文件）。

    Args:
        strip_top_level: 发布包通常有一层顶层目录（如 `Remy_v1.1.1/`），
            直接解压会得到嵌套目录，更新等于没生效。None 表示自动判断：
            所有条目共享同一个顶层目录时就剥掉它。
    """
    ok, detail = verify_zip(zip_path)
    if not ok:
        return ExtractResult(False, error=detail)

    protected = {p.lower() for p in protected}
    target_root = os.path.abspath(target_dir)
    result = ExtractResult(True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            # 文件名编码要先修一遍再算顶层目录/目标路径，否则中文名会
            # 以乱码落盘（见 _decode_name）。
            names = [_decode_name(info) for info in infos]
            # strip_top_level 为 None 时自动判断，为 False 时明确不剥
            prefix = "" if strip_top_level is False else _common_top_level(names)
            if prefix:
                logger.info("检测到顶层目录 %r，解压时剥掉", prefix)

            os.makedirs(target_root, exist_ok=True)
            for info, name in zip(infos, names):
                rel = _sanitize(name, prefix)
                if rel is None:
                    result.rejected.append(name)
                    logger.warning("拒绝不安全的压缩包条目：%r", name)
                    continue
                if not rel:                    # 顶层目录本身，剥掉后为空
                    continue
                if info.is_dir():
                    os.makedirs(os.path.join(target_root, rel), exist_ok=True)
                    continue
                if os.path.basename(rel).lower() in protected \
                        and os.path.exists(os.path.join(target_root, rel)):
                    # 只在目标已存在时才跳过：全新安装应该拿到默认配置
                    result.skipped.append(rel)
                    continue

                out = os.path.join(target_root, rel)
                os.makedirs(os.path.dirname(out) or target_root, exist_ok=True)
                with zf.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                result.extracted += 1
    except Exception as exc:
        return ExtractResult(False, error=f"解压失败：{exc}")

    return result


def _common_top_level(names: Iterable[str]) -> str:
    """所有条目是否共享同一个顶层目录。是则返回该目录名，否则返回 ""。"""
    tops = set()
    for n in names:
        n = n.replace("\\", "/").lstrip("/")
        if not n:
            continue
        head = n.split("/", 1)
        if len(head) == 1:
            return ""          # 有条目直接在根，说明没有统一顶层目录
        tops.add(head[0])
        if len(tops) > 1:
            return ""
    return tops.pop() if len(tops) == 1 else ""


def _decode_name(info: zipfile.ZipInfo) -> str:
    """把 zip 条目名按正确编码解码。

    zipfile 对未设 UTF-8 标志（bit 0x800）的条目名按 CP437 解码，而中文
    Windows 上打包工具（「发送到压缩文件夹」/ WinRAR 等）常用 GBK 存中文名，
    于是解出乱码（如「星夜颂歌-蕾咪！.exe」→「╨╟╥╣╦╠╕Φ-└┘▀Σúí.exe」）。
    这里把 CP437 解码出的字符还原成原始字节，再按 GBK / Big5 重解。
    """
    name = info.filename
    if info.flag_bits & 0x800:          # 已设 UTF-8 标志，zipfile 解对了
        return name
    try:
        raw = name.encode("cp437")      # CP437 无损，可还原原始字节
    except UnicodeEncodeError:
        return name                     # 有 CP437 外的字符，本就该原样
    for enc in ("gbk", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


def _sanitize(name: str, prefix: str = "") -> Optional[str]:
    """把压缩包内的条目名转成安全的相对路径。不安全则返回 None。

    拒绝：绝对路径、盘符（C:\\）、任何 `..` 段。
    """
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return None
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    if prefix and parts and parts[0] == prefix:
        parts = parts[1:]
    return "/".join(parts)


