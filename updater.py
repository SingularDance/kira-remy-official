# -*- coding: utf-8 -*-
"""启动时检查新版本。数据源为 GitHub Releases。

设计约束（与 music/ 包同一套纪律）：

1. **绝不阻塞启动**。本模块只提供纯逻辑；网络请求由调用方放进后台线程，
   超时 5 秒，失败静默降级。GitHub 在国内访问不稳定是常态，
   连不上、超时、限流都必须当作正常情况处理——桌宠照常启动。

2. **时间与网络都从外部注入**（`now` 参数、`fetch` 参数），
   所以「今天已经查过了」「跨天重新查」这类逻辑可以直接单测。

3. **不 import 项目内其他模块**（除 version.py，它零依赖）。
   这样它既能在重构前后的代码树里工作，也能在无 GUI 环境下测试。

4. **两条取版本的路，互为兜底**：

   a. GitHub API `/releases/latest` —— 首选。一次请求拿到 tag、
      资产下载地址、资产大小、changelog 正文。
   b. `github.com/.../releases/latest` 的 302 跳转 —— 兜底。
      从 Location 头里解析 tag，一个字节正文都不用下。

   为什么需要 b：未认证的 GitHub API 限流是 60 次/小时/IP。每天查一次
   远远够用，但学校或公司共用出口 IP 有可能撞上限流，那时 a 会返回 403。

5. **下载地址优先用 API 给的 `browser_download_url`**，只在拿不到资产时
   才用命名模板拼接。模板是脆的：哪天 release 里 zip 改名（加平台后缀、
   换分隔符），拼出来的链接会静默 404，而用户只会看到「下载失败」。
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

try:
    from version import GITHUB_OWNER, GITHUB_REPO
except ImportError:  # pragma: no cover - version.py 缺失时用默认值，不让程序崩
    GITHUB_OWNER, GITHUB_REPO = "SingularDance", "kira-remy-official"

logger = logging.getLogger(__name__)

API_LATEST_URL = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
HTML_LATEST_URL = "https://github.com/{owner}/{repo}/releases/latest"
DOWNLOAD_URL = ("https://github.com/{owner}/{repo}/releases/download/"
                "{tag}/{asset}")
RELEASES_PAGE_URL = "https://github.com/{owner}/{repo}/releases"

# 资产命名模板，仅在 API 未提供资产列表时用于拼接兜底
ASSET_TEMPLATE = "Remy_{tag}.zip"

# 检查更新的超时。启动路径上的请求宁可放弃，也不能让用户干等。
# 注意：**下载安装包用的是另一套超时**（见 downloader.py），别混用。
FETCH_TIMEOUT = 5

# 气泡台词。沿用项目里 EMOTION_PHRASES 的做法：硬编码而不是让 LLM 生成——
# 更新提示必须在没配 API Key、或 API 挂掉时也能正常显示。
#
# 台词刻意不带情绪关键词，表情不靠 detect_emotion 推断，而是由调用方
# （desktop_pet.py 更新分支）用 override_avatar 固定成 Remy_Expect（期待）。
# 这条链路由 tests/test_updater.py 校验（改台词会失败）。
UPDATE_PHRASES = [
    "蕾咪升级了哦，快看看嘛~",
]


class UpdateStatus(str, Enum):
    UPDATE_AVAILABLE = "update_available"  # 有新版本，该提示用户
    UP_TO_DATE = "up_to_date"              # 已是最新
    SKIPPED = "skipped"                    # 用户选过「跳过此版本」
    THROTTLED = "throttled"                # 今天已经查过了
    DISABLED = "disabled"                  # 用户关掉了自动检查
    ERROR = "error"                        # 网络或响应格式问题，静默处理


@dataclass(frozen=True)
class Release:
    """一次 GitHub Release 的解析结果。"""
    version: str                  # 去掉 v 前缀的版本号，用于比较与展示
    tag: str = ""                 # 原始 tag，如 'v1.1.1'，拼下载地址要用
    download_url: str = ""        # 安装包直链
    asset_name: str = ""          # 如 'Remy_v1.1.1.zip'
    size: int = 0                 # 字节数，下载后核对
    notes: str = ""               # release 正文，即 changelog
    page_url: str = ""            # 下载页，供「手动下载」兜底
    source: str = ""              # 'api' / 'redirect'，便于排查问题

    @property
    def size_mb(self) -> float:
        return round(self.size / 1024 / 1024, 1) if self.size else 0.0


@dataclass
class UpdateConfig:
    """对应 config.json 的 update 段。"""
    enabled: bool = True
    owner: str = GITHUB_OWNER
    repo: str = GITHUB_REPO
    # 用户点过「跳过此版本」的版本号
    skip_version: str = ""
    # 上次检查日期（YYYY-MM-DD）。每天最多查一次，避免频繁重启时反复请求
    last_check_date: str = ""

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "UpdateConfig":
        """容忍 config.json 里多出的未知字段，不让程序崩掉。"""
        d = d or {}
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "owner": self.owner,
            "repo": self.repo,
            "skip_version": self.skip_version,
            "last_check_date": self.last_check_date,
        }

    def url(self, template: str, **kw) -> str:
        return template.format(owner=self.owner, repo=self.repo, **kw)


@dataclass(frozen=True)
class UpdateCheckResult:
    status: UpdateStatus
    release: Optional[Release] = None
    # 是否真的发起过网络请求——调用方据此决定要不要写 last_check_date。
    # 被节流/被禁用时没请求过，不该刷新日期，否则永远查不到更新。
    attempted_network: bool = False
    detail: str = ""

    @property
    def should_notify(self) -> bool:
        return self.status is UpdateStatus.UPDATE_AVAILABLE


# ============================================================
# 版本号
# ============================================================

def parse_version(text: str) -> tuple:
    """把版本号解析成可比较的整数元组。

    **绝不能用字符串比较版本号**：`"1.10.0" < "1.9.0"` 在字符串比较下是 True，
    这是最经典的版本比较 bug。

    容忍 "v1.2.3"、"1.2.3-beta"、"1.2" 等写法；预发布后缀直接忽略
    （v1 不需要区分 beta 通道，真需要时再单独加字段，不要靠解析后缀猜）。
    解析不出任何数字时返回空元组，由调用方判为无效。
    """
    if not text:
        return ()
    return tuple(int(n) for n in re.findall(r"\d+", str(text)))


def normalize_version(tag: str) -> str:
    """把 tag 规整成版本号：'v1.1.1' → '1.1.1'。

    只剥前导的 v/V，不动其余部分——tag 里可能有别的信息，
    过度清洗会把有意义的内容丢掉。
    """
    return re.sub(r"^[vV]", "", (tag or "").strip())


def is_newer(remote: str, local: str) -> bool:
    """remote 是否比 local 新。任一侧无法解析时返回 False（保守：不提示）。"""
    r, l = parse_version(remote), parse_version(local)
    if not r or not l:
        return False
    # 补齐长度再比，避免 (1,2) 与 (1,2,0) 被判为不等
    width = max(len(r), len(l))
    return r + (0,) * (width - len(r)) > l + (0,) * (width - len(l))


# ============================================================
# 取最新 release
# ============================================================

def parse_api_release(raw: object, cfg: UpdateConfig) -> Optional[Release]:
    """解析 GitHub API `/releases/latest` 的响应。

    响应是远端内容，必须当作不可信输入：字段缺失、类型错误、
    限流时返回的 `{"message": "API rate limit exceeded"}`
    都可能出现。任何不合预期都返回 None。
    """
    if not isinstance(raw, dict):
        logger.warning("release 响应不是 JSON 对象，忽略")
        return None

    tag = str(raw.get("tag_name", "")).strip()
    version = normalize_version(tag)
    if not parse_version(version):
        # 限流响应会走到这里（只有 message 字段，没有 tag_name）
        logger.info("release 响应缺少可解析的 tag_name：%s",
                    str(raw.get("message", ""))[:80] or "(无 message)")
        return None

    asset_name, download_url, size = "", "", 0
    assets = raw.get("assets")
    if isinstance(assets, list):
        picked = _pick_asset(assets, tag)
        if picked:
            asset_name = str(picked.get("name", ""))
            download_url = str(picked.get("browser_download_url", "")).strip()
            try:
                size = max(0, int(picked.get("size", 0) or 0))
            except (TypeError, ValueError):
                size = 0

    if not download_url.startswith("https://"):
        # 拿不到资产（release 未挂附件）或地址不可信时，用命名模板兜底。
        # 这条路是脆的：zip 一改名就 404，所以只在无法可依时才走。
        asset_name = ASSET_TEMPLATE.format(tag=tag)
        download_url = cfg.url(DOWNLOAD_URL, tag=tag, asset=asset_name)
        size = 0
        logger.info("release 未提供可用资产，改用命名模板拼接：%s", download_url)

    return Release(
        version=version,
        tag=tag,
        download_url=download_url,
        asset_name=asset_name,
        size=size,
        notes=str(raw.get("body") or "").strip(),
        page_url=str(raw.get("html_url") or cfg.url(RELEASES_PAGE_URL)),
        source="api",
    )


def _pick_asset(assets: list, tag: str) -> Optional[dict]:
    """从资产列表里挑安装包。

    优先精确匹配命名模板，其次任意 .zip。不用「第一个资产」——
    release 里常常还挂着源码包、校验文件之类的东西。
    """
    wanted = ASSET_TEMPLATE.format(tag=tag).lower()
    zips = [a for a in assets
            if isinstance(a, dict) and str(a.get("name", "")).lower().endswith(".zip")]
    for a in zips:
        if str(a.get("name", "")).lower() == wanted:
            return a
    return zips[0] if zips else None


def fetch_via_api(cfg: UpdateConfig, timeout: int = FETCH_TIMEOUT,
                  get: Optional[Callable] = None) -> Optional[dict]:
    """调 GitHub API 取最新 release 的原始 JSON。失败返回 None。

    get 是注入点，默认 requests.get；测试注入假响应，避免联网。
    """
    if get is None:
        try:
            import requests
            get = requests.get
        except ImportError:  # pragma: no cover - 项目本身依赖 requests
            logger.warning("requests 不可用，跳过更新检查")
            return None

    url = cfg.url(API_LATEST_URL)
    try:
        # 显式声明 API 版本，避免 GitHub 将来改默认响应格式时被动挨打
        resp = get(url, timeout=timeout, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    except Exception as exc:
        # 断网、DNS 失败、超时、SSL 问题都走这里。GitHub 在国内不稳定，
        # 这是常态而非异常，用 info 级别别刷 warning。
        logger.info("更新检查失败（网络）：%s", exc)
        return None

    if resp.status_code == 403:
        logger.info("GitHub API 限流（60 次/小时/IP），改走 302 兜底")
        return None
    if resp.status_code != 200:
        logger.info("更新检查失败，HTTP %s", resp.status_code)
        return None

    try:
        return resp.json()
    except ValueError:
        logger.warning("release 响应不是合法 JSON（前 80 字符：%r）",
                       resp.text[:80])
        return None


def fetch_via_redirect(cfg: UpdateConfig,
                       timeout: int = FETCH_TIMEOUT,
                       get: Optional[Callable] = None) -> Optional[Release]:
    """兜底路径：从 `/releases/latest` 的 302 跳转里解析 tag。

    不下载任何正文，也不受 API 限流影响。代价是拿不到 changelog
    和资产大小，下载地址只能用命名模板拼。
    """
    if get is None:
        try:
            import requests
            get = requests.get
        except ImportError:  # pragma: no cover
            return None

    url = cfg.url(HTML_LATEST_URL)
    try:
        resp = get(url, timeout=timeout, allow_redirects=False)
    except Exception as exc:
        logger.info("更新检查兜底路径失败（网络）：%s", exc)
        return None

    location = resp.headers.get("Location", "")
    match = re.search(r"/releases/tag/([^/?#]+)", location)
    if not match:
        logger.info("兜底路径未能从跳转地址解析出 tag：HTTP %s，Location=%r",
                    resp.status_code, location[:120])
        return None

    tag = match.group(1)
    version = normalize_version(tag)
    if not parse_version(version):
        logger.info("兜底路径解析出的 tag 不含版本号：%r", tag)
        return None

    asset = ASSET_TEMPLATE.format(tag=tag)
    return Release(
        version=version,
        tag=tag,
        download_url=cfg.url(DOWNLOAD_URL, tag=tag, asset=asset),
        asset_name=asset,
        size=0,                       # 这条路拿不到大小，下载时无法核对
        notes="",                     # 也拿不到 changelog
        page_url=location,
        source="redirect",
    )


def fetch_latest_release(cfg: UpdateConfig,
                         timeout: int = FETCH_TIMEOUT,
                         get: Optional[Callable] = None) -> Optional[Release]:
    """取最新 release：API 优先，302 跳转兜底。两条都失败返回 None。"""
    raw = fetch_via_api(cfg, timeout, get)
    if raw is not None:
        release = parse_api_release(raw, cfg)
        if release is not None:
            return release
    # API 失败或响应不可用（限流、字段缺失）时才走兜底
    return fetch_via_redirect(cfg, timeout, get)


# ============================================================
# 主流程
# ============================================================

def today_str(now: float) -> str:
    return datetime.fromtimestamp(now).strftime("%Y-%m-%d")


def check_for_update(current_version: str,
                     cfg: UpdateConfig,
                     now: float,
                     fetch: Optional[Callable[[UpdateConfig], Optional[Release]]] = None,
                     force: bool = False) -> UpdateCheckResult:
    """检查是否有新版本。

    Args:
        current_version: 当前运行的版本号，通常传 version.VERSION
        cfg: 更新相关配置
        now: 当前时间戳（外部注入，便于测试跨天逻辑）
        fetch: 取 release 的函数，默认走网络；测试时注入假实现
        force: 用户从右键菜单手动触发。强制忽略「今天已查过」和总开关，
               并忽略 skip_version——用户主动点了，就该给他看结果

    调用方拿到结果后需要自己把 `cfg.last_check_date` 写回 config.json
    （见 `attempted_network`），本函数不做持久化。
    """
    if not cfg.enabled and not force:
        return UpdateCheckResult(UpdateStatus.DISABLED,
                                 detail="用户已关闭自动检查")

    if not force and cfg.last_check_date == today_str(now):
        return UpdateCheckResult(UpdateStatus.THROTTLED,
                                 detail="今天已检查过")

    fetcher = fetch or fetch_latest_release
    release = fetcher(cfg)
    if release is None:
        return UpdateCheckResult(UpdateStatus.ERROR, attempted_network=True,
                                 detail="获取 release 失败")

    if not is_newer(release.version, current_version):
        return UpdateCheckResult(UpdateStatus.UP_TO_DATE, release,
                                 attempted_network=True)

    if not force and release.version == cfg.skip_version:
        return UpdateCheckResult(UpdateStatus.SKIPPED, release,
                                 attempted_network=True,
                                 detail="用户已跳过此版本")

    return UpdateCheckResult(UpdateStatus.UPDATE_AVAILABLE, release,
                             attempted_network=True)


# ============================================================
# 提示文案
# ============================================================

def bubble_phrase(rng: Optional[random.Random] = None) -> str:
    """蕾咪用来宣布新版本的气泡台词。

    刻意不带版本号：气泡有 37 字上限，塞版本号会挤掉人格表达，
    具体版本号放在托盘通知和更新对话框里。
    """
    return (rng or random).choice(UPDATE_PHRASES)


def tray_message(release: Release) -> tuple:
    """托盘通知的 (标题, 正文)。这里才是给出确切版本号的地方。"""
    size = f"（{release.size_mb} MB）" if release.size else ""
    return ("蕾咪桌宠", f"发现新版本 {release.version}{size}，点击查看")
